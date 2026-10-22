"""Optimize Product cards from the ADR-106 pipeline, per shop (fast track P7-B, D21).

Until this module, ``optimize_product_2`` produced **one** card per shop: the
rule pipeline's shop-level KPI recommendation, pinned to the top-revenue
product (``subjects._resolve_product_subject``). For a shop with product
analytics, this module replaces that card with the ADR-106 pipeline:

1. read the shop's daily per-product analytics that P1 ingestion stores
   (``analytics_performance_intervals``, grains ``product`` and ``sku``) and
   its ``products`` rows;
2. score the whole catalog and keep the top 30 ranked proposals per executor
   type (D24.17; per type since D24.21 (4))
   (:func:`~juli_backend.services.optimize_product.decision_cards.plan_shop_cards`),
   ranked by recoverable GMV × the shop's history for the lever (D24.6:
   calibration coefficient and seller reasons, :func:`lever_history`);
3. write one subject-scoped card per proposed product, through the same
   revision ladder ``persist.emit_scoring_cards`` applies (ADR-087), carrying
   the diagnosed stage, the lever and the product's funnel evidence;
4. withdraw this workflow's drafts that fell out of the top 30, and surfaced
   cards that are no longer valid or have stayed their 3 days unranked
   (:func:`withdraw_unranked_cards`, D24.17).

D24.17: a surfaced card whose diagnosis has not changed is re-scored in place
(numbers, rank, ``computed_at``; ``surfaced_at`` kept). An expired card's
action returns on that product 7 days after it expired.

Seller reasons (fast track P10-A): a (product, lever) the seller rejected,
declined or reverted is skipped for 7 days (``decision_cooldown``) -- strictly,
no early return on a data change (D24.21 (1), ``services.decision_reasons``).
Those actions dismiss the card; a dismissed latest revision is then governed by
that cooldown alone, so once it lifts the proposal gets a new revision.

How many surface is the emission budget's decision (D24.17: 5 new a day,
25 a week, 30 open, every workflow alike).

Quick cards (fast track P17, D26): the quick scan
(``services/onboarding/quick_scan``) writes its 1-3 cards through
:func:`emit_optimize_product_cards` with an ``OptimizeProductPlan`` carrying
``quick_scan`` (payload ``diagnosis.quick_scan``). The next full run upgrades
them: the TikTok codes a quick card carries are fed to the full diagnosis as
evidence (:func:`quick_card_evidence`); a surfaced quick card whose product
gets the **same lever** is re-scored in place (same row, ``surfaced_at``
kept, ``quick_scan`` dropped); one whose product gets another lever is
withdrawn and the new lever is a new revision; one whose product is no longer
proposed is withdrawn at once (``quick_scan_not_confirmed``) -- the 3-day stay
does not protect a reference-only card.

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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.models import (
    ActionCard,
    AnalyticsPerformanceInterval,
    InventoryItem,
    Product,
)
from juli_backend.services import decision_reasons
from juli_backend.services.action_cards.basis import (
    BASIS_METADATA_KEY,
    basis_unchanged,
    hash_basis_field,
    product_basis_fields,
    stored_basis,
)
from juli_backend.services.action_cards.emission_budget import (
    EXPIRED_STATUS,
    expired_card_returns,
)
from juli_backend.services.action_cards.subjects import (
    PRODUCT_SUBJECT_TYPES,
    SUBJECT_TYPE_PRODUCT,
    SUBJECT_TYPE_PRODUCT_LEVER,
    SUBJECT_TYPE_UNSCOPED,
    CardSubject,
    product_lever_subject_id,
    subject_product_ref,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import (
    ChannelTraffic,
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
    LeverHistory,
    ShopCardPlan,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.diagnosis import PageLevers
from juli_backend.services.optimize_product.eligibility import (
    GIFT_PRODUCT,
    stored_product_gift_reason,
)
from juli_backend.services.optimize_product.funnel import ProductFunnel
from juli_backend.services.optimize_product.kpi_channel import CHANNEL_TOTAL, channel_days
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.prediction import CalibrationStats

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
    #: TikTok product id -> its funnel this run (validity checks, D24.17).
    funnels: dict[str, ProductFunnel] = field(default_factory=dict)
    #: P17: set for the quick scan's plan -- the payload's ``diagnosis.quick_scan``.
    quick_scan: dict | None = None


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


def _is_daily(row: Any) -> bool:
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


#: A-33 content types P1 keeps under ``traffic_breakdown`` / ``sales_breakdown`` (D32).
_CONTENT_TYPES: tuple[str, ...] = ("PRODUCT_CARD", "VIDEO", "LIVE")


def _channel_traffic(row: AnalyticsPerformanceInterval) -> dict[str, ChannelTraffic]:
    """D32: the row's per-content-type traffic (A-33 breakdowns); ``{}`` without one.

    Clicks are the mapper's ``round(impressions × ctr)``; a content type with
    impressions but no CTR has no click count and is left out (unknown, not 0).
    """
    traffic = row.traffic_breakdown if isinstance(row.traffic_breakdown, dict) else {}
    sales = row.sales_breakdown if isinstance(row.sales_breakdown, dict) else {}
    out: dict[str, ChannelTraffic] = {}
    for key in _CONTENT_TYPES:
        block = traffic.get(key)
        if not isinstance(block, dict):
            continue
        impressions = _optional_dec(block.get("impressions"))
        clicks = _optional_dec(block.get("clicks"))
        if impressions is None or clicks is None:
            continue
        sale = sales.get(key)
        gmv = _optional_dec(sale.get("gmv")) if isinstance(sale, dict) else None
        out[key] = ChannelTraffic(impressions=impressions, clicks=clicks, gmv=gmv)
    if out:
        # A content type with sales but no traffic block: its GMV, zero traffic.
        for key in _CONTENT_TYPES:
            sale = sales.get(key)
            if key not in out and isinstance(sale, dict) and key not in traffic:
                out[key] = ChannelTraffic(gmv=_optional_dec(sale.get("gmv")))
    return out


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


#: D72.3: the only product-row columns :func:`load_product_days` reads. The window read
#: runs on every scoring pass (60+ days); the rest of the row -- ``snapshot_key``, rates,
#: currency, timestamps -- was egress nobody used.
_PRODUCT_DAY_COLUMNS = (
    AnalyticsPerformanceInterval.grain,
    AnalyticsPerformanceInterval.start_date,
    AnalyticsPerformanceInterval.end_date,
    AnalyticsPerformanceInterval.tiktok_product_id,
    AnalyticsPerformanceInterval.sku_orders,
    AnalyticsPerformanceInterval.gmv,
    AnalyticsPerformanceInterval.items_sold,
    AnalyticsPerformanceInterval.impressions,
    AnalyticsPerformanceInterval.clicks,
    AnalyticsPerformanceInterval.orders_count,
    AnalyticsPerformanceInterval.traffic_breakdown,
    AnalyticsPerformanceInterval.sales_breakdown,
)


async def load_product_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> dict[str, list[ProductDay]]:
    """Daily rows per TikTok product id over ``[first, last]``.

    SKU orders: the product row's own ``sku_orders`` (the A-34 list value,
    present on single-day windows), else the sum of the product's SKU rows
    for that day (A-31 detail, present on every window), else the A-33
    ``orders`` count.
    """
    api = AnalyticsPerformanceInterval
    in_window = (
        api.shop_id == shop_id,
        api.hour_index.is_(None),
        api.tiktok_product_id.isnot(None),
        api.start_date >= first,
        api.start_date <= last,
    )
    product_stmt = (
        select(api)
        .options(load_only(*_PRODUCT_DAY_COLUMNS))
        .where(api.grain == "product", *in_window)
    )
    # D72.3: SKU rows are only ever summed per (product, day), so Postgres sums them:
    # one row per product-day-window instead of one per SKU-day, three numbers wide.
    # Grouped on end_date too, so the daily check below sees the same windows.
    sku_stmt = (
        select(
            api.tiktok_product_id.label("tiktok_product_id"),
            api.start_date.label("start_date"),
            api.end_date.label("end_date"),
            func.sum(api.sku_orders).label("sku_orders"),
            func.sum(api.gmv).label("gmv"),
            func.sum(api.items_sold).label("items_sold"),
        )
        .where(api.grain == "sku", *in_window)
        .group_by(api.tiktok_product_id, api.start_date, api.end_date)
    )
    product_rows: dict[tuple[str, date], AnalyticsPerformanceInterval] = {}
    sku_orders: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    sku_gmv: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    sku_items: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for row in (await session.execute(product_stmt)).scalars().all():
        if not _is_daily(row):
            continue
        day = _as_date(row.start_date)
        if day is None or row.tiktok_product_id is None:
            continue
        product_rows[(str(row.tiktok_product_id), day)] = row
    for sku in (await session.execute(sku_stmt)).all():
        if not _is_daily(sku):
            continue
        day = _as_date(sku.start_date)
        if day is None or sku.tiktok_product_id is None:
            continue
        key = (str(sku.tiktok_product_id), day)
        sku_orders[key] += _dec(sku.sku_orders)
        sku_gmv[key] += _dec(sku.gmv)
        sku_items[key] += _dec(sku.items_sold)

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
                channels=_channel_traffic(product_row),
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
    from juli_backend.services.shop_rules.diag_tunables import diag_tunables

    config = config or StageDiagnosisConfig()
    as_of = await latest_product_analytics_day(session, shop_id, on_or_before=now.date())
    if as_of is None:
        return None
    tunables = await diag_tunables(session, shop_id)
    # D29.1: the longest adaptive window and the same-length earlier level before it.
    lookback = max(_LOOKBACK_DAYS, 2 * max(tunables.windows))
    days = await load_product_days(session, shop_id, as_of - timedelta(days=lookback - 1), as_of)
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
        catalog[product_id] = CatalogProduct(
            product_id,
            title,
            status,
            category=product.category if product else None,
            sku_prices=(product.price,) if product is not None and product.price else (),
        )
        created = product.tiktok_created_at if product else None
        age = (as_of - created.date()).days if created else None
        funnels.append(
            product_funnel(product_id, title, series, as_of=as_of, config=config, age_days=age)
        )
    last30 = {pid: last_window(series, as_of=as_of) for pid, series in days.items()}
    history = await lever_history(session, shop_id, now=now)
    shop_stats, fleet_stats = await calibration_stats(session, shop_id)
    facts = (
        await price_lever_facts(session, shop_id, now=now)
        if tunables.card_quota_mode
        else PriceLeverFacts()
    )
    plan = plan_shop_cards(
        funnels,
        catalog,
        config,
        top_k=top_k,
        last30=last30,
        history=history,
        tiktok_evidence=await quick_card_evidence(session, shop_id),
        daily=days,
        as_of=as_of,
        tunables=tunables,
        calibration=shop_stats,
        fleet_calibration=fleet_stats,
        discount_cap_set=facts.discount_cap_set,
        page_levers=facts.page_levers,
        active_bmsm=facts.active_bmsm,
    )
    # The counts go in the message too: journald keeps the text, not the extras.
    logger.info(
        "optimize_product_cards_planned shop_id=%s as_of=%s products_scored=%d excluded=%d "
        "proposals=%d overflow=%d quota_mode=%s discount_cap_set=%s diag_trigger=%s",
        shop_id,
        as_of.isoformat(),
        plan.products_scored,
        len(plan.excluded),
        len(plan.proposals),
        plan.overflow,
        tunables.card_quota_mode,
        facts.discount_cap_set,
        tunables.diag_trigger,
        extra={
            "shop_id": str(shop_id),
            "as_of": as_of.isoformat(),
            "products_scored": plan.products_scored,
            "excluded": len(plan.excluded),
            "proposals": len(plan.proposals),
            "overflow": plan.overflow,
        },
    )
    return OptimizeProductPlan(
        as_of=as_of,
        plan=plan,
        products=products,
        days=days,
        funnels={f.product_id: f for f in funnels},
    )


@dataclass(frozen=True)
class PriceLeverFacts:
    """D33: what stored data says about the price levers (quota mode only).

    ``discount_cap_set``: the shop has a maximum discount rule
    (``default_max_discount_pct`` or any SKU ``max_discount_pct``).
    ``page_levers``: TikTok product id -> a product discount (Giảm giá / Flash
    sale) already runs on it per ``promotion_activities``. ``active_bmsm``:
    products already in a running Mua nhiều giảm nhiều. Empty = nothing known.
    """

    discount_cap_set: bool = False
    page_levers: dict[str, PageLevers] = field(default_factory=dict)
    active_bmsm: frozenset[str] = frozenset()


#: TikTok activity types that put a product discount on the product.
_DISCOUNT_ACTIVITY_TYPES = frozenset({"FIXED_PRICE", "DIRECT_DISCOUNT", "FLASHSALE"})
_BMSM_ACTIVITY_TYPE = "BUY_MORE_SAVE_MORE"
_ENDED_ACTIVITY_STATUSES = frozenset({"EXPIRED", "DEACTIVATED", "NOT_EFFECTIVE"})


async def price_lever_facts(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> PriceLeverFacts:
    """D33: the discount cap (shop rules) and running promotions (stored activities)."""
    from juli_backend.models.history import PromotionActivity, PromotionActivityProduct
    from juli_backend.services.shop_rules.rules import get_rules

    rules = await get_rules(session, shop_id)
    cap_set = rules.default_max_discount_pct is not None or bool(rules.max_discount_pct)
    moment = _as_aware(now).astimezone(UTC).replace(tzinfo=None)
    rows = await session.execute(
        select(
            PromotionActivity.activity_type,
            PromotionActivity.status,
            PromotionActivityProduct.tiktok_product_id,
        )
        .join(
            PromotionActivityProduct,
            (PromotionActivityProduct.shop_id == PromotionActivity.shop_id)
            & (PromotionActivityProduct.activity_id == PromotionActivity.activity_id),
        )
        .where(
            PromotionActivity.shop_id == shop_id,
            PromotionActivityProduct.removed_at.is_(None),
            PromotionActivity.deactivated_at.is_(None),
            (PromotionActivity.begin_time.is_(None)) | (PromotionActivity.begin_time <= moment),
            (PromotionActivity.end_time.is_(None)) | (PromotionActivity.end_time > moment),
        )
    )
    discounted: set[str] = set()
    bmsm: set[str] = set()
    for activity_type, status, product_id in rows.all():
        if str(status or "").upper() in _ENDED_ACTIVITY_STATUSES:
            continue
        kind = str(activity_type or "").upper()
        if kind in _DISCOUNT_ACTIVITY_TYPES:
            discounted.add(str(product_id))
        elif kind == _BMSM_ACTIVITY_TYPE:
            bmsm.add(str(product_id))
    return PriceLeverFacts(
        discount_cap_set=cap_set,
        page_levers={pid: PageLevers(product_discount_active=True) for pid in sorted(discounted)},
        active_bmsm=frozenset(bmsm),
    )


def is_quick_card(card: ActionCard) -> bool:
    """Whether *card* is a quick-scan card (P17): its diagnosis carries ``quick_scan``."""
    return isinstance(_diagnosis(card).get("quick_scan"), dict)


def _orders_quick_card(card: ActionCard) -> bool:
    """P64 (D73.3): a sandbox quick card chosen from paid orders (``quick_scan.source``)."""
    block = _diagnosis(card).get("quick_scan")
    return isinstance(block, dict) and block.get("source") == "orders"


async def quick_card_evidence(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[str, list[Evidence]]:
    """TikTok product id -> the TikTok codes this shop's open quick cards were built on.

    The full pipeline otherwise only reads the title locally (module
    docstring of ``decision_cards``); feeding TikTok's own codes back keeps a
    confirmed cover-image or description card confirmed when it is upgraded.
    """
    rows = await session.execute(
        select(ActionCard).where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
            ActionCard.status == _ACTIVE,
        )
    )
    out: dict[str, list[Evidence]] = {}
    for card in rows.scalars():
        diagnosis = _diagnosis(card)
        if not isinstance(diagnosis.get("quick_scan"), dict):
            continue
        product_id = diagnosis.get("tiktok_product_id")
        lever = diagnosis.get("lever")
        entries = lever.get("evidence") if isinstance(lever, dict) else None
        if not product_id or not isinstance(entries, list):
            continue
        evidence = [
            Evidence(str(e["code"]), EvidenceSource.TIKTOK, detail=str(e.get("detail") or ""))
            for e in entries
            if isinstance(e, dict) and e.get("code") and e.get("source") == "tiktok"
        ]
        if evidence:
            out[str(product_id)] = evidence
    return out


async def calibration_stats(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[dict[str, CalibrationStats], dict[str, CalibrationStats]]:
    """(shop, fleet) lever -> measured coefficient and result count (D30.3)."""
    from juli_backend.services.lever_flows.measurement import (
        fleet_calibration_stats,
        shop_calibration_stats,
    )

    shop = await shop_calibration_stats(session, shop_id)
    fleet = await fleet_calibration_stats(session)
    return (
        {k: CalibrationStats(float(c), n) for k, (c, n) in shop.items()},
        {k: CalibrationStats(float(c), n) for k, (c, n) in fleet.items()},
    )


async def lever_history(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, LeverHistory]:
    """lever code -> the shop's history for it (D24.6); only levers with any history.

    The calibration coefficient comes from ``lever_calibrations``
    (``lever_flows.measurement.shop_calibrations``), the penalty from the
    seller's reasons of the last 60 days (``decision_reasons.reason_penalties``).
    """
    from juli_backend.services.lever_flows.measurement import shop_calibrations

    calibrations = await shop_calibrations(session, shop_id)
    penalties = await decision_reasons.reason_penalties(session, shop_id, now=now)
    out: dict[str, LeverHistory] = {}
    for lever in set(calibrations) | set(penalties):
        kwargs: dict[str, Decimal] = {}
        if lever in calibrations:
            kwargs["calibration"] = calibrations[lever]
        if lever in penalties:
            kwargs["reason_penalty"] = penalties[lever]
        out[lever] = LeverHistory(**kwargs)
    return out


def _subject_for(product: Product) -> CardSubject:
    return CardSubject(
        subject_type=SUBJECT_TYPE_PRODUCT,
        subject_id=str(product.id),
        label=product.title or product.name,
    )


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _impact_sentence(proposal: CardProposal, *, quick: bool = False) -> str | None:
    value = proposal.recoverable_gmv_per_day
    if value is None:
        return None
    vnd = f"{int(value.quantize(Decimal('1'))):,}".replace(",", ".")
    if quick:
        return (
            f"Có thể lấy lại khoảng {vnd} ₫ GMV mỗi ngày (ước tính trên "
            "14 ngày gần nhất, chỉ để tham khảo)"
        )
    return f"Có thể lấy lại khoảng {vnd} ₫ GMV mỗi ngày (ước tính)"


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
    quick = op_plan.quick_scan is not None
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
                    "confidence": "reference" if quick else "rule_based_estimate",
                }
            }
            if proposal.recoverable_gmv_per_day is not None
            else {}
        ),
        "preconditions_met": True,
        "user_action_required": True,
        "source_kpi_ids": [],
        "computed_at": computed_at.isoformat(),
        "adjusted_by_history": proposal.adjusted_by_history,
        "subject": {"type": subject.subject_type, "id": subject.subject_id, "label": subject.label},
        "reasoning": {
            "copy_source": _COPY_SOURCE,
            "why": proposal.reason,
            "expected_impact": _impact_sentence(proposal, quick=quick),
            "next_steps": [proposal.lever_detail],
            "source_kpi_ids": [],
        },
        "diagnosis": {
            **proposal.diagnosis_payload(as_of=as_of, medians=op_plan.plan.medians),
            "tiktok_product_id": proposal.product_id,
            **({"quick_scan": dict(op_plan.quick_scan)} if op_plan.quick_scan is not None else {}),
        },
        "evidence": funnel_evidence(op_plan.days.get(proposal.product_id, []), as_of=op_plan.as_of),
        **d29_payload(proposal),
    }


def d29_payload(proposal: CardProposal) -> dict[str, Any]:
    """The D29 / D30 card fields (contract P23; the frontend codes against these names).

    ``target_metric``, ``confidence``, ``kpi``, ``gmv_estimate`` and
    ``sibling_cards`` are seller-facing; ``quality`` is internal (D30.5) and is
    not in the seller allowlist. Empty for a proposal built without D29.
    """
    if proposal.kpi is None or proposal.target_metric is None:
        return {}
    kpi = proposal.kpi
    low, high = proposal.gmv_estimate or (0.0, 0.0)
    return {
        "target_metric": proposal.target_metric,
        "confidence": proposal.confidence,
        "kpi": {
            "metric": kpi.metric,
            "current": kpi.current,
            "target": kpi.target,
            "target_min": kpi.target_min,
            "target_max": kpi.target_max,
            "display": kpi.display,
            "band_pct": round(kpi.band_pct, 2),
            "window_days": kpi.window_days,
            "low_data": kpi.low_data,
            "day14_only": kpi.day14_only,
            # D32: the channel the KPI is read and measured on ("total" = all).
            "channel": kpi.channel,
        },
        "gmv_estimate": {"per_month_min": float(round(low)), "per_month_max": float(round(high))},
        "sibling_cards": proposal.sibling_cards,
        **({"quality": proposal.quality.to_json()} if proposal.quality is not None else {}),
        # D33 (S28B): set only on a "below shop level" card (quota mode).
        **({"reason_code": proposal.reason_code} if proposal.reason_code is not None else {}),
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
    live_metrics = await live_metrics_by_product(
        session, shop_id, now=computed_at, full_run=op_plan.quick_scan is None
    )
    for proposal in op_plan.plan.proposals:
        product = op_plan.products.get(proposal.product_id)
        if product is None:
            continue
        subject, latest = await chain_for(session, shop_id, product, LEVER_CODES[proposal.lever])
        kept.add(subject.subject_id)
        cooled = _cooled_down(cooldowns, product, proposal)
        if cooled is not None:
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
        metric = proposal_metric(proposal)
        other = {
            m
            for card_id, m in live_metrics.get(str(product.id), {}).items()
            if latest is None or card_id != latest.id
        }
        if other - {metric}:
            # D29.4: never two target metrics on one product at once.
            decision = persist.CardEmission(
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=latest,
                revision=None if latest is None else latest.revision,
                suppressed_reason=persist.SUPPRESSED_REASON_OTHER_METRIC_ACTIVE,
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
        in_place: ActionCard | None = None
        if latest is None:
            in_place = await persist._adoptable_unscoped_candidate(
                session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY
            )
        elif (
            op_plan.quick_scan is None
            and latest.status == _ACTIVE
            and latest.surfaced_at is not None
            and is_quick_card(latest)
        ):
            # P17: the full diagnosis meets a surfaced quick card on this product.
            if decision_reasons.card_basis(latest).lever_code == LEVER_CODES[proposal.lever]:
                # Same action: the same card, re-scored with the full numbers;
                # its surfacing (3-day stay, 7-day validity) is kept.
                _write(latest, proposal, payload, basis, computed_at)
                await session.flush()
                decision = persist.CardEmission(
                    workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=latest,
                    revision=latest.revision,
                    suppressed_reason=persist.SUPPRESSED_REASON_BASIS_UNCHANGED,
                )
                decisions.append(decision)
                logger.info(
                    "optimize_product_quick_card_upgraded",
                    extra={"shop_id": str(shop_id), "card_id": str(latest.id)},
                )
                continue
            # Another action: the quick card is withdrawn; the new action
            # is a new revision for the budget to place.
            _withdraw(latest, shop_id, why=WITHDRAW_QUICK_SUPERSEDED)
            await session.flush()
        elif (
            latest.status == WITHDRAWN_STATUS
            or persist._is_unsurfaced_draft(latest)
            or (latest.status == _ACTIVE and not is_adr106_card(latest))
        ):
            in_place = latest
        elif latest.status == EXPIRED_STATUS:
            # D24.17: the same action on this product returns 7 days after its
            # card expired; another action may come at once. Either way as a
            # new revision -- the expired card was an offer, it is history.
            same_action = (
                decision_reasons.card_basis(latest).lever_code == LEVER_CODES[proposal.lever]
            )
            if same_action and not expired_card_returns(
                latest,
                now=computed_at,
                cooldown_days=emission_config.cooldown_days,
                validity_days=emission_config.validity_days,
            ):
                decision = persist.CardEmission(
                    workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    card=latest,
                    revision=latest.revision,
                    suppressed_reason=persist.SUPPRESSED_REASON_EXPIRED_COOLDOWN,
                )
                decisions.append(decision)
                persist._log_suppressed(shop_id, decision)
                continue
        elif (
            latest.status == _ACTIVE
            and latest.surfaced_at is not None
            and basis_unchanged(stored_basis(latest), basis)
        ):
            # D24.17: an open card is re-scored daily in place -- its numbers
            # and rank follow the data, ``surfaced_at`` (its 3-day stay and
            # 7-day validity) does not move. Same diagnosis, so no revision.
            _write(latest, proposal, payload, basis, computed_at)
            await session.flush()
            decision = persist.CardEmission(
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                card=latest,
                revision=latest.revision,
                suppressed_reason=persist.SUPPRESSED_REASON_BASIS_UNCHANGED,
            )
            decisions.append(decision)
            continue
        elif latest.status != decision_reasons.DISMISSED_CARD_STATUS and (
            basis_unchanged(stored_basis(latest), basis)
            or persist._card_still_stands(
                latest, now=computed_at, cooldown_days=emission_config.cooldown_days
            )
        ):
            # A card the seller rejected, declined or reverted (dismissed) is
            # governed by the per-lever decision cooldown above instead: past
            # its 7 days the proposal gets a new revision even when the
            # diagnosis itself has not moved (D24.21: strictly 7 days).
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

    withdrawn = await withdraw_unranked_cards(
        session,
        shop_id,
        keep_subject_ids=kept,
        now=computed_at,
        op_plan=op_plan,
        min_stay_days=emission_config.min_stay_days,
    )
    if op_plan.quick_scan is None:
        # P23 follow-up: a pending card written before D29 that this run did not
        # rewrite (its diagnosis moved, or it is no longer ranked but still within
        # its stay) gets the D29 KPI / confidence / GMV range in place.
        await rescore_pending_cards(session, shop_id, op_plan, now=computed_at)
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


async def rescore_pending_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    op_plan: OptimizeProductPlan,
    *,
    now: datetime,
) -> list[ActionCard]:
    """Re-score every pending pre-D29 card of the shop in place (no new revision).

    Pending: ``active`` (surfaced or a draft) with an ADR-106 ``diagnosis`` and
    no D29 ``kpi``. The card keeps its row, revision, lever and ``surfaced_at``;
    its numbers become D29's (:func:`rescore.rescore_legacy_payload`). A card
    whose KPI cannot be recomputed (no daily rows for its product) is left as it
    is -- the read model caps its target. Quick-scan cards are left to the full
    run's own upgrade. No commit here.
    """
    from juli_backend.services.optimize_product.rescore import rescore_legacy_payload
    from juli_backend.services.shop_rules.diag_tunables import diag_tunables

    rows = await session.execute(
        select(ActionCard).where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
            ActionCard.status == _ACTIVE,
        )
    )
    cards = [c for c in rows.scalars() if is_adr106_card(c) and not is_quick_card(c)]
    if not cards:
        return []
    tunables = await diag_tunables(session, shop_id)
    by_uuid = {str(p.id): p for p in op_plan.products.values()}
    rescored: list[ActionCard] = []
    for card in cards:
        try:
            payload = json.loads(card.recommendation_payload or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        tiktok_id = _diagnosis(card).get("tiktok_product_id")
        if not tiktok_id:
            ref = subject_product_ref(card.subject_type, card.subject_id)
            product = by_uuid.get(ref) if ref is not None else None
            tiktok_id = product.tiktok_product_id if product is not None else None
        days = op_plan.days.get(str(tiktok_id)) if tiktok_id else None
        updated = rescore_legacy_payload(
            payload, days or [], as_of=op_plan.as_of, tunables=tunables
        )
        if updated is None:
            continue
        card.recommendation_payload = json.dumps(updated, ensure_ascii=False)
        card.computed_at = now
        rescored.append(card)
    if rescored:
        await session.flush()
        logger.info(
            "optimize_product_cards_rescored_d29 shop_id=%s rescored=%d",
            shop_id,
            len(rescored),
            extra={"shop_id": str(shop_id), "rescored": len(rescored)},
        )
    return rescored


async def rescore_shop_cards(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    """Ops: re-score one shop's pending cards from stored data only (no TikTok call).

    Plans from the stored daily analytics, then (a) retires gift-product cards
    and (b) re-scores pending pre-D29 cards in place. Emits no new card and
    touches no surfacing (the daily diagnosis build does that). No commit here.
    """
    op_plan = await plan_optimize_product_cards(session, shop_id, now=now)
    if op_plan is None:
        return {"shop_id": str(shop_id), "status": "no_product_analytics"}
    gifts = await retire_gift_cards(session, shop_id)
    rescored = await rescore_pending_cards(session, shop_id, op_plan, now=now)
    return {
        "shop_id": str(shop_id),
        "status": "ok",
        "as_of": op_plan.as_of.isoformat(),
        "gift_cards_retired": len(gifts),
        "cards_rescored": len(rescored),
    }


#: D29: the funnel stage of a pre-D29 card -> the metric it targeted.
_STAGE_METRIC: dict[str, str] = {"card": "ctr", "page": "ctor", "basket": "aov"}
_ORDERS_CARD_METRIC = "aov"
#: An approved / executed card holds its product's metric through its
#: measurement (approve → write → day 14), bounded so a stuck run never blocks forever.
_IN_FLIGHT_DAYS = 21


def proposal_metric(proposal: CardProposal) -> str:
    if proposal.listing_proposal is not None:
        # P64 (D73.3): an orders-based sandbox card claims only its real AOV, whatever
        # listing lever it carries -- so its title and description cards share a metric.
        return _ORDERS_CARD_METRIC
    return proposal.target_metric or _STAGE_METRIC.get(proposal.stage.value, "ctor")


def card_metric(card: ActionCard) -> str | None:
    """The target metric a stored card is about (D29 ``target_metric``, else its stage)."""
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    metric = payload.get("target_metric")
    if isinstance(metric, str) and metric:
        return metric
    if _orders_quick_card(card):
        return _ORDERS_CARD_METRIC
    diagnosis = payload.get("diagnosis")
    stage = diagnosis.get("stage") if isinstance(diagnosis, dict) else None
    code = stage.get("code") if isinstance(stage, dict) else None
    return _STAGE_METRIC.get(str(code)) if code else None


async def chain_for(
    session: AsyncSession, shop_id: uuid.UUID, product: Product, lever_code: str
) -> tuple[CardSubject, ActionCard | None]:
    """The (product, lever) chain's subject and newest row (D29.4).

    A chain written before P23 is keyed on the product alone; it stays the
    lever's chain while its newest row carries that lever, so existing rows keep
    their revision ladder (re-score in place, 7-day return, cooldowns). Every
    other (product, lever) gets its own ``product_lever`` chain.
    """
    from juli_backend.services.action_cards import persist

    lever_subject = CardSubject(
        subject_type=SUBJECT_TYPE_PRODUCT_LEVER,
        subject_id=product_lever_subject_id(str(product.id), lever_code),
        label=product.title or product.name,
    )
    latest = await persist._latest_revision(
        session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY, lever_subject
    )
    if latest is not None:
        return lever_subject, latest
    legacy_subject = _subject_for(product)
    legacy = await persist._latest_revision(
        session, shop_id, OPTIMIZE_PRODUCT_WORKFLOW_KEY, legacy_subject
    )
    if legacy is not None and decision_reasons.card_basis(legacy).lever_code == lever_code:
        return legacy_subject, legacy
    return lever_subject, None


async def live_metrics_by_product(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, full_run: bool = True
) -> dict[str, dict[uuid.UUID, str]]:
    """products.id -> {card id: target metric} of the cards that hold a metric (D29.4).

    Holding: a surfaced live card (a quick card does not, in a full run -- the
    full diagnosis replaces it), and an approved / executed card within
    :data:`_IN_FLIGHT_DAYS`. Drafts, withdrawn, expired and dismissed rows do not.
    """
    rows = await session.execute(
        select(ActionCard).where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
            ActionCard.subject_type.in_(PRODUCT_SUBJECT_TYPES),
            ActionCard.status.notin_(
                (WITHDRAWN_STATUS, EXPIRED_STATUS, decision_reasons.DISMISSED_CARD_STATUS)
            ),
        )
    )
    horizon = _as_aware(now) - timedelta(days=_IN_FLIGHT_DAYS)
    out: dict[str, dict[uuid.UUID, str]] = defaultdict(dict)
    for card in rows.scalars():
        if card.status == _ACTIVE:
            if card.surfaced_at is None or (full_run and is_quick_card(card)):
                continue
        else:
            marker = card.executed_at or card.approved_at
            if marker is None or _as_aware(marker) < horizon:
                continue
        ref = subject_product_ref(card.subject_type, card.subject_id)
        metric = card_metric(card)
        if ref is not None and metric is not None:
            out[ref][card.id] = metric
    return dict(out)


def _cooled_down(
    cooldowns: dict[tuple[str, str], DecisionReason], product: Product, proposal: CardProposal
) -> DecisionReason | None:
    """The seller reason still cooling this (product, lever) down, if any (P10-A).

    Strictly 7 days (D24.21 (1)): no data change lifts it early.
    """
    return cooldowns.get((str(product.id), LEVER_CODES[proposal.lever]))


#: Why a surfaced card left before its 7 days (D24.17), for the log.
WITHDRAW_QUICK_NOT_CONFIRMED = "quick_scan_not_confirmed"
WITHDRAW_QUICK_SUPERSEDED = "quick_scan_superseded"
WITHDRAW_EDITED_OUTSIDE_JULI = "edited_outside_juli"
WITHDRAW_OUT_OF_STOCK = "out_of_stock"
WITHDRAW_NOT_ON_SALE = "not_on_sale"
WITHDRAW_AT_TARGET = "metric_at_target"
WITHDRAW_UNRANKED = "unranked_after_min_stay"
#: A gift item (``optimize_product.eligibility``) is never an optimize
#: candidate: its live cards -- surfaced or not, ADR-106 or legacy -- are
#: retired on the next run with this reason and never executed.
WITHDRAW_GIFT_PRODUCT = GIFT_PRODUCT


def _withdraw(card: ActionCard, shop_id: uuid.UUID, *, why: str) -> None:
    card.status = WITHDRAWN_STATUS
    card.surfaced_at = None
    # A gift card keeps its reason on the row (the revision vocabulary's
    # ``gift_product``), so Ops can see why it left; other withdrawals clear it.
    card.suppressed_reason = WITHDRAW_GIFT_PRODUCT if why == WITHDRAW_GIFT_PRODUCT else None
    logger.info(
        "optimize_product_card_withdrawn shop_id=%s card_id=%s why=%s",
        shop_id,
        card.id,
        why,
        extra={"shop_id": str(shop_id), "card_id": str(card.id), "why": why},
    )


async def retire_gift_cards(session: AsyncSession, shop_id: uuid.UUID) -> list[ActionCard]:
    """Withdraw every live card (any status ``active``) whose product is a gift item."""
    gift_ids = await gift_product_ids(session, shop_id)
    if not gift_ids:
        return []
    rows = await session.execute(
        select(ActionCard).where(
            ActionCard.shop_id == shop_id,
            ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
            ActionCard.status == _ACTIVE,
        )
    )
    retired: list[ActionCard] = []
    for card in rows.scalars():
        if subject_product_ref(card.subject_type, card.subject_id) in gift_ids:
            _withdraw(card, shop_id, why=WITHDRAW_GIFT_PRODUCT)
            retired.append(card)
    if retired:
        await session.flush()
    return retired


async def gift_product_ids(session: AsyncSession, shop_id: uuid.UUID) -> set[str]:
    """``products.id`` (as str) of the shop's gift items (``eligibility``)."""
    rows = await session.execute(select(Product).where(Product.shop_id == shop_id))
    return {str(p.id) for p in rows.scalars() if stored_product_gift_reason(p) is not None}


def _diagnosis(card: ActionCard) -> dict:
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    diagnosis = payload.get("diagnosis") if isinstance(payload, dict) else None
    return diagnosis if isinstance(diagnosis, dict) else {}


def _kpi_channel(card: ActionCard) -> str:
    """D32: the channel a stored card's KPI is read on; ``total`` when it has none."""
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return CHANNEL_TOTAL
    kpi = payload.get("kpi") if isinstance(payload, dict) else None
    channel = kpi.get("channel") if isinstance(kpi, dict) else None
    return str(channel) if isinstance(channel, str) and channel else CHANNEL_TOTAL


def _rate(funnel: ProductFunnel, key: str) -> Decimal | None:
    window = funnel.current
    return {"ctr": window.ctr, "ctor": window.ctor, "aov": window.aov}.get(key)


def invalid_reason(
    card: ActionCard,
    *,
    product: Product | None,
    stock: Decimal | None,
    funnel: ProductFunnel | None,
) -> str | None:
    """Why a surfaced card is no longer valid (D24.17), else ``None``.

    - the product was edited outside Juli: its title differs from the one the
      card was proposed on (an approved card is no longer ``active``, so Juli's
      own edits never reach here);
    - it is not on sale, or out of stock (every SKU's quantity is 0; no stock
      rows means unknown, which never withdraws);
    - the weak stage's rate is already at or above the card's target
      (``recoverable_gmv_basis.reference_rate``) over the current window.
    """
    diagnosis = _diagnosis(card)
    proposed_title = diagnosis.get("product_title")
    if product is not None and isinstance(proposed_title, str) and proposed_title:
        if (product.title or product.name) != proposed_title:
            return WITHDRAW_EDITED_OUTSIDE_JULI
    if product is not None and product.status:
        from juli_backend.services.optimize_product.decision_cards import LIVE_STATUSES

        if product.status.strip().lower() not in LIVE_STATUSES:
            return WITHDRAW_NOT_ON_SALE
    if stock is not None and stock <= 0:
        return WITHDRAW_OUT_OF_STOCK
    basis = diagnosis.get("recoverable_gmv_basis")
    if funnel is not None and isinstance(basis, dict):
        target = basis.get("reference_rate")
        key = basis.get("stage_rate")
        current = _rate(funnel, str(key)) if key else None
        if isinstance(target, int | float) and current is not None:
            if current >= Decimal(str(target)):
                return WITHDRAW_AT_TARGET
    return None


async def _stock_by_tiktok_id(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Decimal]:
    rows = await session.execute(
        select(InventoryItem.tiktok_product_id, func.sum(InventoryItem.quantity))
        .where(InventoryItem.shop_id == shop_id)
        .group_by(InventoryItem.tiktok_product_id)
    )
    return {str(pid): _dec(total) for pid, total in rows.all()}


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def withdraw_unranked_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    keep_subject_ids: set[str],
    now: datetime | None = None,
    op_plan: OptimizeProductPlan | None = None,
    min_stay_days: int = 3,
) -> list[ActionCard]:
    """Withdraw this workflow's live cards that are no longer ranked or no longer valid.

    Withdrawn at once: an unscoped legacy card and a live card the rule
    pipeline wrote, unless ranked; an unsurfaced draft that is not ranked.

    A surfaced ADR-106 card (D24.17) stays at least ``min_stay_days`` (3): it
    is withdrawn earlier only when :func:`invalid_reason` says it is no longer
    valid -- never for dropping out of the ranking. After its 3 days, a card
    that is no longer ranked is withdrawn too. (A valid ranked card stays until
    the seller acts or it expires at 7 days, ``emission_budget``.)
    """
    now = _as_aware(now) if now is not None else datetime.now(UTC)
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        ActionCard.status == _ACTIVE,
    )
    withdrawn = await retire_gift_cards(session, shop_id)
    retired = {c.id for c in withdrawn}
    cards = [c for c in (await session.execute(stmt)).scalars() if c.id not in retired]
    surfaced = [c for c in cards if c.surfaced_at is not None and is_adr106_card(c)]
    products_by_id: dict[str, Product] = {}
    stock: dict[str, Decimal] = {}
    if surfaced:
        product_ids = {
            ref
            for c in surfaced
            if (ref := subject_product_ref(c.subject_type, c.subject_id)) is not None
        }
        if op_plan is not None:
            products_by_id = {
                str(p.id): p for p in op_plan.products.values() if str(p.id) in product_ids
            }
        else:
            rows = await session.execute(select(Product).where(Product.shop_id == shop_id))
            products_by_id = {str(p.id): p for p in rows.scalars() if str(p.id) in product_ids}
        stock = await _stock_by_tiktok_id(session, shop_id)

    for card in cards:
        ranked = card.subject_type in PRODUCT_SUBJECT_TYPES and card.subject_id in keep_subject_ids
        legacy = card.subject_type == SUBJECT_TYPE_UNSCOPED or not is_adr106_card(card)
        why: str | None = None
        if card.surfaced_at is None or legacy:
            if ranked:
                continue
            why = "unranked"
        else:
            product_ref = subject_product_ref(card.subject_type, card.subject_id)
            product = products_by_id.get(product_ref) if product_ref is not None else None
            tiktok_id = product.tiktok_product_id if product is not None else None
            funnel = (
                op_plan.funnels.get(str(tiktok_id))
                if op_plan is not None and tiktok_id is not None
                else None
            )
            channel = _kpi_channel(card)
            if channel != CHANNEL_TOTAL and op_plan is not None and tiktok_id is not None:
                # D32: "already at target" compares the KPI's own channel.
                funnel = product_funnel(
                    str(tiktok_id),
                    "",
                    channel_days(op_plan.days.get(str(tiktok_id), []), channel),
                    as_of=op_plan.as_of,
                    config=StageDiagnosisConfig(),
                )
            why = invalid_reason(
                card,
                product=product,
                stock=stock.get(str(tiktok_id)) if tiktok_id is not None else None,
                funnel=funnel,
            )
            full_run = op_plan is not None and op_plan.quick_scan is None
            if (
                why is None
                and not ranked
                and full_run
                and is_quick_card(card)
                and not _orders_quick_card(card)
            ):
                # P17: the full diagnosis did not confirm this quick card. P64
                # (D73.3): a sandbox card chosen from paid orders was never built on
                # analytics, so an analytics run cannot unconfirm it (its 3-day stay holds).
                why = WITHDRAW_QUICK_NOT_CONFIRMED
            if why is None and not ranked:
                stayed = now - _as_aware(card.surfaced_at)
                if stayed >= timedelta(days=min_stay_days):
                    why = WITHDRAW_UNRANKED
            if why is None:
                continue
        _withdraw(card, shop_id, why=why)
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
    "gift_product_ids",
    "rescore_pending_cards",
    "rescore_shop_cards",
    "retire_gift_cards",
    "invalid_reason",
    "is_adr106_card",
    "is_quick_card",
    "quick_card_evidence",
    "latest_product_analytics_day",
    "lever_history",
    "load_product_days",
    "plan_optimize_product_cards",
    "withdraw_unranked_cards",
]
