"""Write the nightly content cards (P14-E, D24.4 / D24.17 / D24.18).

Called once per scoring run from ``action_cards.persist.emit_scoring_cards``
(the clearly marked P14-E hook), after the Optimize Product cards. Rules and
arithmetic only (D24.1): the card text is a template.

Per shop:

1. read the newest stored ``seller_video × ctr`` and ``seller_live × ctor``
   rankings (ADR-109 d.5) and turn them into candidates (``candidates``);
2. **maintain** the open content cards: a card surfaced more than
   :data:`~.constants.VALIDITY_DAYS` ago expires (withdrawn, ``expired_at``
   stamped — the same action on the same product returns no earlier than
   :data:`~.constants.COOLDOWN_DAYS` later); a never-surfaced draft no longer
   proposed is withdrawn; a surfaced card is withdrawn early only when it is
   no longer valid (product inactive, metric already at target) — never for
   dropping in rank, and never inside its first
   :data:`~.constants.MIN_SURFACED_DAYS` days for any other reason;
3. **emit** each candidate, best expected GMV first: skip a product not in
   the catalogue / not active, a (product, lever) in the seller's 7-day reason
   cooldown (``decision_reasons``), a card whose run is in flight or was
   approved in the last :data:`MEASURING_DAYS` days (no overlapping change in
   measurement, D24.2), an expiry cooldown; refresh an open card's numbers in
   place (D24.17: "re-scored daily"); otherwise write a new revision — at most
   :data:`~.constants.WEEKLY_CONTENT_CARDS` new content cards per ISO week
   (D24.17 sub-limit).

Surfacing (how many show, the day-1 content slot) is the emission budget's
job; this module writes candidates with ``status="active"`` and never touches
``surfaced_at``. No commit.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.services import decision_reasons
from juli_backend.services.action_cards.subjects import SUBJECT_TYPE_PRODUCT, CardSubject
from juli_backend.services.content_cards import copy
from juli_backend.services.content_cards.candidates import (
    ContentCandidate,
    candidates_from_ranking,
    merge_ranked,
    product_rate,
)
from juli_backend.services.content_cards.constants import (
    CHIP_VI,
    CONTENT_WORKFLOW_KEYS,
    COOLDOWN_DAYS,
    EXECUTOR_JULI_DRAFTS,
    LIVE,
    MIN_SURFACED_DAYS,
    PAYLOAD_VERSION,
    SPEC_BY_WORKFLOW,
    SPECS,
    VALIDITY_DAYS,
    VIDEO,
    WEEKLY_CONTENT_CARDS,
    ContentKind,
)

logger = logging.getLogger(__name__)

_ACTIVE = "active"
_WITHDRAWN = "withdrawn"
#: Set by ``action_cards.emission_budget`` on a surfaced card past its validity.
_EXPIRED = "expired"
_IN_FLIGHT = frozenset({"approved", "executing"})
_SEVERITY = "warning"
#: An approved content card blocks a new one on the same product and lever for
#: this long: publish wait (7) + measurement (14).
MEASURING_DAYS = 21
#: TikTok product statuses a card is never proposed for (out of sale).
_NOT_SELLABLE = frozenset(
    {
        "DRAFT",
        "PENDING",
        "FAILED",
        "FREEZE",
        "DELETED",
        "SELLER_DEACTIVATED",
        "PLATFORM_DEACTIVATED",
    }
)

SUPPRESSED_EXPIRY_COOLDOWN = "content_expiry_cooldown"
SUPPRESSED_IN_FLIGHT = "content_in_flight"
SUPPRESSED_WEEKLY_CAP = "content_weekly_cap"
SUPPRESSED_NOT_SELLABLE = "content_product_not_sellable"

EXPIRED_AT_KEY = "expired_at"
WITHDRAWN_WHY_KEY = "withdrawn_why"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _week_start(now: datetime) -> datetime:
    day = now.astimezone(UTC).date()
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


def _metadata(card: ActionCard) -> dict[str, Any]:
    try:
        data = json.loads(card.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def payload_of(card: ActionCard) -> dict[str, Any]:
    try:
        data = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sellable(product: Product) -> bool:
    return (product.status or "").upper() not in _NOT_SELLABLE


@dataclass(frozen=True)
class ProductFacts:
    """What the card copy needs about one product."""

    product: Product
    seller_sku: str | None
    sku_count: int
    sku_ids: tuple[str, ...]

    @property
    def title(self) -> str:
        return self.product.title or self.product.name or ""

    @property
    def label(self) -> str:
        return copy.product_label(self.seller_sku, self.title)


async def _product_facts(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_ids: set[str]
) -> dict[str, ProductFacts]:
    if not tiktok_ids:
        return {}
    products = (
        await session.execute(
            select(Product).where(
                Product.shop_id == shop_id, Product.tiktok_product_id.in_(tiktok_ids)
            )
        )
    ).scalars()
    by_id = {str(p.tiktok_product_id): p for p in products}
    skus: dict[str, list[InventoryItem]] = defaultdict(list)
    if by_id:
        rows = (
            await session.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.shop_id == shop_id,
                    InventoryItem.tiktok_product_id.in_(set(by_id)),
                )
                .order_by(InventoryItem.tiktok_sku_id.asc())
            )
        ).scalars()
        for item in rows:
            skus[str(item.tiktok_product_id)].append(item)
    out: dict[str, ProductFacts] = {}
    for pid, product in by_id.items():
        items = skus.get(pid, [])
        seller = next((i.seller_sku for i in items if i.seller_sku), None)
        out[pid] = ProductFacts(
            product=product,
            seller_sku=seller,
            sku_count=len(items),
            sku_ids=tuple(str(i.tiktok_sku_id) for i in items if i.tiktok_sku_id),
        )
    return out


async def _discount_caps(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, float]:
    """TikTok SKU id -> the seller's max discount % (Quy tắc)."""
    from juli_backend.services import shop_rules

    rules = await shop_rules.get_rules(session, shop_id)
    out: dict[str, float] = {}
    for sku_id, value in rules.max_discount_pct.items():
        try:
            out[str(sku_id)] = float(value.value)
        except (TypeError, ValueError):
            continue
    return out


def product_discount_cap(facts: ProductFacts, caps: Mapping[str, float]) -> float | None:
    """The product's discount cap: the lowest cap among its SKUs that have one."""
    values = [caps[s] for s in facts.sku_ids if s in caps]
    return min(values) if values else None


def build_payload(
    candidate: ContentCandidate,
    facts: ProductFacts,
    *,
    priority: int,
    computed_at: datetime,
    discount_cap_pct: float | None,
) -> dict[str, Any]:
    """The ``recommendation_payload`` of one content card (no ``diagnosis`` key)."""
    spec = candidate.spec
    product = facts.product
    subject = {"type": SUBJECT_TYPE_PRODUCT, "id": str(product.id), "label": facts.title}
    reason_full = copy.reason_full(candidate)
    return {
        "workflow_key": spec.workflow_key,
        "workflow_name": spec.workflow_label,
        "priority": priority,
        "rationale": spec.reason_short,
        "expected_impact": {
            "metric": "recoverable_gmv_per_day",
            "value": round(candidate.recoverable_gmv_per_day, 2),
            "confidence": "rule_based_estimate",
        },
        "preconditions_met": True,
        "user_action_required": True,
        "source_kpi_ids": [],
        "computed_at": computed_at.isoformat(),
        "subject": subject,
        "card_executor": EXECUTOR_JULI_DRAFTS,
        "reasoning": {
            "copy_source": "p14_content_rules",
            "why": spec.reason_short,
            "expected_impact": copy.impact_sentence(candidate.recoverable_gmv_per_day),
            "next_steps": [spec.action_label],
            "source_kpi_ids": [],
        },
        "content": {
            "version": PAYLOAD_VERSION,
            "kind": candidate.kind,
            "lever_code": spec.lever_code,
            "metric": spec.kpi_key,
            "stage_rate": "ctr" if candidate.kind == VIDEO else "ctor",
            "current": candidate.current,
            "target": candidate.target,
            "recoverable_gmv_per_day": round(candidate.recoverable_gmv_per_day, 2),
            "volume": round(candidate.volume, 2),
            "rows": [row.to_json() for row in candidate.rows],
            "as_of": candidate.as_of,
            "tiktok_product_id": candidate.tiktok_product_id,
            "product_title": facts.title,
            "product_label": facts.label,
            "reason_short": spec.reason_short,
            "reason_full": reason_full,
            "action_label": spec.action_label,
            "chip": CHIP_VI,
            "will_draft": copy.will_draft(
                candidate.kind, facts.label, discount_cap_pct=discount_cap_pct
            ),
            "measure": copy.measure_line(candidate.kind, facts.label),
            "discount_cap_pct": discount_cap_pct,
        },
    }


def _write(
    card: ActionCard,
    candidate: ContentCandidate,
    payload: dict[str, Any],
    *,
    priority: int,
    computed_at: datetime,
) -> None:
    spec = candidate.spec
    content = payload["content"]
    title = content["product_title"] or content["product_label"]
    short = title if len(title) <= 60 else title[:59].rstrip() + "…"
    card.priority = priority
    card.severity = _SEVERITY
    card.title = f"{spec.action_label} · {short}"
    card.description = f"{spec.reason_short}. {content['reason_full']}"
    card.recommendation_payload = json.dumps(payload, ensure_ascii=False)
    metadata = _metadata(card)
    metadata.pop(WITHDRAWN_WHY_KEY, None)
    metadata.pop(EXPIRED_AT_KEY, None)
    metadata.update({"computed_at": computed_at.isoformat(), "content_kind": candidate.kind})
    card.metadata_json = json.dumps(metadata)
    card.computed_at = computed_at


def _withdraw(card: ActionCard, *, why: str, now: datetime) -> None:
    metadata = _metadata(card)
    metadata[WITHDRAWN_WHY_KEY] = why
    if why == "expired":
        metadata[EXPIRED_AT_KEY] = now.isoformat()
    card.metadata_json = json.dumps(metadata)
    card.status = _WITHDRAWN
    card.surfaced_at = None
    card.suppressed_reason = None


def expired_recently(card: ActionCard, *, now: datetime) -> bool:
    """A card that expired less than ``COOLDOWN_DAYS`` ago.

    Expired here (withdrawn, ``expired_at`` stamped) or by the emission budget
    (status ``expired``, same ``expired_at`` key; P14 card limits, D24.17).
    """
    if card.status == _EXPIRED:
        from juli_backend.services.action_cards.emission_budget import expired_card_returns

        return not expired_card_returns(
            card, now=now, cooldown_days=COOLDOWN_DAYS, validity_days=VALIDITY_DAYS
        )
    if card.status != _WITHDRAWN:
        return False
    raw = _metadata(card).get(EXPIRED_AT_KEY)
    if not isinstance(raw, str):
        return False
    try:
        expired = _aware(datetime.fromisoformat(raw))
    except ValueError:
        return False
    return expired is not None and now - expired < timedelta(days=COOLDOWN_DAYS)


def card_expired(card: ActionCard, *, now: datetime) -> bool:
    """An open card older than its validity (counted from when it was first shown)."""
    shown = _aware(card.surfaced_at)
    return shown is not None and now - shown > timedelta(days=VALIDITY_DAYS)


async def _latest_cards(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[tuple[str, str], ActionCard]:
    """(workflow_key, subject_id) -> the newest revision, for every content chain."""
    rows = (
        await session.execute(
            select(ActionCard)
            .where(
                ActionCard.shop_id == shop_id,
                ActionCard.workflow_key.in_(CONTENT_WORKFLOW_KEYS),
            )
            .order_by(ActionCard.revision.asc())
        )
    ).scalars()
    return {(card.workflow_key, card.subject_id): card for card in rows}


async def _created_this_week(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> int:
    start = _week_start(now).replace(tzinfo=None)
    stmt = select(func.count(ActionCard.id)).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key.in_(CONTENT_WORKFLOW_KEYS),
        ActionCard.created_at >= start,
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


def _subject(product: Product) -> CardSubject:
    return CardSubject(
        subject_type=SUBJECT_TYPE_PRODUCT,
        subject_id=str(product.id),
        label=product.title or product.name,
    )


async def _load_rankings(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[ContentKind, Mapping[str, Any] | None]:
    from juli_backend.services.shop_diagnosis.channels import Channel
    from juli_backend.services.shop_diagnosis.rankings import Metric
    from juli_backend.services.shop_diagnosis_daily.read import latest_metric_ranking

    video = await latest_metric_ranking(session, shop_id, Channel.SELLER_VIDEO, Metric.CTR)
    live = await latest_metric_ranking(session, shop_id, Channel.SELLER_LIVE, Metric.CTOR)
    return {
        VIDEO: video.ranking if video is not None else None,
        LIVE: live.ranking if live is not None else None,
    }


async def emit_content_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    rankings: Mapping[ContentKind, Mapping[str, Any] | None] | None = None,
) -> list[Any]:
    """Maintain and emit the shop's content cards. Returns ``persist.CardEmission`` values."""
    from juli_backend.services.action_cards import persist

    now = _aware(now) or datetime.now(UTC)
    tables = rankings if rankings is not None else await _load_rankings(session, shop_id)
    candidates = merge_ranked(
        candidates_from_ranking(tables.get(VIDEO), VIDEO),
        candidates_from_ranking(tables.get(LIVE), LIVE),
    )
    latest = await _latest_cards(session, shop_id)
    ids = {c.tiktok_product_id for c in candidates}
    open_product_ids: set[str] = set()
    for card in latest.values():
        tiktok_id = payload_of(card).get("content", {}).get("tiktok_product_id")
        if card.status == _ACTIVE and isinstance(tiktok_id, str):
            open_product_ids.add(tiktok_id)
    facts = await _product_facts(session, shop_id, ids | open_product_ids)
    proposed = {(c.spec.workflow_key, c.tiktok_product_id) for c in candidates}

    # -- 2. maintenance of the open cards ------------------------------------------
    withdrawn = 0
    for (workflow_key, _subject_id), card in latest.items():
        if card.status != _ACTIVE:
            continue
        content = payload_of(card).get("content") or {}
        tiktok_id = str(content.get("tiktok_product_id") or "")
        spec = SPEC_BY_WORKFLOW[workflow_key]
        product_facts = facts.get(tiktok_id)
        if card_expired(card, now=now):
            _withdraw(card, why="expired", now=now)
            withdrawn += 1
        elif product_facts is None or not _sellable(product_facts.product):
            _withdraw(card, why="product_not_sellable", now=now)
            withdrawn += 1
        elif (workflow_key, tiktok_id) not in proposed:
            if card.surfaced_at is None:
                _withdraw(card, why="not_proposed", now=now)
                withdrawn += 1
                continue
            rate = product_rate(tables.get(spec.kind), tiktok_id)
            target = content.get("target")
            if rate is not None and isinstance(target, int | float) and rate >= float(target):
                _withdraw(card, why="at_target", now=now)
                withdrawn += 1
            # else: still valid, numbers unchanged — stays (≥ MIN_SURFACED_DAYS by rule).

    # -- 3. emit ------------------------------------------------------------------
    cooldowns = await decision_reasons.active_cooldowns(session, shop_id, now=now)
    caps = await _discount_caps(session, shop_id)
    created = await _created_this_week(session, shop_id, now)
    decisions: list[Any] = []
    for priority, candidate in enumerate(candidates, start=1):
        spec = candidate.spec
        product_facts = facts.get(candidate.tiktok_product_id)
        if product_facts is None:
            continue  # not in the catalogue: approve binds a run to a products row
        subject = _subject(product_facts.product)

        def suppressed(
            reason: str,
            card: ActionCard | None,
            *,
            workflow_key: str = spec.workflow_key,
            subject: CardSubject = subject,
        ) -> None:
            decision = persist.CardEmission(
                workflow_key=workflow_key,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=card,
                revision=None if card is None else card.revision,
                suppressed_reason=reason,
            )
            decisions.append(decision)
            persist._log_suppressed(shop_id, decision)

        current = latest.get((spec.workflow_key, subject.subject_id))
        if not _sellable(product_facts.product):
            suppressed(SUPPRESSED_NOT_SELLABLE, current)
            continue
        if (subject.subject_id, spec.lever_code) in cooldowns:
            suppressed(decision_reasons.SUPPRESSED_REASON_DECISION_COOLDOWN, current)
            continue
        if current is not None and current.status in _IN_FLIGHT:
            approved = _aware(current.approved_at) or _aware(current.updated_at)
            if approved is None or now - approved < timedelta(days=MEASURING_DAYS):
                suppressed(SUPPRESSED_IN_FLIGHT, current)
                continue
        if current is not None and expired_recently(current, now=now):
            suppressed(SUPPRESSED_EXPIRY_COOLDOWN, current)
            continue
        payload = build_payload(
            candidate,
            product_facts,
            priority=priority,
            computed_at=now,
            discount_cap_pct=product_discount_cap(product_facts, caps),
        )
        if current is not None and current.status in (_ACTIVE, _WITHDRAWN):
            # Re-scored daily in place (D24.17); a withdrawn row (never an open
            # offer any more) is revived as a fresh draft.
            if current.status == _WITHDRAWN:
                if created >= WEEKLY_CONTENT_CARDS:
                    suppressed(SUPPRESSED_WEEKLY_CAP, current)
                    continue
                current.status = _ACTIVE
                current.surfaced_at = None
                current.suppressed_reason = None
                created += 1
            _write(current, candidate, payload, priority=priority, computed_at=now)
            await session.flush()
            decisions.append(
                persist.CardEmission(
                    workflow_key=spec.workflow_key,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=current,
                    revision=current.revision,
                    suppressed_reason=None,
                )
            )
            continue
        if created >= WEEKLY_CONTENT_CARDS:
            suppressed(SUPPRESSED_WEEKLY_CAP, current)
            continue
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key=spec.workflow_key,
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
            revision=1 if current is None else current.revision + 1,
            supersedes_card_id=None if current is None else current.id,
            status=_ACTIVE,
        )
        _write(card, candidate, payload, priority=priority, computed_at=now)
        session.add(card)
        await session.flush()
        created += 1
        decisions.append(
            persist.CardEmission(
                workflow_key=spec.workflow_key,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=card,
                revision=card.revision,
                suppressed_reason=None,
                supersedes_card_id=card.supersedes_card_id,
            )
        )
    logger.info(
        "content_cards_emitted",
        extra={
            "shop_id": str(shop_id),
            "candidates": len(candidates),
            "emitted": sum(1 for d in decisions if d.suppressed_reason is None),
            "suppressed": sum(1 for d in decisions if d.suppressed_reason is not None),
            "withdrawn": withdrawn,
        },
    )
    return decisions


async def emit_content_cards_safely(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> list[Any]:
    """The persist hook: a defect here must not stop the shop's other cards.

    A database error is re-raised (the transaction is unusable after it, and
    the caller's failure domain owns that), exactly like the ADR-106 planner.
    """
    try:
        return await emit_content_cards(session, shop_id, now=now)
    except SQLAlchemyError:
        raise
    except Exception:
        logger.exception("content_cards_emit_failed", extra={"shop_id": str(shop_id)})
        return []


def content_kind_of(card: ActionCard) -> ContentKind | None:
    spec = SPEC_BY_WORKFLOW.get(card.workflow_key)
    return spec.kind if spec is not None else None


def is_content_card(card: ActionCard) -> bool:
    return card.workflow_key in CONTENT_WORKFLOW_KEYS


def surfaced_long_enough(card: ActionCard, *, now: datetime) -> bool:
    """Whether a surfaced card has had its minimum ``MIN_SURFACED_DAYS`` on the desk."""
    shown = _aware(card.surfaced_at)
    return shown is None or now - shown >= timedelta(days=MIN_SURFACED_DAYS)


def week_of(now: datetime) -> date:
    return _week_start(now).date()


__all__ = [
    "EXPIRED_AT_KEY",
    "MEASURING_DAYS",
    "SPECS",
    "SUPPRESSED_EXPIRY_COOLDOWN",
    "SUPPRESSED_IN_FLIGHT",
    "SUPPRESSED_NOT_SELLABLE",
    "SUPPRESSED_WEEKLY_CAP",
    "ProductFacts",
    "build_payload",
    "card_expired",
    "content_kind_of",
    "emit_content_cards",
    "emit_content_cards_safely",
    "expired_recently",
    "is_content_card",
    "payload_of",
    "product_discount_cap",
    "surfaced_long_enough",
    "week_of",
]
