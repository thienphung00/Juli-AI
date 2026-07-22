"""LIVE bucket partition E2E for analytics historical backfill (#468)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
)
from juli_backend.integrations.tiktok.mapping import (
    analytics_snapshot_key,
    expand_analytics_live_session,
)
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import (
    BudgetExhaustedError,
    CallBudgetGovernor,
)

LIVE_BUCKET = "live"

_BACKFILL_LIVE_GET_PATHS = frozenset({
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
})

_FORBIDDEN_LIVE_BACKFILL_PATH_PATTERNS = (
    re.compile(r"^/analytics/\d+/shop_lives/[^/]+/performance_per_minutes$"),
    re.compile(r"^/analytics/\d+/shop_lives/[^/]+/products/performance$"),
)

PartitionStatus = Literal["skipped", "complete", "paused", "failed"]


class LiveAnalyticsResource(Protocol):
    def get_live_overview_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]: ...

    def list_live_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class LivePartitionResult:
    status: PartitionStatus
    called_paths: tuple[str, ...] = ()


def backfill_live_allowed_get_paths() -> frozenset[str]:
    """GET paths the LIVE backfill partition may call (A-28 + A-29 only)."""
    return _BACKFILL_LIVE_GET_PATHS


def assert_no_forbidden_live_backfill_paths(called_paths: Iterable[str]) -> None:
    """Reject A-26/A-27 and other forbidden LIVE endpoints in backfill code paths."""
    for path in called_paths:
        normalized = path.split("?", 1)[0]
        if normalized not in _BACKFILL_LIVE_GET_PATHS:
            msg = f"forbidden LIVE backfill path: {path}"
            raise AssertionError(msg)
        for pattern in _FORBIDDEN_LIVE_BACKFILL_PATH_PATTERNS:
            if pattern.match(normalized):
                msg = f"forbidden LIVE backfill path: {path}"
                raise AssertionError(msg)


def _date_window(partition_date: date) -> tuple[str, str]:
    start = partition_date.isoformat()
    end = (partition_date + timedelta(days=1)).isoformat()
    return start, end


def _day_bounds(partition_date: date) -> tuple[int, int]:
    day_start = datetime(
        partition_date.year,
        partition_date.month,
        partition_date.day,
        tzinfo=UTC,
    )
    day_end = day_start + timedelta(days=1)
    return int(day_start.timestamp()), int(day_end.timestamp())


def compute_live_hours(
    sessions: list[dict[str, Any]],
    partition_date: date,
) -> Decimal:
    """Sum clipped session durations in hours for sessions intersecting the day."""
    day_start_ts, day_end_ts = _day_bounds(partition_date)
    total_seconds = 0
    for session in sessions:
        start_ts = session.get("start_time")
        end_ts = session.get("end_time")
        if start_ts is None or end_ts is None:
            continue
        clipped_start = max(int(start_ts), day_start_ts)
        clipped_end = min(int(end_ts), day_end_ts)
        if clipped_end <= clipped_start:
            continue
        total_seconds += clipped_end - clipped_start
    return (Decimal(total_seconds) / Decimal(3600)).quantize(Decimal("0.0001"))


def compute_live_sessions_count(sessions: list[dict[str, Any]]) -> int:
    return len(sessions)


def sum_live_views(sessions: list[dict[str, Any]]) -> int:
    total = 0
    for session in sessions:
        interaction = session.get("interaction_performance")
        if not isinstance(interaction, dict):
            continue
        views = interaction.get("views")
        if views is not None:
            total += int(views)
    return total


def sum_live_impressions(sessions: list[dict[str, Any]]) -> int:
    total = 0
    for session in sessions:
        interaction = session.get("interaction_performance")
        if not isinstance(interaction, dict):
            continue
        impressions = interaction.get("product_impressions")
        if impressions is not None:
            total += int(impressions)
    return total


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    cleaned = str(value).strip().rstrip("%")
    if not cleaned:
        return None
    return Decimal(cleaned)


def _extract_gmv_amount_currency(value: Any) -> tuple[Decimal | None, str | None]:
    gmv = _as_dict(value)
    amount = gmv.get("amount")
    if amount is None:
        return None, None
    currency = gmv.get("currency")
    return _optional_decimal(amount), str(currency) if currency else None


def _overview_interval_for_day(
    overview_response: dict[str, Any],
    partition_date: date,
) -> dict[str, Any] | None:
    data = _as_dict(overview_response.get("data"))
    performance = _as_dict(data.get("performance"))
    intervals = performance.get("intervals")
    if not isinstance(intervals, list):
        return None
    target = partition_date.isoformat()
    for interval in intervals:
        if isinstance(interval, dict) and interval.get("start_date") == target:
            return interval
    return None


def build_live_shop_rollup_kwargs(
    *,
    partition_date: date,
    sessions: list[dict[str, Any]],
    overview_response: dict[str, Any],
    synced_at: int,
) -> dict[str, Any]:
    start_date, end_date = _date_window(partition_date)
    overview = _overview_interval_for_day(overview_response, partition_date)
    gmv_amount: Decimal | None = None
    gmv_currency: str | None = None
    sku_orders: int | None = None
    customers: int | None = None
    click_through_rate: Decimal | None = None
    click_to_order_rate: Decimal | None = None
    if overview is not None:
        gmv_amount, gmv_currency = _extract_gmv_amount_currency(overview.get("gmv"))
        raw_orders = overview.get("sku_orders")
        sku_orders = int(raw_orders) if raw_orders is not None else None
        raw_customers = overview.get("customers")
        customers = int(raw_customers) if raw_customers is not None else None
        click_through_rate = _optional_decimal(overview.get("click_through_rate"))
        click_to_order_rate = _optional_decimal(overview.get("click_to_order_rate"))

    kwargs: dict[str, Any] = {
        "snapshot_key": analytics_snapshot_key(
            grain="shop",
            start_date=start_date,
            end_date=end_date,
        ),
        "grain": "shop",
        "start_date": partition_date,
        "end_date": date.fromisoformat(end_date),
        "update_time": datetime.fromtimestamp(synced_at, tz=UTC),
        "live_hours": compute_live_hours(sessions, partition_date),
        "live_sessions": compute_live_sessions_count(sessions),
        "visitors": sum_live_views(sessions),
        "impressions": sum_live_impressions(sessions),
    }
    if gmv_amount is not None:
        kwargs["gmv"] = gmv_amount
    if gmv_currency is not None:
        kwargs["gmv_currency"] = gmv_currency
    if sku_orders is not None:
        kwargs["sku_orders"] = sku_orders
    if customers is not None:
        kwargs["customers"] = customers
    if click_through_rate is not None:
        kwargs["click_through_rate"] = click_through_rate
    if click_to_order_rate is not None:
        kwargs["click_to_order_rate"] = click_to_order_rate
    return kwargs


def _record_partner_get(
    budget: CallBudgetGovernor,
    path: str,
    called_paths: list[str],
) -> None:
    assert_no_forbidden_live_backfill_paths([path])
    if budget.should_stop():
        raise BudgetExhaustedError("Partner call budget soft cap reached")
    budget.record_attempt()
    called_paths.append(path)


async def run_live_partition(
    *,
    shop_id: Any,
    partition_date: date,
    analytics: LiveAnalyticsResource,
    budget: CallBudgetGovernor,
    partitions_repo: AnalyticsBackfillPartitionsRepo,
    performance_repo: AnalyticsPerformanceRepo,
    synced_at: int,
) -> LivePartitionResult:
    """Fetch A-29 + A-28 for one calendar day and upsert LIVE rollup rows."""
    if await partitions_repo.is_complete(shop_id, LIVE_BUCKET, partition_date):
        return LivePartitionResult(status="skipped")

    start_date_ge, end_date_lt = _date_window(partition_date)
    called_paths: list[str] = []

    try:
        if budget.should_stop():
            return LivePartitionResult(status="paused", called_paths=tuple(called_paths))

        _record_partner_get(budget, ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH, called_paths)
        overview_response = analytics.get_live_overview_performance(
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )
        budget.record_success()

        if budget.should_stop():
            return LivePartitionResult(status="paused", called_paths=tuple(called_paths))

        _record_partner_get(budget, ANALYTICS_LIVE_PERFORMANCE_LIST_PATH, called_paths)
        sessions = analytics.list_live_performance_all(
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )
        budget.record_success()

        rollup_kwargs = build_live_shop_rollup_kwargs(
            partition_date=partition_date,
            sessions=sessions,
            overview_response=overview_response,
            synced_at=synced_at,
        )
        await performance_repo.upsert(shop_id=shop_id, **rollup_kwargs)

        for session in sessions:
            session_row = expand_analytics_live_session(
                session,
                start_date=start_date_ge,
                end_date=end_date_lt,
                synced_at=synced_at,
            )
            if session_row is None:
                continue
            session_kwargs = _session_row_to_upsert_kwargs(session_row, synced_at)
            await performance_repo.upsert(shop_id=shop_id, **session_kwargs)

        await partitions_repo.mark_complete(shop_id, LIVE_BUCKET, partition_date)
        return LivePartitionResult(status="complete", called_paths=tuple(called_paths))
    except BudgetExhaustedError:
        return LivePartitionResult(status="paused", called_paths=tuple(called_paths))
    except Exception:
        await partitions_repo.mark_failed(
            shop_id,
            LIVE_BUCKET,
            partition_date,
            "LIVE partition failed",
        )
        raise


def _session_row_to_upsert_kwargs(row: dict[str, Any], synced_at: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "snapshot_key": row["snapshot_key"],
        "grain": row["grain"],
        "start_date": date.fromisoformat(str(row["start_date"])),
        "update_time": datetime.fromtimestamp(synced_at, tz=UTC),
    }
    if row.get("end_date"):
        kwargs["end_date"] = date.fromisoformat(str(row["end_date"]))
    if row.get("live_id"):
        kwargs["tiktok_live_id"] = str(row["live_id"])
    metric_fields = (
        "gmv",
        "gmv_currency",
        "sku_orders",
        "items_sold",
        "customers",
        "click_through_rate",
        "click_to_order_rate",
        "impressions",
        "visitors",
    )
    for field in metric_fields:
        if field in row and row[field] is not None:
            if field in {"gmv", "click_through_rate", "click_to_order_rate"}:
                kwargs[field] = _optional_decimal(row[field])
            else:
                kwargs[field] = row[field]
    return kwargs
