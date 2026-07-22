"""Catalog Active/New partition backfill via A-2 Search Products (#469).

A-2 returns the **current** catalog snapshot, not historical listing status.
``CatalogCountStrategy.DAILY`` applies trailing-7-day ``create_time`` windows for
*New* counts; *Active* uses the current ``status`` allowlist (best-effort for
historical dates). ``CatalogCountStrategy.POINT_IN_TIME`` is the documented
fallback: point-in-time Active plus New-since-``BACKFILL_WINDOW_START``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import CallBudgetGovernor

CATALOG_BUCKET = "catalog"
BACKFILL_WINDOW_START = date(2026, 3, 16)

# Listing statuses treated as live/active for catalog metrics (A-2 ``status`` field).
# Contract sample uses ``ACTIVATE``; extend here if Partner documents additional live states.
ACTIVE_PRODUCT_STATUSES = frozenset({"ACTIVATE"})

TRAILING_NEW_DAYS = 7


class CatalogCountStrategy(str, Enum):
    """How to derive Active/New from the current A-2 catalog snapshot."""

    DAILY = "daily"
    POINT_IN_TIME = "point_in_time"


@dataclass(frozen=True)
class CatalogCounts:
    active_products: int
    new_products: int
    strategy: CatalogCountStrategy


@dataclass(frozen=True)
class CatalogPartitionResult:
    status: Literal["completed", "skipped", "failed"]
    partition_date: date
    strategy: CatalogCountStrategy
    active_products: int | None = None
    new_products: int | None = None
    error: str | None = None


class ProductsSearch(Protocol):
    def search_all(self, *, page_size: int = 50) -> list[dict]: ...


def _create_date(create_time: int | None) -> date | None:
    if create_time is None:
        return None
    return datetime.fromtimestamp(create_time, tz=UTC).date()


def _trailing_window_end(partition_date: date, *, days: int = TRAILING_NEW_DAYS) -> tuple[date, date]:
    window_start = partition_date - timedelta(days=days - 1)
    return window_start, partition_date


def _is_active(product: dict) -> bool:
    status = product.get("status")
    return isinstance(status, str) and status in ACTIVE_PRODUCT_STATUSES


def _count_active(products: list[dict]) -> int:
    return sum(1 for product in products if _is_active(product))


def _count_new_daily(products: list[dict], *, partition_date: date) -> int:
    window_start, window_end = _trailing_window_end(partition_date)
    count = 0
    for product in products:
        created = _create_date(product.get("create_time"))
        if created is not None and window_start <= created <= window_end:
            count += 1
    return count


def _count_new_since_window_start(products: list[dict]) -> int:
    count = 0
    for product in products:
        created = _create_date(product.get("create_time"))
        if created is not None and created >= BACKFILL_WINDOW_START:
            count += 1
    return count


def compute_catalog_counts(
    products: list[dict],
    *,
    partition_date: date,
    strategy: CatalogCountStrategy = CatalogCountStrategy.DAILY,
) -> CatalogCounts:
    """Derive Active/New counts from an A-2 Search Products payload."""
    active = _count_active(products)
    if strategy is CatalogCountStrategy.POINT_IN_TIME:
        new = _count_new_since_window_start(products)
    else:
        new = _count_new_daily(products, partition_date=partition_date)
    return CatalogCounts(
        active_products=active,
        new_products=new,
        strategy=strategy,
    )


def _catalog_grain(strategy: CatalogCountStrategy) -> str:
    if strategy is CatalogCountStrategy.POINT_IN_TIME:
        return "catalog_point_in_time"
    return "catalog_daily"


def _catalog_snapshot_key(partition_date: date, *, strategy: CatalogCountStrategy) -> str:
    grain = _catalog_grain(strategy)
    return "|".join(
        [
            grain,
            partition_date.isoformat(),
            partition_date.isoformat(),
            "",
            "",
            "",
            "",
        ]
    )


def _fetch_products_via_a2(
    products: ProductsSearch,
    budget: CallBudgetGovernor | None,
) -> list[dict]:
    if budget is not None:
        budget.record_attempt()
    try:
        rows = products.search_all(page_size=50)
    except Exception:
        if budget is not None:
            budget.record_failure()
        raise
    if budget is not None:
        budget.record_success()
    return rows


async def run_catalog_partition(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    partition_date: date,
    products: ProductsSearch,
    strategy: CatalogCountStrategy = CatalogCountStrategy.DAILY,
    budget: CallBudgetGovernor | None = None,
    skip_if_complete: bool = True,
) -> CatalogPartitionResult:
    """Fetch catalog via A-2, persist counts, and advance partition progress."""
    partitions = AnalyticsBackfillPartitionsRepo(session)
    if skip_if_complete and await partitions.is_complete(
        shop_id, CATALOG_BUCKET, partition_date
    ):
        return CatalogPartitionResult(
            status="skipped",
            partition_date=partition_date,
            strategy=strategy,
        )

    try:
        product_rows = _fetch_products_via_a2(products, budget)
        counts = compute_catalog_counts(
            product_rows,
            partition_date=partition_date,
            strategy=strategy,
        )
    except Exception as exc:
        await partitions.mark_failed(
            shop_id,
            CATALOG_BUCKET,
            partition_date,
            str(exc),
        )
        return CatalogPartitionResult(
            status="failed",
            partition_date=partition_date,
            strategy=strategy,
            error=str(exc),
        )

    synced_at = int(datetime.now(tz=UTC).timestamp())
    perf_repo = AnalyticsPerformanceRepo(session)
    await perf_repo.upsert(
        shop_id=shop_id,
        snapshot_key=_catalog_snapshot_key(partition_date, strategy=strategy),
        grain=_catalog_grain(strategy),
        start_date=partition_date,
        end_date=partition_date,
        active_products=counts.active_products,
        new_products=counts.new_products,
        update_time=datetime.fromtimestamp(synced_at, tz=UTC),
    )
    await partitions.mark_complete(shop_id, CATALOG_BUCKET, partition_date)

    return CatalogPartitionResult(
        status="completed",
        partition_date=partition_date,
        strategy=strategy,
        active_products=counts.active_products,
        new_products=counts.new_products,
    )
