"""The per-product queue of open cards (P91 D-1).

Every card that passes the hard filters is kept. The open cards of one product form a queue,
best first; ``product_queue`` 1 is the card the Quyết định list shows, the others wait on the
Sản phẩm page. When the first card closes the next one moves up.

Closed for the queue (the card gives its place up, all at once): ``rejected`` (dismissed),
``withdrawn``, ``superseded``, ``executed`` (owner 2026-11-04: the next card is up right away),
``measured``, and a ``sent`` card with an ``expired`` event. ``planned`` (D-6, the draft plan)
also takes a card out of the queue and gives it back when it leaves the plan (removed) or when the
plan is confirmed (the card is then ``approved``). A card the seller approved goes ahead of
waiting cards.

A product whose executed change is still inside its planned measurement window is "being
measured": :func:`measuring` derives ``product_measuring = {until, change_set}`` for it (a
read-only derivation; ``change_set`` stays None until D-8) and the open cards of that product
carry it, so the UI can say "Sản phẩm đang đo: còn N ngày". The window ends the day after
``start + plan days`` begins, or when an ``impact_final`` reading exists (the rule
``measure.read_cards`` uses), where ``start`` is the read-back's ``verified`` time, else the
execution time.

Storage: ``shop_proposals.product_queue`` (migration 116), written by :func:`requeue_products`
-- a column, so the list filters on it with an index and the refs read it for free. The numbers
come from the pure :func:`assign`; :func:`requeue_shop` is the idempotent entry the beat and the
measurement job call, and every status transition calls :func:`requeue_products` for its product.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    EVENT_EXPIRED,
    EVENT_IMPACT_FINAL,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_SENT,
    ShopProposal,
    ShopProposalExecution,
)
from juli_backend.services.shopee_recommendations import config

OPEN_STATUSES = (STATUS_DRAFT, STATUS_SENT, STATUS_CHANGES_REQUESTED, STATUS_APPROVED)
_LAST = 10**6


@dataclass(frozen=True)
class QueueCard:
    id: str
    product: str | None  # the card's primary product; None = shop / campaign card, no queue
    status: str
    score: float  # ranking score at generation (higher = better)
    queue: int | None = None  # the stored place, only a tie-break
    expired: bool = False  # a `sent` card whose 7 days passed without a decision
    #: ISO time a person pinned the card to place 1 (a manual card made with ``primary``); the
    #: newest pin leads, the previous head moves to 2
    pinned_at: str | None = None


def holds_place(card: QueueCard) -> bool:
    """True when the card is still open for the queue."""
    if card.product is None:
        return False
    if card.status in OPEN_STATUSES:
        return not card.expired
    return False  # executed, planned, rejected, withdrawn, superseded, measured


def _pin_rank(c: QueueCard) -> tuple[int, float]:
    """Pinned cards first, the newest pin leading (ISO strings of one clock order as text)."""
    if not c.pinned_at:
        return (1, 0.0)
    return (0, -datetime.fromisoformat(c.pinned_at).timestamp())


def assign(cards: Iterable[QueueCard]) -> dict[str, int | None]:
    """The place of every card: 1..n among the open cards of its product (seller-chosen cards
    first, then best score; the stored place and the id break ties), None for a closed card or
    one with no product. Pure and stable: the same cards always give the same numbers."""
    out: dict[str, int | None] = {}
    by_product: dict[str, list[QueueCard]] = {}
    for c in cards:
        out[c.id] = None
        if holds_place(c):
            by_product.setdefault(c.product or "", []).append(c)
    for group in by_product.values():
        group.sort(
            key=lambda c: (
                _pin_rank(c),
                0 if c.status in config.QUEUE_IN_FLIGHT else 1,
                -c.score,
                c.queue if c.queue is not None else _LAST,
                c.id,
            )
        )
        for n, c in enumerate(group, start=1):
            out[c.id] = n
    return out


def window_over(
    *,
    executed_at: datetime | None,
    verified_at: datetime | None,
    plan_days: int | None,
    has_final_reading: bool,
    now: datetime,
) -> bool:
    """Whether an executed card's measurement window is over."""
    if has_final_reading:
        return True
    start = verified_at or executed_at
    if start is None:
        return False
    days = plan_days or config.QUEUE_DEFAULT_PLAN_DAYS
    return now.date() >= (start + timedelta(days=days + 1)).date()


# ------------------------------------------------------------------------------ storage


def _meta(raw: str | None) -> Mapping[str, object]:
    return json.loads(raw) if raw else {}


async def requeue_products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    products: Iterable[str] | None,
    now: datetime,
) -> int:
    """Renumber the queues of these products (None = every product of the shop). Writes only
    the rows whose place changed and returns how many did, so it is safe to run again."""
    now = now.replace(tzinfo=None) if now.tzinfo else now
    stmt = (
        select(
            ShopProposal,
            ActionCard.metadata_json,
            ActionCard.priority,
        )
        .join(ActionCard, ActionCard.id == ShopProposal.id)
        .where(
            ShopProposal.shop_id == shop_id,
            ActionCard.status == "shopee_reco",
            ShopProposal.item_id.is_not(None),
        )
    )
    wanted = None if products is None else {str(p) for p in products}
    if wanted is not None:
        if not wanted:
            return 0
        stmt = stmt.where(ShopProposal.item_id.in_(sorted(wanted)))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return 0
    ids = [r[0].id for r in rows if r[0].status == STATUS_SENT]
    expired: set[uuid.UUID] = set()
    if ids:
        expired = set(
            await session.scalars(
                select(CardEvent.card_id).where(
                    CardEvent.shop_id == shop_id,
                    CardEvent.card_id.in_(ids),
                    CardEvent.event_type == EVENT_EXPIRED,
                )
            )
        )
    cards: list[QueueCard] = []
    for p, raw_meta, priority in rows:
        meta = _meta(raw_meta)
        score = meta.get("rank_score")
        cards.append(
            QueueCard(
                id=str(p.id),
                product=p.item_id,
                status=p.status,
                score=float(score) if isinstance(score, int | float) else -float(priority or 0),
                queue=p.product_queue,
                expired=p.id in expired,
                pinned_at=str(meta["primary_at"])
                if meta.get("primary") and meta.get("primary_at")
                else None,
            )
        )
    places = assign(cards)
    changed = 0
    for p, _, _ in rows:
        new = places[str(p.id)]
        if p.product_queue != new:
            p.product_queue = new
            changed += 1
    if changed:
        await session.flush()
    return changed


async def requeue_shop(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> int:
    """Idempotent re-queue of the whole shop: what the beat and the measurement job run, so a
    window that ended (no event marks the day it does) hands its product to the next card."""
    return await requeue_products(session, shop_id, None, now)


async def measuring(
    session: AsyncSession,
    shop_id: uuid.UUID,
    now: datetime,
    products: Iterable[str] | None = None,
) -> dict[str, dict[str, object]]:
    """``{product: {"until": "YYYY-MM-DD", "change_set": None}}`` for each product with an
    executed card whose planned measurement window has not ended (the latest end wins).
    ``until`` is the last day of the window (the change set's chosen window, P91 D-8, stored as the
    card's ``plan_days``); ``change_set`` is its id (None for a card executed before change sets).
    A measurement a later change cut is no longer running."""
    now = now.replace(tzinfo=None) if now.tzinfo else now
    stmt = (
        select(ShopProposal.id, ShopProposal.item_id, ActionCard.metadata_json)
        .join(ActionCard, ActionCard.id == ShopProposal.id)
        .where(
            ShopProposal.shop_id == shop_id,
            ActionCard.status == "shopee_reco",
            ShopProposal.status == STATUS_EXECUTED,
            ShopProposal.item_id.is_not(None),
        )
    )
    if products is not None:
        wanted = sorted({str(p) for p in products})
        if not wanted:
            return {}
        stmt = stmt.where(ShopProposal.item_id.in_(wanted))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {}
    ids = [r[0] for r in rows]
    executed_at = dict(
        (
            await session.execute(
                select(
                    ShopProposalExecution.proposal_id, func.max(ShopProposalExecution.executed_at)
                )
                .where(ShopProposalExecution.proposal_id.in_(ids))
                .group_by(ShopProposalExecution.proposal_id)
            )
        ).all()
    )
    verified: dict[uuid.UUID, datetime] = {}
    final: set[uuid.UUID] = set()
    for cid, etype, at in await session.execute(
        select(CardEvent.card_id, CardEvent.event_type, CardEvent.occurred_at).where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id.in_(ids),
            CardEvent.event_type.in_([EVENT_VERIFIED, EVENT_IMPACT_FINAL]),
        )
    ):
        if etype == EVENT_VERIFIED:
            at = at.replace(tzinfo=None)
            verified[cid] = max(at, verified.get(cid, at))
        else:
            final.add(cid)
    out: dict[str, dict[str, object]] = {}
    for pid, item, raw in rows:
        if _meta(raw).get("measure_cut_at"):
            continue  # a later change cut this measurement (change_sets.cut)
        plan = _meta(raw).get("plan_days")
        plan_days = int(plan) if isinstance(plan, int | float) else None
        if window_over(
            executed_at=executed_at.get(pid),
            verified_at=verified.get(pid),
            plan_days=plan_days,
            has_final_reading=pid in final,
            now=now,
        ):
            continue
        start = verified.get(pid) or executed_at.get(pid)
        if start is None:
            continue
        until = (start + timedelta(days=plan_days or config.QUEUE_DEFAULT_PLAN_DAYS)).date()
        if item not in out or until.isoformat() > str(out[item]["until"]):
            out[item] = {"until": until.isoformat(), "change_set": _meta(raw).get("change_set")}
    return out
