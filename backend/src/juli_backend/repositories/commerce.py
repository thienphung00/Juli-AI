"""Orders, order lines, returns, products, inventory and settlements.

These are the silver-layer domain rows synced from TikTok (ADR-046). Every
repository here is a :class:`ShopScopedRepo` whose ``_lookup_attrs`` name the
vendor's natural key, so ETL upserts are idempotent per shop.

One-writer rule: ``OrdersRepo.upsert`` and ``ReturnsRepo.upsert`` may only be
called from ``services.etl`` (enforced by ``agent-runtime/scripts/ci/
medallion_one_writer.py``). Readers may be many.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from juli_backend.models.models import (
    InventoryItem,
    Order,
    OrderItem,
    Product,
    Return,
    Settlement,
)
from juli_backend.repositories._base import ShopScopedRepo, utc_now_naive

AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
SHIPPED = "SHIPPED"


class OrdersRepo(ShopScopedRepo[Order]):
    _model = Order
    _lookup_attrs = ("tiktok_order_id",)

    async def get_by_tiktok_id(self, shop_id: uuid.UUID, tiktok_order_id: str) -> Order | None:
        return await self._one_or_none(
            self._scoped(shop_id, Order.tiktok_order_id == tiktok_order_id)
        )

    async def list_filtered(
        self,
        shop_id: uuid.UUID,
        *,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[Order]:
        """Newest first, optionally narrowed by status and ``update_time`` window."""
        stmt = self._scoped(shop_id)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if date_from is not None:
            stmt = stmt.where(Order.update_time >= date_from)
        if date_to is not None:
            stmt = stmt.where(Order.update_time <= date_to)
        return await self._paginate(stmt, sort_column=Order.created_at, after=after, limit=limit)

    async def confirm_shipment(self, shop_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        """Move an ``AWAITING_SHIPMENT`` order to ``SHIPPED``.

        Raises :class:`NotFound` for a missing or foreign order and ``ValueError``
        for any other starting status; the state machine has exactly one edge.
        """
        order = await self.get(shop_id, order_id)
        if order.status != AWAITING_SHIPMENT:
            raise ValueError(f"Cannot ship order in status '{order.status}'")
        order.status = SHIPPED
        order.update_time = utc_now_naive()
        await self._session.flush()
        return order


class OrderItemsRepo(ShopScopedRepo[OrderItem]):
    """Order lines are keyed by ``(order, sku)``: one SKU can appear on many orders."""

    _model = OrderItem
    _lookup_attrs = ("tiktok_order_id", "tiktok_sku_id")


class ReturnsRepo(ShopScopedRepo[Return]):
    _model = Return
    _lookup_attrs = ("tiktok_return_id",)


class ProductsRepo(ShopScopedRepo[Product]):
    _model = Product
    _lookup_attrs = ("tiktok_product_id",)

    async def recompute_revenue_from_order_items(
        self, shop_id: uuid.UUID, tiktok_product_id: str
    ) -> None:
        """Set ``revenue``/``units_sold`` from the sum of synced order lines (#943).

        A full recompute, never an increment: ``OrderItemsRepo.upsert`` overwrites
        a redelivered line rather than diffing it, so adding deltas would double
        count. Updating zero rows (product not synced yet) is fine -- the next
        recompute for that id picks it up once the product row exists.
        """
        totals_stmt = self._scoped_order_item_totals(shop_id, tiktok_product_id)
        revenue, units_sold = (await self._session.execute(totals_stmt)).one()
        await self._session.execute(
            update(Product)
            .where(Product.shop_id == shop_id, Product.tiktok_product_id == tiktok_product_id)
            .values(revenue=revenue, units_sold=units_sold)
        )
        await self._session.flush()

    @staticmethod
    def _scoped_order_item_totals(shop_id: uuid.UUID, tiktok_product_id: str):
        return select(
            func.coalesce(func.sum(OrderItem.line_total), 0),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        ).where(
            OrderItem.shop_id == shop_id,
            OrderItem.tiktok_product_id == tiktok_product_id,
        )

    async def list_by_revenue(
        self,
        shop_id: uuid.UUID,
        *,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[Product]:
        return await self._paginate(
            self._scoped(shop_id), sort_column=Product.revenue, after=after, limit=limit
        )

    async def get_highest_revenue_product(self, shop_id: uuid.UUID) -> Product | None:
        """The ADR-082 product-binding rule: top ``revenue``, then ``tiktok_product_id`` ascending.

        The tiebreak is load-bearing. Without it two products with equal revenue
        resolve in whatever order Postgres returns them, and the same ActionCard
        approved twice could bind to different listings for no reason a seller
        could see. ``None`` when the shop has no products; the caller turns that
        into ``NoProductsForShop`` rather than a run with a NULL product.
        """
        stmt = (
            self._scoped(shop_id)
            .order_by(Product.revenue.desc(), Product.tiktok_product_id.asc())
            .limit(1)
        )
        return await self._one_or_none(stmt)


class InventoryRepo(ShopScopedRepo[InventoryItem]):
    _model = InventoryItem
    _lookup_attrs = ("tiktok_sku_id",)


class SettlementsRepo(ShopScopedRepo[Settlement]):
    _model = Settlement
    _lookup_attrs = ("tiktok_settlement_id",)


__all__ = [
    "AWAITING_SHIPMENT",
    "InventoryRepo",
    "OrderItemsRepo",
    "OrdersRepo",
    "ProductsRepo",
    "ReturnsRepo",
    "SHIPPED",
    "SettlementsRepo",
]
