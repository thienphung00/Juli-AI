"""Promote bronze append rows to silver domain upserts (#607)."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from juli_backend.models.models import Order, Return
from juli_backend.repositories.repos import OrdersRepo, ReturnsRepo
from juli_backend.services.etl.transform import (
    TransformError,
    bronze_order_to_upsert_kwargs,
    bronze_return_to_upsert_kwargs,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juli_backend.models.models import BronzeOrderRawPayload, BronzeReturnRawPayload


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
