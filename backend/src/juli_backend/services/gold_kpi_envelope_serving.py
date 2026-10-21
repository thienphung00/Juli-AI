"""Gold KPI envelope serving helpers — contract + persistence orchestration (#606)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    GoldKpiEnvelope,
    Order,
    Shop,
)
from juli_backend.repositories.repos import GoldKpiEnvelopesRepo
from juli_backend.services.gold_kpi_envelope_contract import (
    ENVELOPE_VERSION,
    KPI_SOURCE,
    build_honest_unavailable_shell_payload,
    build_source_freshness,
)


async def seed_unavailable_shell(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> GoldKpiEnvelope:
    """Seed honest-unavailable ADR-044 shell when no gold row exists."""
    repo = GoldKpiEnvelopesRepo(session)
    existing = await repo.get(shop_id)
    if existing is not None:
        return existing

    when = datetime.now(tz=UTC)
    payload = build_honest_unavailable_shell_payload(shop_id=shop_id, computed_at=when)
    return await repo.upsert(
        shop_id=shop_id,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=when,
    )


#: Statuses that count as a cancelled order for the five Demo Main KPIs.
CANCELLED_ORDER_STATUSES: tuple[str, ...] = ("CANCELLED", "CANCELED")

#: D72.3 (P62-B): the five KPIs are all-time aggregates by contract (ADR-049), so the
#: reads are not windowed -- they are AGGREGATED in Postgres instead. Before, every gold
#: recompute (each material webhook + the hourly reconcile) pulled every ``silver.orders``
#: row and every product- and shop-grain ``analytics_performance_intervals`` row of the
#: shop (~3,700 + 2 x ~2,400 full ORM rows per call, D72 evidence); now it reads one row
#: per order day plus two single-row aggregates.


def _as_day(value: Any) -> date | None:
    """``date(...)`` comes back as a ``date`` on Postgres and as ISO text on SQLite."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _day_start_utc(day: Any) -> datetime | None:
    """A ``start_date`` (the day measured) as midnight UTC, to compare with order times."""
    as_date = _as_day(day)
    return None if as_date is None else datetime.combine(as_date, time.min, tzinfo=UTC)


def _dec(value: Any) -> Decimal:
    return Decimal(0) if value is None else Decimal(str(value))


def _later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    return candidate if current is None else max(current, candidate)


async def _order_day_aggregates(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[int, int, datetime | None, Decimal, list[tuple[date, Decimal]]]:
    """(orders, cancelled, newest update_time, GMV, [(day, GMV)] for days with a sale).

    One row per order day, bucketed on ``tiktok_created_at`` else ``update_time`` --
    the same bucket the Python loop used. GMV and the non-cancelled count exclude
    cancelled orders; only non-zero amounts are summed (as before).
    """
    cancelled = func.upper(Order.status).in_(CANCELLED_ORDER_STATUSES)
    day = func.date(func.coalesce(Order.tiktok_created_at, Order.update_time))
    stmt = (
        select(
            day.label("day"),
            func.count().label("orders"),
            func.count().filter(cancelled).label("cancelled"),
            func.max(Order.update_time).label("newest"),
            func.sum(Order.total_amount).filter(~cancelled).label("gmv"),
            func.count(Order.total_amount).filter(~cancelled & (Order.total_amount != 0)),
        )
        .where(Order.shop_id == shop_id)
        .group_by(day)
    )
    total = cancelled_total = 0
    newest: datetime | None = None
    gmv_total = Decimal(0)
    days: list[tuple[date, Decimal]] = []
    for row in (await session.execute(stmt)).all():
        total += int(row[1])
        cancelled_total += int(row[2])
        newest = _later(newest, row[3])
        day_gmv = Decimal(str(row[4])) if row[4] is not None else Decimal(0)
        gmv_total += day_gmv
        bucket = _as_day(row[0])
        if bucket is not None and int(row[5]) > 0:
            days.append((bucket, day_gmv))
    return total, cancelled_total, newest, gmv_total, sorted(days)


async def _product_ctor_aggregate(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[int, date | None, Decimal, Decimal]:
    """(rows, newest start_date, sum gmv, sum gmv x click_order_rate) of product grain."""
    both = AnalyticsPerformanceInterval.gmv.is_not(None) & (
        AnalyticsPerformanceInterval.click_order_rate.is_not(None)
    )
    stmt = select(
        func.count(),
        func.max(AnalyticsPerformanceInterval.start_date),
        func.sum(AnalyticsPerformanceInterval.gmv).filter(both),
        func.sum(
            AnalyticsPerformanceInterval.gmv * AnalyticsPerformanceInterval.click_order_rate
        ).filter(both),
    ).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == "product",
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), _as_day(row[1]), _dec(row[2]), _dec(row[3])


async def _shop_live_hours_aggregate(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[int, date | None, Decimal]:
    """(rows, newest start_date, sum live_hours) of shop grain."""
    stmt = select(
        func.count(),
        func.max(AnalyticsPerformanceInterval.start_date),
        func.sum(AnalyticsPerformanceInterval.live_hours),
    ).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == "shop",
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), _as_day(row[1]), _dec(row[2])


async def compute_demo_main_kpis_payload(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    computed_at: datetime | None = None,
    currency: str = "VND",
) -> dict[str, Any]:
    """Build gold envelope payload with computed five Demo Main KPIs (#630, ADR-049).

    Computes gmv_tiktok, aov, cancellation_rate from silver orders.
    Computes ctor as GMV-weighted click_order_rate from product-grain analytics.
    Computes live_hours from shop-grain analytics.
    Emits a date-bucketed series for gmv_tiktok (#633).
    """
    computed_at = computed_at or datetime.now(tz=UTC)

    # Fetch shop for identity information
    shop_stmt = select(Shop).where(Shop.id == shop_id)
    shop_result = await session.execute(shop_stmt)
    shop = shop_result.scalars().first()

    # D72.3: one aggregate row per order day, not every order row.
    order_count, cancelled_count, orders_as_of, total_gmv, gmv_days = await _order_day_aggregates(
        session, shop_id
    )

    gmv_value: float | None = None
    aov_value: float | None = None
    cancellation_value: float | None = None
    # Newest source record behind the orders-derived KPIs. Distinct from computed_at:
    # gold keeps recomputing on schedule even when the Partner fetch has been failing,
    # so without this the envelope reports fresh numbers built on frozen data.
    intervals_as_of: datetime | None = None

    if order_count:
        non_cancelled = order_count - cancelled_count
        # GMV: sum of non-cancelled orders
        if non_cancelled and total_gmv:
            gmv_value = float(total_gmv)
        # Cancellation rate: cancelled / total
        cancellation_value = cancelled_count / order_count
        # AOV: GMV / number of non-cancelled orders
        if non_cancelled and gmv_value:
            aov_value = gmv_value / non_cancelled
    # Date-bucketed series for gmv_tiktok (#633): tiktok_created_at else update_time.
    gmv_series: list[dict[str, Any]] = [{"t": d.isoformat(), "v": float(v)} for d, v in gmv_days]

    # Build the kpis map with proper typing
    kpis: dict[str, dict[str, Any]] = {}

    # GMV: Gross Merchandise Value
    gmv_kpi: dict[str, Any] = {
        "availability": "available" if gmv_value is not None else "unavailable",
        "label": "GMV (TikTok)",
    }
    if gmv_value is not None:
        gmv_kpi["value"] = gmv_value
    # Always emit series, even if empty (for consistency with legacy contract)
    gmv_kpi["series"] = gmv_series
    kpis["gmv_tiktok"] = gmv_kpi

    # AOV: Average Order Value
    aov_kpi: dict[str, Any] = {
        "availability": "available" if aov_value is not None else "unavailable",
        "label": "AOV",
    }
    if aov_value is not None:
        aov_kpi["value"] = aov_value
    kpis["aov"] = aov_kpi

    # CTOR: Click-to-Order Rate (GMV-weighted from product-grain analytics)
    ctor_value: float | None = None
    product_rows, product_newest, product_gmv, product_weighted = await _product_ctor_aggregate(
        session, shop_id
    )
    if product_rows:
        intervals_as_of = _later(intervals_as_of, _day_start_utc(product_newest))
        if product_gmv > 0:
            ctor_value = float(product_weighted / product_gmv)

    ctor_kpi: dict[str, Any] = {
        "availability": "available" if ctor_value is not None else "unavailable",
        "label": "CTOR (lượt nhấp → đơn)",
    }
    if ctor_value is not None:
        ctor_kpi["value"] = ctor_value
    kpis["ctor"] = ctor_kpi

    # Live Hours (from shop-grain analytics)
    # Note: live_hours is unbounded across all history; gmv_tiktok is bounded by
    # the #744 page cap on silver orders. This difference is accepted per review.
    live_hours_value: float | None = None
    shop_rows, shop_newest, total_live_hours = await _shop_live_hours_aggregate(session, shop_id)
    if shop_rows:
        intervals_as_of = _later(intervals_as_of, _day_start_utc(shop_newest))
        # Report sum as-is, even if zero (legitimate measurement when rows exist).
        # Only unavailable when no rows exist (missing data, per ADR-044).
        live_hours_value = float(total_live_hours)

    live_hours_kpi: dict[str, Any] = {
        "availability": "available" if live_hours_value is not None else "unavailable",
        "label": "LIVE hours",
    }
    if live_hours_value is not None:
        live_hours_kpi["value"] = live_hours_value
    kpis["live_hours"] = live_hours_kpi

    # Cancellation Rate
    cancellation_kpi: dict[str, Any] = {
        "availability": "available" if cancellation_value is not None else "unavailable",
        "label": "Cancellation rate",
    }
    if cancellation_value is not None:
        cancellation_kpi["value"] = cancellation_value
    kpis["cancellation_rate"] = cancellation_kpi

    # Freshness is per-source, then stamped onto each KPI, so a consumer can tell
    # which specific numbers a stalled upstream affects rather than having to know
    # the derivation. A KPI reading "available" with stale=True is the exact state a
    # failing Partner fetch produces once the fetch stopped aborting the whole job.
    source_freshness = {
        "silver.orders": build_source_freshness(
            source="silver.orders",
            as_of=orders_as_of,
            computed_at=computed_at,
            row_count=order_count,
        ),
        "analytics_performance_intervals": build_source_freshness(
            source="analytics_performance_intervals",
            as_of=intervals_as_of,
            computed_at=computed_at,
            row_count=product_rows + shop_rows,
        ),
    }
    for metric_id, kpi in kpis.items():
        entry = source_freshness[KPI_SOURCE[metric_id]]
        kpi["source"] = KPI_SOURCE[metric_id]
        kpi["as_of"] = entry["as_of"]
        kpi["stale"] = entry["stale"]

    # Build identity block for masking (preserves PII for local processing,
    # masked before public response via mask_public_analytics_envelope)
    identity: dict[str, Any] = {}
    if shop:
        identity["shop_display_name"] = shop.shop_name or f"Shop {shop.id}"

    return {
        "envelope_version": ENVELOPE_VERSION,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": currency,
        "identity": identity,
        "kpis": kpis,
        # Top level, not meta: mask_public_analytics_envelope pops meta wholesale, and
        # a freshness signal nobody can read defeats the point of emitting it.
        "source_freshness": source_freshness,
        "meta": {
            "source_partitions": ["silver.orders", "analytics_performance_intervals"],
            "notes": ["A1 five-KPI precompute (#630)"],
        },
    }


async def write_demo_main_kpis_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> GoldKpiEnvelope:
    """Compute and persist the five Demo Main KPIs gold envelope (#630).

    Sole gold.kpi_envelopes writer entrypoint for this payload — keeps the
    upsert inside this module per the medallion one-writer ownership gate
    (agent-runtime/scripts/ci/medallion_one_writer.py).

    On successful upsert, refreshes the Redis cache (#631) to keep Demo reads fast.
    Cache refresh fails gracefully (logged) and does not block the write.
    """
    computed_at = datetime.now(tz=UTC)
    payload = await compute_demo_main_kpis_payload(session, shop_id, computed_at=computed_at)
    repo = GoldKpiEnvelopesRepo(session)
    envelope = await repo.upsert(
        shop_id=shop_id,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=computed_at,
    )

    # Refresh Redis cache after successful Postgres upsert (fail-open, non-blocking)
    from juli_backend.services.gold_kpi_cache import (
        get_shared_redis_client,
        refresh_gold_kpi_envelope_cache,
    )

    redis_client = get_shared_redis_client()
    await refresh_gold_kpi_envelope_cache(shop_id, envelope, redis_client=redis_client)

    return envelope
