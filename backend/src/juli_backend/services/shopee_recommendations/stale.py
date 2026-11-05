"""Staleness: which open recommendations an input change (Step 4's seller import) affects,
and the re-run of only those.

``mark_stale_for(session, shop_id, product_ids=..., sku_ids=..., shop_wide=...)`` is the
function the importer calls (through ``shop_inputs.register_recompute_hook`` -- this package
registers :func:`on_stale_request` at import). It flags open cards (``draft`` / ``sent`` /
``changes_requested`` / ``approved``) whose products or SKUs changed -- or, shop-wide (margin
target / marketing cap changes), every card of a target-sensitive family -- in
``action_cards.metadata_json`` (``stale`` + reason + time). It writes nothing else and returns
the number flagged. ``rerun_stale`` then recomputes ONLY those cards: a draft is replaced, a
sent / changes-requested one is revised through ADR-118's ``revise`` (the old text stays what
the client saw); an approved one is left as approved and stays flagged for a person to review.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_SENT,
    ShopProposal,
)
from juli_backend.services.shop_inputs.affected import StaleRequest
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shopee_recommendations import freshness, product_queue, store
from juli_backend.services.shopee_recommendations.cards import proposal_fields
from juli_backend.services.shopee_recommendations.env import RecoEnv

OPEN = (STATUS_DRAFT, STATUS_SENT, STATUS_CHANGES_REQUESTED, STATUS_APPROVED)
#: Families judged against the operating floor / spend cap: a shop-wide target change moves them.
TARGET_SENSITIVE_FAMILIES = ("promotion", "voucher", "sale", "ads", "combo", "mega_sale")
REASON = "seller_inputs_changed"


def _sku_matches(card_skus: Iterable[str], items: Iterable[str], wanted: set[str]) -> bool:
    card_set = set(card_skus)
    if card_set & wanted:
        return True
    for w in wanted:  # "item_id:variation_id" scope of an imported rule
        head = w.split(":", 1)[0]
        if head in set(items):
            return True
    return False


async def mark_stale_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_ids: Iterable[str] | None = None,
    sku_ids: Iterable[str] | None = None,
    *,
    shop_wide: bool = False,
    reason: str = REASON,
    now: datetime | None = None,
) -> int:
    """Flag the open cards affected by a change to these products / SKUs (or shop-wide)."""
    items = {str(i) for i in (product_ids or ())}
    skus = {str(s) for s in (sku_ids or ())}
    if not items and not skus and not shop_wide:
        return 0
    rows = (
        await session.execute(
            select(ShopProposal.id, ActionCard)
            .join(ActionCard, ActionCard.id == ShopProposal.id)
            .where(
                ShopProposal.shop_id == shop_id,
                ActionCard.status == store.CARD_STATUS,
                ShopProposal.status.in_(OPEN),
            )
        )
    ).all()
    n = 0
    for _, card_row in rows:
        meta = json.loads(card_row.metadata_json or "{}")
        payload_items = set(meta.get("locked_items", []))
        hit = bool(items & payload_items)
        if not hit and skus:
            payload = await store.card_payload(session, shop_id, card_row.id)
            card_skus = (payload or {}).get("scope", {}).get("sku_ids", [])
            hit = _sku_matches(card_skus, payload_items, skus)
        if not hit and shop_wide and meta.get("family") in TARGET_SENSITIVE_FAMILIES:
            hit = True
        if hit and not meta.get("stale"):
            meta.update(
                {
                    "stale": True,
                    "stale_reason": reason,
                    "stale_at": (now or datetime.now(UTC).replace(tzinfo=None)).isoformat(),
                }
            )
            card_row.metadata_json = json.dumps(meta)
            n += 1
        elif hit:
            n += 1
    await session.flush()
    return n


async def on_stale_request(
    session: AsyncSession, shop_id: uuid.UUID, request: StaleRequest
) -> None:
    """The ``shop_inputs`` hook: SKU ids and item ids arrive together in ``item_ids``."""
    from juli_backend.services import shopee_reco_refresh

    ids = list(request.item_ids)
    await mark_stale_for(
        session,
        shop_id,
        product_ids=ids,
        sku_ids=ids,
        shop_wide=request.shop_wide,
        reason=request.reason,
        now=request.changed_at,
    )
    # Recompute what the write touched once it has committed (background, idempotent).
    shopee_reco_refresh.schedule_after_commit(session, shop_id, request.reason)


async def stale_cards(session: AsyncSession, shop_id: uuid.UUID) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    rows = (
        await session.execute(
            select(ActionCard.id, ActionCard.metadata_json)
            .join(ShopProposal, ShopProposal.id == ActionCard.id)
            .where(
                ShopProposal.shop_id == shop_id,
                ActionCard.status == store.CARD_STATUS,
                ShopProposal.status.in_(OPEN),
            )
        )
    ).all()
    for cid, meta in rows:
        if json.loads(meta or "{}").get("stale"):
            out.append(cid)
    return out


async def rerun_stale(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    resend: bool = False,
    env: RecoEnv | None = None,
) -> dict[str, Any]:
    """Recompute only the flagged cards on a fresh environment. Returns the counts.

    ``resend``: a card the shop had been sent comes back as a sent card (the automatic refresh), not
    as a draft Ops must send again, so the seller never loses it."""
    from juli_backend.services.shopee_recommendations import service
    from juli_backend.services.shopee_recommendations.loader import load_env

    now = now.replace(tzinfo=None)
    ids = await stale_cards(session, shop_id)
    counts = {"stale": len(ids), "replaced": 0, "revised": 0, "kept_approved": 0, "dropped": 0}
    if not ids:
        return counts
    env = env or await load_env(session, shop_id, now=now)
    if env is None:
        return counts
    for cid in ids:
        p = await session.scalar(select(ShopProposal).where(ShopProposal.id == cid))
        card = await store.card_payload(session, shop_id, cid)
        if p is None or card is None:
            continue
        if p.status == STATUS_APPROVED:
            counts["kept_approved"] += 1
            continue
        new = service.refresh_card(env, card, now=now)
        if new is None:
            counts["dropped"] += 1
            await proposals.withdraw(session, p, now=now)
            continue
        new["rank"] = card.get("rank")
        if p.status == STATUS_DRAFT:
            await proposals.withdraw(session, p, now=now)
            await store.save_card(
                session,
                shop_id,
                new,
                cycle=p.cycle,
                position=(card.get("rank") or {}).get("position", 0),
                now=now,
                supersedes=p.id,
            )
            counts["replaced"] += 1
        else:
            fields = proposal_fields(new, "")
            draft = proposals.ProposalDraft(
                cycle=p.cycle,
                kind=fields["kind"],
                subject_type=fields["subject_type"],
                subject_label=fields["subject_label"],
                change_after=fields["change_after"],
                reason=fields["reason"],
                item_id=fields["item_id"],
                change_before=fields["change_before"],
            )
            successor = await proposals.revise(session, p, draft, staff_id=None, now=now)
            await store.save_card(
                session,
                shop_id,
                new,
                cycle=p.cycle,
                position=(card.get("rank") or {}).get("position", 0),
                now=now,
                existing=successor,
            )
            if resend:
                await proposals.send(session, successor, now=now)
            counts["revised"] += 1
    await product_queue.requeue_shop(session, shop_id, now)
    return counts


async def mark_stale_by_freshness(
    session: AsyncSession, shop_id: uuid.UUID, env: RecoEnv, *, now: datetime
) -> dict[str, int]:
    """Flag every open card (or version) computed by another engine version or on other inputs
    than ``env`` reads now. Returns ``{checked, flagged}``; flags only, recomputes nothing."""
    rows = (
        (
            await session.execute(
                select(ActionCard)
                .join(ShopProposal, ShopProposal.id == ActionCard.id)
                .where(
                    ShopProposal.shop_id == shop_id,
                    ActionCard.status == store.CARD_STATUS,
                    ShopProposal.status.in_(OPEN),
                )
            )
        )
        .scalars()
        .all()
    )
    checked = flagged = 0
    for row in rows:
        card = await store.card_payload(session, shop_id, row.id)
        if card is None:
            continue
        checked += 1
        why = freshness.card_stale_reason(card, env)
        if why is None:
            continue
        flagged += 1
        meta = json.loads(row.metadata_json or "{}")
        if not meta.get("stale"):
            meta.update({"stale": True, "stale_reason": why, "stale_at": now.isoformat()})
            row.metadata_json = json.dumps(meta)
    await session.flush()
    return {"checked": checked, "flagged": flagged}


__all__ = [
    "mark_stale_by_freshness",
    "date",
    "mark_stale_for",
    "on_stale_request",
    "rerun_stale",
    "stale_cards",
]
