"""Revenue-core partition backfill for one calendar day (P2-9-4 / #466)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.integrations.tiktok.mapping import expand_analytics_shop_performance
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import CallBudgetGovernor
from juli_backend.services.etl.transform import transform_for_channel

RevenuePartitionStatus = Literal["skipped", "complete", "failed"]

BUCKET = "revenue"


class AnalyticsResourceProtocol(Protocol):
    def get_shop_performance(
        self, *, start_date_ge: str, end_date_lt: str
    ) -> dict[str, Any]: ...

    def get_shop_performance_per_hour(self, *, date: str) -> dict[str, Any]: ...


def _partition_window(partition_date: date) -> tuple[str, str]:
    start_date_ge = partition_date.isoformat()
    end_date_lt = (partition_date + timedelta(days=1)).isoformat()
    return start_date_ge, end_date_lt


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_customers_from_per_hour(data: dict[str, Any]) -> int | None:
    """A-37 customers: prefer performance.overall.customers; else sum hourly buckets."""
    performance = data.get("performance") if isinstance(data, dict) else None
    if not isinstance(performance, dict):
        return None

    overall = performance.get("overall")
    if isinstance(overall, dict):
        customers = _optional_int(overall.get("customers"))
        if customers is not None:
            return customers

    intervals = performance.get("intervals")
    if not isinstance(intervals, list):
        return None

    total = 0
    found = False
    for interval in intervals:
        if not isinstance(interval, dict):
            continue
        customers = _optional_int(interval.get("customers"))
        if customers is None:
            continue
        total += customers
        found = True
    return total if found else None


def _select_daily_row(
    rows: list[dict[str, Any]], partition_date: date
) -> dict[str, Any] | None:
    date_str = partition_date.isoformat()
    for row in rows:
        if row.get("grain") == "shop" and row.get("start_date") == date_str:
            return row
    for row in rows:
        if row.get("grain") == "shop":
            return row
    return None


def derive_aov(gmv: Any, orders_count: int | None) -> Decimal | None:
    """Average order value (GMV / orders) when orders > 0."""
    if orders_count is None or orders_count <= 0 or gmv is None:
        return None
    return (Decimal(str(gmv)) / Decimal(orders_count)).quantize(Decimal("1"))


async def backfill_revenue_partition(
    *,
    shop_id: uuid.UUID,
    partition_date: date,
    analytics_resource: AnalyticsResourceProtocol,
    partitions_repo: AnalyticsBackfillPartitionsRepo,
    performance_repo: AnalyticsPerformanceRepo,
    budget: CallBudgetGovernor,
    synced_at: int,
) -> RevenuePartitionStatus:
    """Backfill one revenue partition: A-36 daily GMV/orders + A-37 customers."""
    if await partitions_repo.is_complete(shop_id, BUCKET, partition_date):
        return "skipped"

    start_date_ge, end_date_lt = _partition_window(partition_date)
    date_str = partition_date.isoformat()

    try:
        budget.record_attempt()
        shop_performance = analytics_resource.get_shop_performance(
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )
        budget.record_success()

        budget.record_attempt()
        per_hour = analytics_resource.get_shop_performance_per_hour(date=date_str)
        budget.record_success()
    except TikTokAPIError as exc:
        budget.record_failure()
        await partitions_repo.mark_failed(
            shop_id,
            BUCKET,
            partition_date,
            str(exc),
            retryable=True,
        )
        return "failed"

    rows = expand_analytics_shop_performance(shop_performance, synced_at=synced_at)
    daily_row = _select_daily_row(rows, partition_date)
    if daily_row is None:
        budget.record_failure()
        await partitions_repo.mark_failed(
            shop_id,
            BUCKET,
            partition_date,
            f"No A-36 shop interval for {date_str}",
            retryable=True,
        )
        return "failed"

    customers = _extract_customers_from_per_hour(per_hour)
    if customers is not None:
        daily_row["customers"] = customers

    _, upsert_kwargs = transform_for_channel("tiktok.analytics.shop.raw", daily_row)
    await performance_repo.upsert(shop_id=shop_id, **upsert_kwargs)
    await partitions_repo.mark_complete(shop_id, BUCKET, partition_date)
    return "complete"
