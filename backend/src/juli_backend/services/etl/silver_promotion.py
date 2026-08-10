"""Promote bronze append rows to silver domain upserts (#607)."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from juli_backend.models.models import AnalyticsPerformanceInterval, Order, Return
from juli_backend.repositories.repos import AnalyticsPerformanceRepo, OrdersRepo, ReturnsRepo
from juli_backend.services.etl.transform import (
    TransformError,
    bronze_order_to_upsert_kwargs,
    bronze_return_to_upsert_kwargs,
    transform_for_channel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juli_backend.models.models import (
        BronzeCtorPerformanceRawPayload,
        BronzeLiveHoursRawPayload,
        BronzeOrderRawPayload,
        BronzeReturnRawPayload,
    )


class SilverOrdersReturnsPromoter:
    """Bronze → silver promotion for orders/returns domain (#607)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrdersRepo(session)
        self._returns = ReturnsRepo(session)

    async def promote_order(self, bronze_row: BronzeOrderRawPayload) -> Order:
        if not isinstance(bronze_row.payload, dict):
            raise TransformError("bronze order payload must be a JSON object")
        received_at = bronze_row.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        kwargs = bronze_order_to_upsert_kwargs(bronze_row.payload, received_at=received_at)
        return await self._orders.upsert(shop_id=bronze_row.shop_id, **kwargs)

    async def promote_return(self, bronze_row: BronzeReturnRawPayload) -> Return:
        if not isinstance(bronze_row.payload, dict):
            raise TransformError("bronze return payload must be a JSON object")
        received_at = bronze_row.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        kwargs = bronze_return_to_upsert_kwargs(bronze_row.payload, received_at=received_at)
        order = await self._orders.get_by_tiktok_id(
            bronze_row.shop_id,
            kwargs["tiktok_order_id"],
        )
        if order is not None:
            kwargs["order_id"] = order.id
        return await self._returns.upsert(shop_id=bronze_row.shop_id, **kwargs)


class SilverAnalyticsPromoter:
    """Bronze → silver promotion for ctor (A-34) / live_hours (A-28) domains (#880).

    Bronze payloads for these two domains are already the normalized
    ``expand_analytics_*``/rollup shape (see ``services/etl/bronze_append.py``),
    so promotion is: run the same generic analytics transform the ETL consumer
    uses for webhook-delivered analytics channels, then upsert by
    ``snapshot_key`` — idempotent by construction (``AnalyticsPerformanceRepo``
    matches on the unique ``(shop_id, snapshot_key)`` index), so replaying the
    same bronze row never creates a duplicate interval row.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._performance = AnalyticsPerformanceRepo(session)

    async def promote_ctor(
        self,
        bronze_row: BronzeCtorPerformanceRawPayload,
    ) -> AnalyticsPerformanceInterval:
        if not isinstance(bronze_row.payload, dict):
            raise TransformError("bronze ctor payload must be a JSON object")
        _, kwargs = transform_for_channel("tiktok.analytics.product.raw", bronze_row.payload)
        return await self._performance.upsert(shop_id=bronze_row.shop_id, **kwargs)

    async def promote_live_hours(
        self,
        bronze_row: BronzeLiveHoursRawPayload,
    ) -> AnalyticsPerformanceInterval:
        if not isinstance(bronze_row.payload, dict):
            raise TransformError("bronze live_hours payload must be a JSON object")
        _, kwargs = transform_for_channel("tiktok.analytics.live.raw", bronze_row.payload)
        return await self._performance.upsert(shop_id=bronze_row.shop_id, **kwargs)
