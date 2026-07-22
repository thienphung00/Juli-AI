"""Phase 2.9 analytics backfill coverage reporter (#471).

Computes calendar-day coverage for Revenue (A-36), LIVE overview (A-29-derived),
and Product list (A-34) against ADR-029 / PRD exit thresholds.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.repositories.repos import AnalyticsBackfillPartitionsRepo
from juli_backend.services.analytics_backfill.catalog_partition import (
    CatalogCountStrategy,
)
from juli_backend.services.analytics_backfill.orchestrator import BACKFILL_WINDOW_START

REVENUE_LIVE_COVERAGE_THRESHOLD = 0.95
PRODUCT_COVERAGE_THRESHOLD = 0.90

_COVERAGE_NOTES: tuple[str, ...] = (
    "Ads are out of Phase 2.9 scope.",
    "Product Impressions/Views are out of Phase 2.9 exit.",
    "GMV is TikTok GMV — not Net Revenue.",
)

_CATALOG_GRAINS: tuple[str, ...] = ("catalog_daily", "catalog_point_in_time")


@dataclass(frozen=True)
class BucketCoverageResult:
    bucket: str
    days_present: int
    days_total: int
    coverage_pct: float
    missing_dates: tuple[str, ...]
    gate_pass: bool | None = None


@dataclass(frozen=True)
class CoverageReport:
    shop_id: uuid.UUID
    window_start: date
    window_end: date
    generated_at: datetime
    days_total: int
    buckets: tuple[BucketCoverageResult, ...]
    revenue_live_gate: bool
    product_gate: bool
    catalog_mode: str
    exit_ready: bool
    notes: tuple[str, ...]


def iter_calendar_days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def coverage_ratio(days_present: int, days_total: int) -> float:
    if days_total <= 0:
        return 0.0
    return round((days_present / days_total) * 100.0, 1)


def meets_coverage_threshold(
    days_present: int,
    days_total: int,
    threshold: float,
) -> bool:
    """Return True when ``days_present / days_total >= threshold`` (exact fraction)."""
    if days_total <= 0:
        return False
    return days_present / days_total >= threshold


def _shop_row_has_revenue(row: AnalyticsPerformanceInterval) -> bool:
    return row.gmv is not None or row.orders_count is not None


def _shop_row_has_live(row: AnalyticsPerformanceInterval) -> bool:
    return row.live_hours is not None or row.live_sessions is not None


def _build_bucket_coverage(
    *,
    bucket: str,
    days_present: int,
    days_total: int,
    missing_dates: Sequence[date],
    threshold: float | None,
) -> BucketCoverageResult:
    gate_pass: bool | None = None
    if threshold is not None:
        gate_pass = meets_coverage_threshold(days_present, days_total, threshold)
    return BucketCoverageResult(
        bucket=bucket,
        days_present=days_present,
        days_total=days_total,
        coverage_pct=coverage_ratio(days_present, days_total),
        missing_dates=tuple(sorted(d.isoformat() for d in missing_dates)),
        gate_pass=gate_pass,
    )


def _merge_missing_dates(
    data_gaps: set[date],
    incomplete_partitions: Sequence[date],
) -> tuple[date, ...]:
    merged = set(data_gaps)
    merged.update(incomplete_partitions)
    return tuple(sorted(merged))


async def _load_shop_rows_by_date(
    session: AsyncSession,
    shop_id: uuid.UUID,
    start: date,
    end: date,
) -> dict[date, AnalyticsPerformanceInterval]:
    stmt = select(AnalyticsPerformanceInterval).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == "shop",
        AnalyticsPerformanceInterval.start_date >= start,
        AnalyticsPerformanceInterval.start_date <= end,
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {row.start_date: row for row in rows}


async def _load_product_dates(
    session: AsyncSession,
    shop_id: uuid.UUID,
    start: date,
    end: date,
) -> set[date]:
    stmt = select(AnalyticsPerformanceInterval.start_date).where(
        AnalyticsPerformanceInterval.shop_id == shop_id,
        AnalyticsPerformanceInterval.grain == "product",
        AnalyticsPerformanceInterval.start_date >= start,
        AnalyticsPerformanceInterval.start_date <= end,
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def _infer_catalog_mode(
    session: AsyncSession,
    shop_id: uuid.UUID,
    start: date,
    end: date,
) -> str:
    stmt = (
        select(AnalyticsPerformanceInterval.grain)
        .where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.grain.in_(_CATALOG_GRAINS),
            AnalyticsPerformanceInterval.start_date >= start,
            AnalyticsPerformanceInterval.start_date <= end,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    grain = result.scalar_one_or_none()
    if grain == "catalog_point_in_time":
        return "point_in_time_fallback"
    if grain == "catalog_daily":
        return "daily"
    return "daily"


async def _incomplete_partition_dates(
    partitions_repo: AnalyticsBackfillPartitionsRepo,
    shop_id: uuid.UUID,
    bucket: str,
    start: date,
    end: date,
) -> list[date]:
    rows = await partitions_repo.list_incomplete(shop_id, bucket, start, end)
    return [row.partition_date for row in rows]


async def generate_coverage_report(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date,
    generated_at: datetime | None = None,
) -> CoverageReport:
    """Build machine- and human-readable coverage for the analytics backfill window."""
    window_start = start_date or BACKFILL_WINDOW_START
    window_end = end_date
    calendar_days = iter_calendar_days(window_start, window_end)
    days_total = len(calendar_days)

    shop_rows = await _load_shop_rows_by_date(session, shop_id, window_start, window_end)
    product_dates = await _load_product_dates(session, shop_id, window_start, window_end)
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)

    revenue_present: list[date] = []
    live_present: list[date] = []
    revenue_live_present: list[date] = []
    revenue_data_gaps: set[date] = set()
    live_data_gaps: set[date] = set()
    revenue_live_data_gaps: set[date] = set()
    product_data_gaps: set[date] = set()

    for day in calendar_days:
        row = shop_rows.get(day)
        has_revenue = row is not None and _shop_row_has_revenue(row)
        has_live = row is not None and _shop_row_has_live(row)
        if has_revenue:
            revenue_present.append(day)
        else:
            revenue_data_gaps.add(day)
        if has_live:
            live_present.append(day)
        else:
            live_data_gaps.add(day)
        if has_revenue and has_live:
            revenue_live_present.append(day)
        else:
            revenue_live_data_gaps.add(day)
        if day not in product_dates:
            product_data_gaps.add(day)

    revenue_incomplete = await _incomplete_partition_dates(
        partitions_repo, shop_id, "revenue", window_start, window_end
    )
    live_incomplete = await _incomplete_partition_dates(
        partitions_repo, shop_id, "live", window_start, window_end
    )
    product_incomplete = await _incomplete_partition_dates(
        partitions_repo, shop_id, "product", window_start, window_end
    )

    revenue_missing = _merge_missing_dates(revenue_data_gaps, revenue_incomplete)
    live_missing = _merge_missing_dates(live_data_gaps, live_incomplete)
    revenue_live_missing = _merge_missing_dates(
        revenue_live_data_gaps,
        revenue_incomplete + live_incomplete,
    )
    product_missing = _merge_missing_dates(product_data_gaps, product_incomplete)

    revenue_bucket = _build_bucket_coverage(
        bucket="revenue",
        days_present=len(revenue_present),
        days_total=days_total,
        missing_dates=revenue_missing,
        threshold=None,
    )
    live_bucket = _build_bucket_coverage(
        bucket="live",
        days_present=len(live_present),
        days_total=days_total,
        missing_dates=live_missing,
        threshold=None,
    )
    revenue_live_bucket = _build_bucket_coverage(
        bucket="revenue_live",
        days_present=len(revenue_live_present),
        days_total=days_total,
        missing_dates=revenue_live_missing,
        threshold=REVENUE_LIVE_COVERAGE_THRESHOLD,
    )
    product_bucket = _build_bucket_coverage(
        bucket="product",
        days_present=len(product_dates & set(calendar_days)),
        days_total=days_total,
        missing_dates=product_missing,
        threshold=PRODUCT_COVERAGE_THRESHOLD,
    )

    catalog_mode = await _infer_catalog_mode(session, shop_id, window_start, window_end)
    catalog_bucket = _build_bucket_coverage(
        bucket="catalog",
        days_present=0,
        days_total=days_total,
        missing_dates=(),
        threshold=None,
    )

    revenue_live_gate = revenue_live_bucket.gate_pass is True
    product_gate = product_bucket.gate_pass is True

    return CoverageReport(
        shop_id=shop_id,
        window_start=window_start,
        window_end=window_end,
        generated_at=generated_at or datetime.now(tz=UTC),
        days_total=days_total,
        buckets=(
            revenue_bucket,
            live_bucket,
            revenue_live_bucket,
            product_bucket,
            catalog_bucket,
        ),
        revenue_live_gate=revenue_live_gate,
        product_gate=product_gate,
        catalog_mode=catalog_mode,
        exit_ready=revenue_live_gate and product_gate,
        notes=_COVERAGE_NOTES,
    )


def coverage_report_to_dict(report: CoverageReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["shop_id"] = str(report.shop_id)
    payload["window_start"] = report.window_start.isoformat()
    payload["window_end"] = report.window_end.isoformat()
    payload["generated_at"] = report.generated_at.isoformat()
    payload["buckets"] = [asdict(bucket) for bucket in report.buckets]
    payload["catalog_strategy"] = (
        CatalogCountStrategy.POINT_IN_TIME.value
        if report.catalog_mode == "point_in_time_fallback"
        else CatalogCountStrategy.DAILY.value
    )
    return payload


def coverage_report_to_json(report: CoverageReport, *, indent: int = 2) -> str:
    return json.dumps(coverage_report_to_dict(report), indent=indent)


def coverage_report_to_markdown(report: CoverageReport) -> str:
    lines = [
        "# Analytics backfill coverage",
        "",
        f"- **shop_id:** `{report.shop_id}`",
        f"- **window:** {report.window_start.isoformat()} → "
        f"{report.window_end.isoformat()} ({report.days_total} days)",
        f"- **generated_at:** {report.generated_at.isoformat()}",
        f"- **catalog_mode:** {report.catalog_mode}",
        f"- **revenue+live gate (≥95%):** "
        f"{'PASS' if report.revenue_live_gate else 'FAIL'}",
        f"- **product gate (≥90%):** {'PASS' if report.product_gate else 'FAIL'}",
        f"- **exit_ready:** {'true' if report.exit_ready else 'false'}",
        "",
        "## Buckets",
    ]
    for bucket in report.buckets:
        if bucket.bucket == "catalog":
            continue
        gate = ""
        if bucket.gate_pass is not None:
            gate = f" — gate {'PASS' if bucket.gate_pass else 'FAIL'}"
        lines.append(
            f"- **{bucket.bucket}:** {bucket.days_present}/{bucket.days_total} "
            f"({bucket.coverage_pct}%){gate}"
        )
        if bucket.missing_dates:
            preview = ", ".join(bucket.missing_dates[:5])
            suffix = "…" if len(bucket.missing_dates) > 5 else ""
            lines.append(f"  - missing: {preview}{suffix}")
    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines)
