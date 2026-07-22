"""Product funnel backfill partition — A-34 Get Shop Product Performance List (#467).

Uses a **1-day** Partner window per calendar partition date
(``start_date_ge=date``, ``end_date_lt=date+1``). The A-34 payload exposes
window-total ``total_performance`` per product (not daily intervals).

Product Impressions / Product Views are **deferred** — they require A-33 detail
fan-out, which is out of scope for Phase 2.9 exit.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.integrations.tiktok.mapping import expand_analytics_product_list_item
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import (
    BudgetExhaustedError,
    CallBudgetGovernor,
)
from juli_backend.services.etl.transform import transform_for_channel

PRODUCT_BUCKET = "product"
_ANALYTICS_PRODUCT_CHANNEL = "tiktok.analytics.product.raw"
_DEFAULT_PAGE_SIZE = 50


class ProductPerformanceResource(Protocol):
    def list_product_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProductPartitionResult:
    skipped: bool = False
    complete: bool = False
    products_upserted: int = 0
    pages_fetched: int = 0
    error: str | None = None


def _partition_date_window(partition_date: date) -> tuple[str, str]:
    start_date_ge = partition_date.isoformat()
    end_date_lt = (partition_date + timedelta(days=1)).isoformat()
    return start_date_ge, end_date_lt


async def backfill_product_partition(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    partition_date: date,
    resource: ProductPerformanceResource,
    budget: CallBudgetGovernor,
    synced_at: int | None = None,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> ProductPartitionResult:
    """Backfill one calendar-day product funnel partition via paginated A-34."""
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)
    if await partitions_repo.is_complete(shop_id, PRODUCT_BUCKET, partition_date):
        return ProductPartitionResult(skipped=True, complete=True)

    start_date_ge, end_date_lt = _partition_date_window(partition_date)
    resolved_synced_at = synced_at if synced_at is not None else int(time.time())
    perf_repo = AnalyticsPerformanceRepo(session)

    page_token: str | None = None
    products_upserted = 0
    pages_fetched = 0

    while True:
        try:
            budget.record_attempt()
        except BudgetExhaustedError as exc:
            return ProductPartitionResult(
                products_upserted=products_upserted,
                pages_fetched=pages_fetched,
                error=str(exc),
            )

        try:
            data = resource.list_product_performance(
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
                page_size=page_size,
                page_token=page_token,
            )
            budget.record_success()
        except TikTokAPIError as exc:
            budget.record_failure()
            await partitions_repo.mark_failed(
                shop_id,
                PRODUCT_BUCKET,
                partition_date,
                str(exc),
            )
            return ProductPartitionResult(
                products_upserted=products_upserted,
                pages_fetched=pages_fetched,
                error=str(exc),
            )

        pages_fetched += 1
        products = data.get("products", []) if isinstance(data, dict) else []
        if isinstance(products, list):
            for product in products:
                if not isinstance(product, dict):
                    continue
                row = expand_analytics_product_list_item(
                    product,
                    start_date=start_date_ge,
                    end_date=end_date_lt,
                    synced_at=resolved_synced_at,
                )
                if row is None:
                    continue
                _, kwargs = transform_for_channel(_ANALYTICS_PRODUCT_CHANNEL, row)
                await perf_repo.upsert(shop_id=shop_id, **kwargs)
                products_upserted += 1

        next_token: str | None = None
        if isinstance(data, dict):
            raw_token = data.get("next_page_token") or data.get("page_token")
            if raw_token:
                next_token = str(raw_token)

        if not next_token:
            break
        page_token = next_token

    await partitions_repo.mark_complete(shop_id, PRODUCT_BUCKET, partition_date)
    return ProductPartitionResult(
        complete=True,
        products_upserted=products_upserted,
        pages_fetched=pages_fetched,
    )
