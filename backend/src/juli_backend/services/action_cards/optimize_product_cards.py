"""Optimize Product cards from the ADR-106 pipeline, per shop (fast track P7-B, D21).

Until this module, ``optimize_product_2`` produced **one** card per shop: the
rule pipeline's shop-level KPI recommendation, pinned to the top-revenue
product (``subjects._resolve_product_subject``). For a shop with product
analytics, this module replaces that card with the ADR-106 pipeline:

1. read the shop's daily per-product analytics that P1 ingestion stores
   (``analytics_performance_intervals``, grains ``product`` and ``sku``) and
   its ``products`` rows;
2. score the whole catalog and keep the top 10 ranked proposals
   (:func:`~juli_backend.services.optimize_product.decision_cards.plan_shop_cards`);
3. write one subject-scoped card per proposed product, through the same
   revision ladder ``persist.emit_scoring_cards`` applies (ADR-087), carrying
   the diagnosed stage, the lever and the product's funnel evidence;
4. withdraw this workflow's drafts that fell out of the top 10.

Seller reasons (fast track P10-A): a (product, lever) the seller rejected,
declined or reverted is skipped for 7 days (``decision_cooldown``) unless the
weak stage's rate moved > 20 % relative since (``services.decision_reasons``).
Those actions dismiss the card; a dismissed latest revision is then governed by
that cooldown alone, so once it lifts the proposal gets a new revision.

How many surface is the emission budget's decision: ``optimize_product_2``
has its own per-workflow cap (5, ADR-106 decision 6) in
``DecisionEmissionConfig.workflow_max_active``.

A shop with **no** product analytics in the store keeps the rule pipeline's
card exactly as before — the pipeline has nothing to diagnose, and inventing a
product would be worse than the legacy card (``subjects`` module docstring).

Called from ``persist.emit_scoring_cards``, so every scoring path — the P1
bootstrap fast phase and daily analytics pass (D11), the manual refresh, the
continuous compute stage — produces the same cards. No commit here.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.models import ActionCard, AnalyticsPerformanceInterval, Product
from juli_backend.services import decision_reasons
from juli_backend.services.action_cards.basis import (
    BASIS_METADATA_KEY,
    basis_unchanged,
    hash_basis_field,
    product_basis_fields,
    stored_basis,
)
from juli_backend.services.action_cards.subjects import (
    SUBJECT_TYPE_PRODUCT,
    SUBJECT_TYPE_UNSCOPED,
    CardSubject,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import (
    ProductDay,
    funnel_evidence,
    last_window,
    product_funnel,
)
from juli_backend.services.optimize_product.decision_cards import (
    DEFAULT_TOP_K,
    LEVER_CODES,
    CardProposal,
    CatalogProduct,
    ShopCardPlan,
    plan_shop_cards,
)

logger = logging.getLogger(__name__)

OPTIMIZE_PRODUCT_WORKFLOW_KEY = "optimize_product_2"
_WORKFLOW_NAME = "Tối ưu sản phẩm"
_COPY_SOURCE = "adr106_stage_diagnosis"

#: A draft this producer no longer proposes. Never shown to the seller, so
#: nothing is destroyed; a product that re-enters the ranking revives the row.
WITHDRAWN_STATUS = "withdrawn"

#: Days of daily rows read per run: 30 + 30 for the evidence, which also
#: covers the diagnosis's 14 + 28.
_LOOKBACK_DAYS = 60

#: The ``traffic_breakdown`` key under which P1 keeps the A-34 list row's
#: totals (``add_cart_count``, ``clicks``) for single-day windows.
_A34_TOTAL_KEY = "A34_TOTAL"

_ACTIVE = "active"
_SEVERITY = "warning"


@dataclass(frozen=True)
class OptimizeProductPlan:
    """Everything one shop's emission needs, read once per scoring run."""

    as_of: date
    plan: ShopCardPlan
    products: dict[str, Product]
    days: dict[str, list[ProductDay]]


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _optional_dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return _dec(value)
    except (ArithmeticError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _is_daily(row: AnalyticsPerformanceInterval) -> bool:
    start, end = _as_date(row.start_date), _as_date(row.end_date)
    return end is None or (start is not None and (end - start).days == 1)


def _a34_cart(row: AnalyticsPerformanceInterval) -> tuple[Decimal | None, Decimal | None]:
    block = (row.traffic_breakdown or {}).get(_A34_TOTAL_KEY)
    if not isinstance(block, dict):
        return None, None
    add_cart = _optional_dec(block.get("add_cart_count"))
    clicks = _optional_dec(block.get("clicks"))
    if add_cart is None or clicks is None:
        return None, None
    return add_cart, clicks


async def latest_product_analytics_day(
    session: AsyncSession, shop_id: uuid.UUID, *, on_or_before: date
) -> date | None:
    """The newest day with daily product-grain analytics stored for the shop."""
    stmt = select(func.max(AnalyticsPerformanceInterval.start_date)).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == "product",
        AnalyticsPerformanceInterval.hour_index.is_(None),
        AnalyticsPerformanceInterval.tiktok_product_id.isnot(None),
        AnalyticsPerformanceInterval.start_date <= on_or_before,
    )
    return _as_date((await session.execute(stmt)).scalar_one_or_none())


async def load_product_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> dict[str, list[ProductDay]]:
    """Daily rows per TikTok product id over ``[first, last]``.

    SKU orders: the product row's own ``sku_orders`` (the A-34 list value,
    present on single-day windows), else the sum of the product's SKU rows
    for that day (A-31 detail, present on every window), else the A-33
    ``orders`` count.
    """
    stmt = select(AnalyticsPerformanceInterval).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain.in_(("product", "sku")),
        AnalyticsPerformanceInterval.hour_index.is_(None),
        AnalyticsPerformanceInterval.tiktok_product_id.isnot(None),
        AnalyticsPerformanceInterval.start_date >= first,
        AnalyticsPerformanceInterval.start_date <= last,
    )
    rows = (await session.execute(stmt)).scalars().all()
    product_rows: dict[tuple[str, date], AnalyticsPerformanceInterval] = {}
    sku_orders: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    sku_gmv: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    sku_items: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for row in rows:
        if not _is_daily(row):
            continue
        day = _as_date(row.start_date)
        if day is None or row.tiktok_product_id is None:
            continue
        key = (str(row.tiktok_product_id), day)
        if row.grain == "product":
            product_rows[key] = row
        else:
            sku_orders[key] += _dec(row.sku_orders)
            sku_gmv[key] += _dec(row.gmv)
            sku_items[key] += _dec(row.items_sold)

    out: dict[str, list[ProductDay]] = defaultdict(list)
    for key in set(product_rows) | set(sku_orders):
        product_id, day = key
        product_row = product_rows.get(key)
        if product_row is None:
            out[product_id].append(
                ProductDay(
                    day=day,
                    sku_orders=sku_orders[key],
                    items_sold=sku_items[key],
                    gmv=sku_gmv[key],
                )
            )
            continue
        if product_row.sku_orders is not None:
            orders = _dec(product_row.sku_orders)
        elif key in sku_orders:
            orders = sku_orders[key]
        else:
            orders = _dec(product_row.orders_count)
        add_cart, cart_clicks = _a34_cart(product_row)
        out[product_id].append(
            ProductDay(
                day=day,
                impressions=_dec(product_row.impressions),
                clicks=_dec(product_row.clicks),
                sku_orders=orders,
                items_sold=_dec(product_row.items_sold),
                gmv=_dec(product_row.gmv),
                add_to_cart=add_cart,
                cart_clicks=cart_clicks,
            )
        )
    for series in out.values():
        series.sort(key=lambda d: d.day)
    return dict(out)


async def plan_optimize_product_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    config: StageDiagnosisConfig | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> OptimizeProductPlan | None:
    """The ADR-106 plan for one shop, or ``None`` when it has no product analytics.

    ``as_of`` is the newest stored analytics day not after ``now`` — the data's
    own D-1, not the wall clock, so a late analytics pass never reads a window
    of empty days as a fall.
    """
    config = config or StageDiagnosisConfig()
    as_of = await latest_product_analytics_day(session, shop_id, on_or_before=now.date())
    if as_of is None:
        return None
    days = await load_product_days(
        session, shop_id, as_of - timedelta(days=_LOOKBACK_DAYS - 1), as_of
    )
    if not days:
        return None
    products = {
        str(p.tiktok_product_id): p
        for p in (
            await session.execute(select(Product).where(Product.shop_id == shop_id))
        ).scalars()
    }
    catalog: dict[str, CatalogProduct] = {}
    funnels = []
    for product_id, series in sorted(days.items()):
        product = products.get(product_id)
        title = (product.title or product.name) if product else product_id
        # A product the catalog does not hold cannot carry a card (approve
        # binds a run to a ``products`` row); it is excluded, not invented.
        status = product.status if product else "NOT_IN_CATALOG"
        catalog[product_id] = CatalogProduct(product_id, title, status)
        created = product.tiktok_created_at if product else None
        age = (as_of - created.date()).days if created else None
        funnels.append(
            product_funnel(product_id, title, series, as_of=as_of, config=config, age_days=age)
        )
    last30 = {pid: last_window(series, as_of=as_of) for pid, series in days.items()}
    plan = plan_shop_cards(funnels, catalog, config, top_k=top_k, last30=last30)
    logger.info(
        "optimize_product_cards_planned",
        extra={
            "shop_id": str(shop_id),
            "as_of": as_of.isoformat(),
            "products_scored": plan.products_scored,
            "excluded": len(plan.excluded),
            "proposals": len(plan.proposals),
            "overflow": plan.overflow,
        },
    )
    return OptimizeProductPlan(as_of=as_of, plan=plan, products=products, days=days)


def _subject_for(product: Product) -> CardSubject:
    return CardSubject(
        subject_type=SUBJECT_TYPE_PRODUCT,
        subject_id=str(product.id),
        label=product.title or product.name,
    )


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _impact_sentence(proposal: CardProposal) -> str | None:
    value = proposal.recoverable_gmv_per_day
    if value is None:
        return None
    vnd = f"{int(value.quantize(Decimal('1'))):,}".replace(",", ".")
    return f"Có thể lấy lại khoảng {vnd} ₫ GMV mỗi ngày (ước tính theo quy tắc, chưa phải mô hình)"


def build_card_payload(
    proposal: CardProposal,
    op_plan: OptimizeProductPlan,
    subject: CardSubject,
    *,
    computed_at: datetime,
) -> dict:
    """The ``recommendation_payload`` of one ADR-106 card.

    Keeps every key the rule pipeline's payload carries (so the masking and the
    agent run read it unchanged) and adds ``diagnosis`` and ``evidence``.
    """
    as_of = op_plan.as_of.isoformat()
    return {
        "workflow_key": OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        "workflow_name": _WORKFLOW_NAME,
        "priority": proposal.rank,
        "rationale": proposal.reason,
        **(
            {
                "expected_impact": {
                    "metric": "recoverable_gmv_per_day",
                    "value": float(proposal.recoverable_gmv_per_day),
                    "confidence": "rule_based_estimate",
                }
            }
            if proposal.recoverable_gmv_per_day is not None
            else {}
        ),
        "preconditions_met": True,
        "user_action_required": True,
        "source_kpi_ids": [],
        "computed_at": computed_at.isoformat(),
        "subject": {"type": subject.subject_type, "id": subject.subject_id, "label": subject.label},
        "reasoning": {
            "copy_source": _COPY_SOURCE,
            "why": proposal.reason,
            "expected_impact": _impact_sentence(proposal),
            "next_steps": [proposal.lever_detail],
            "source_kpi_ids": [],
        },
        "diagnosis": {
            **proposal.diagnosis_payload(as_of=as_of, medians=op_plan.plan.medians),
            "tiktok_product_id": proposal.product_id,
        },
        "evidence": funnel_evidence(op_plan.days.get(proposal.product_id, []), as_of=op_plan.as_of),
    }


def is_adr106_card(card: ActionCard) -> bool:
    """Whether *card*'s payload came from this producer (it has a ``diagnosis``)."""
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("diagnosis"), dict)


def _basis(proposal: CardProposal) -> dict[str, str]:
    """What makes a new revision: the diagnosis itself, never its daily numbers."""
    return {
        "diagnosis": hash_basis_field(
            "diagnosis",
            {
                "status": proposal.status,
                "label": proposal.label.value,
                "stage": proposal.stage.value,
                "lever": proposal.lever.value,
                "trigger": proposal.trigger.value,
            },
        )
    }


def _write(
    card: ActionCard,
    proposal: CardProposal,
    payload: dict,
    basis: dict[str, str],
    computed_at: datetime,
) -> None:
    card.priority = proposal.rank
    card.severity = _SEVERITY
    card.title = f"{proposal.action} · {_short(proposal.title)}"
    card.description = f"{proposal.reason}. {proposal.lever_detail}"
    card.recommendation_payload = json.dumps(payload, ensure_ascii=False)
    card.metadata_json = json.dumps(
        {"computed_at": computed_at.isoformat(), BASIS_METADATA_KEY: basis}
    )
    card.computed_at = computed_at


async def emit_optimize_product_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    op_plan: OptimizeProductPlan,
    *,
    computed_at: datetime,
    emission_config: DecisionEmissionConfig,
) -> list[Any]:
    """One card per proposal through the ADR-087 ladder, then withdraw stale drafts.

    Ladder per product: no chain → revision 1 (adopting a live unscoped
    pre-#1703 row once); a withdrawn row, an unsurfaced draft, or a live card
    the rule pipeline wrote before this producer existed → rewritten in place
    (none of them is an offer this producer made); basis unchanged →
    ``basis_unchanged``; a card still standing → ``active_card_exists``;
    otherwise a chained successor. Returns ``persist.CardEmission`` values.
    """
    from juli_backend.services.action_cards import persist

    decisions: list[Any] = []
    kept: set[str] = set()
    cooldowns = await decision_reasons.active_cooldowns(session, shop_id, now=computed_at)
    for proposal in op_plan.plan.proposals:
        product = op_plan.products.get(proposal.product_id)
        if product is None:
            continue
        subject = _subject_for(product)
        kept.add(subject.subject_id)
        cooled = _cooled_down(cooldowns, product, proposal)
        if cooled is not None:
            latest = await persist._latest_revision(
                session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY, subject
            )
            decision = persist.CardEmission(
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=latest,
                revision=None if latest is None else latest.revision,
                suppressed_reason=decision_reasons.SUPPRESSED_REASON_DECISION_COOLDOWN,
            )
            decisions.append(decision)
            persist._log_suppressed(shop_id, decision)
            continue
        payload = build_card_payload(proposal, op_plan, subject, computed_at=computed_at)
        basis = {
            **_basis(proposal),
            **await product_basis_fields(
                session, shop_id, workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY, subject=subject
            ),
        }
        latest = await persist._latest_revision(
            session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY, subject
        )
        in_place: ActionCard | None = None
        if latest is None:
            in_place = await persist._adoptable_unscoped_candidate(
                session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY
            )
        elif (
            latest.status == WITHDRAWN_STATUS
            or persist._is_unsurfaced_draft(latest)
            or (latest.status == _ACTIVE and not is_adr106_card(latest))
        ):
            in_place = latest
        elif latest.status != decision_reasons.DISMISSED_CARD_STATUS and (
            basis_unchanged(stored_basis(latest), basis)
            or persist._card_still_stands(
                latest, now=computed_at, cooldown_days=emission_config.cooldown_days
            )
        ):
            # A card the seller rejected, declined or reverted (dismissed) is
            # governed by the per-lever decision cooldown above instead: past
            # its 7 days, or after a clear data change, the proposal gets a new
            # revision even when the diagnosis itself has not moved.
            reason = (
                persist.SUPPRESSED_REASON_BASIS_UNCHANGED
                if basis_unchanged(stored_basis(latest), basis)
                else persist.SUPPRESSED_REASON_ACTIVE_CARD_EXISTS
            )
            decision = persist.CardEmission(
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=latest,
                revision=latest.revision,
                suppressed_reason=reason,
            )
            decisions.append(decision)
            persist._log_suppressed(shop_id, decision)
            continue

        if in_place is not None:
            if in_place.status == WITHDRAWN_STATUS:
                in_place.status = _ACTIVE
                in_place.surfaced_at = None
                in_place.suppressed_reason = None
            in_place.subject_type = subject.subject_type
            in_place.subject_id = subject.subject_id
            _write(in_place, proposal, payload, basis, computed_at)
            await session.flush()
            decisions.append(
                persist.CardEmission(
                    workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=in_place,
                    revision=in_place.revision,
                    suppressed_reason=None,
                )
            )
            continue

        revision = 1 if latest is None else latest.revision + 1
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
            revision=revision,
            supersedes_card_id=None if latest is None else latest.id,
            status=_ACTIVE,
        )
        _write(card, proposal, payload, basis, computed_at)
        session.add(card)
        await session.flush()
        decisions.append(
            persist.CardEmission(
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=card,
                revision=revision,
                suppressed_reason=None,
                supersedes_card_id=card.supersedes_card_id,
            )
        )

    withdrawn = await withdraw_unranked_cards(session, shop_id, keep_subject_ids=kept)
    logger.info(
        "optimize_product_cards_emitted",
        extra={
            "shop_id": str(shop_id),
            "emitted": sum(1 for d in decisions if d.suppressed_reason is None),
            "suppressed": sum(1 for d in decisions if d.suppressed_reason is not None),
            "withdrawn": len(withdrawn),
        },
    )
    return decisions


def _cooled_down(
    cooldowns: dict[tuple[str, str], DecisionReason], product: Product, proposal: CardProposal
) -> DecisionReason | None:
    """The seller reason still cooling this (product, lever) down, if any (P10-A).

    A clear move of the weak stage's rate since the reason lifts it early
    (``decision_reasons.clearly_changed``).
    """
    reason = cooldowns.get((str(product.id), LEVER_CODES[proposal.lever]))
    if reason is None:
        return None
    rates = {name: gap.value for name, gap in proposal.gaps.items()}
    if decision_reasons.clearly_changed(reason, rates):
        return None
    return reason


async def withdraw_unranked_cards(
    session: AsyncSession, shop_id: uuid.UUID, *, keep_subject_ids: set[str]
) -> list[ActionCard]:
    """Withdraw this workflow's live cards that are no longer ranked.

    Withdrawn: an unscoped legacy card, an unsurfaced draft, and a live card
    the rule pipeline wrote for a product this pipeline does not rank. Kept: a
    surfaced ADR-106 card — an offer on the seller's desk stays until they act
    (ADR-106 decision 6: a slot frees when its card is acted on).
    """
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        ActionCard.status == _ACTIVE,
    )
    withdrawn: list[ActionCard] = []
    for card in (await session.execute(stmt)).scalars():
        if card.subject_type == SUBJECT_TYPE_PRODUCT and card.subject_id in keep_subject_ids:
            continue
        legacy = card.subject_type == SUBJECT_TYPE_UNSCOPED or not is_adr106_card(card)
        if card.surfaced_at is not None and not legacy:
            continue
        card.status = WITHDRAWN_STATUS
        card.surfaced_at = None
        card.suppressed_reason = None
        withdrawn.append(card)
    if withdrawn:
        await session.flush()
    return withdrawn


__all__ = [
    "OPTIMIZE_PRODUCT_WORKFLOW_KEY",
    "WITHDRAWN_STATUS",
    "OptimizeProductPlan",
    "build_card_payload",
    "emit_optimize_product_cards",
    "is_adr106_card",
    "latest_product_analytics_day",
    "load_product_days",
    "plan_optimize_product_cards",
    "withdraw_unranked_cards",
]
