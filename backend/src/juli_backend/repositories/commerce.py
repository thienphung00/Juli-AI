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
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import func, select, update

from juli_backend.models.models import (
    InventoryItem,
    Order,
    OrderItem,
    Product,
    Return,
    Settlement,
)
from juli_backend.models.order_status import CANCELLED, UNKNOWN_ORDER_STATUS, is_cancelled_status
from juli_backend.repositories._base import ShopScopedRepo, utc_now_naive

AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
SHIPPED = "SHIPPED"

#: Amount columns where a stored 0 is ``OrdersRepo._insert_defaults``' placeholder.
_ZERO_IS_GAP: frozenset[str] = frozenset({"total_amount", "order_value"})


def _is_gap(name: str, current: Any) -> bool:
    return current is None or (name in _ZERO_IS_GAP and current == 0)


def _status_is_gap(current: Any) -> bool:
    """No status yet, ``unknown``, or a cancellation spelled other than ``cancelled``."""
    return (
        current is None
        or current == UNKNOWN_ORDER_STATUS
        or (is_cancelled_status(current) and current != CANCELLED)
    )


class OrdersRepo(ShopScopedRepo[Order]):
    _model = Order
    _lookup_attrs = ("tiktok_order_id",)
    #: A status webhook creates the row with no amount (P70, E15): placeholders.
    _insert_defaults: ClassVar[Mapping[str, Any]] = {
        "total_amount": Decimal("0"),
        "currency": "VND",
    }

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

    async def _apply_if_newer(
        self, existing: Order, values: Mapping[str, Any], *, full_snapshot: bool = False
    ) -> Order:
        """Merge one order write into the stored row (P70, E15).

        Two writers feed ``silver.orders``: the poll's whole-order snapshot
        (``full_snapshot=True``) and status webhooks that carry only the order id,
        status and update time. The merge:

        * a snapshot wins when its ``update_time`` is at or after the stored one --
          equal included, so a webhook that landed the same TikTok event first
          cannot keep the poll from completing the row;
        * a webhook (partial) wins only when strictly newer;
        * a write that does not win still fills gaps: a NULL column, an amount
          stored as the 0 placeholder (``_insert_defaults``), a status that is
          ``unknown`` or a cancellation not spelled ``cancelled`` (pre-P70 ``cancel``);
        * a winning write never blanks a stored value with ``None`` and never
          replaces a known status with ``unknown``.
        """
        incoming = values.get("update_time")
        stored = existing.update_time
        if incoming is None or stored is None:
            wins = True
        else:
            wins = incoming >= stored if full_snapshot else incoming > stored
        for name, value in values.items():
            if name == "tiktok_order_id" or value is None:
                continue
            current = getattr(existing, name)
            if name == "status":
                if value != UNKNOWN_ORDER_STATUS and (wins or _status_is_gap(current)):
                    existing.status = value
                continue
            if wins or _is_gap(name, current):
                setattr(existing, name, value)
        await self._session.flush()
        return existing

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


#: P71: product name columns where a stored blank or "Unknown" is a placeholder.
_PRODUCT_NAME_COLUMNS: frozenset[str] = frozenset({"title", "name"})


def is_placeholder_product_name(name: str | None) -> bool:
    """A missing, blank or "Unknown" product name (``services.product_name`` re-exports it)."""
    text = (name or "").strip()
    return not text or text.lower() == "unknown"


def _product_column_is_gap(name: str, current: Any) -> bool:
    if current is None:
        return True
    if name in _PRODUCT_NAME_COLUMNS:
        return is_placeholder_product_name(current)
    return False


class ProductsRepo(ShopScopedRepo[Product]):
    _model = Product
    _lookup_attrs = ("tiktok_product_id",)
    #: A status webhook creates the row with no name (P71): placeholders the poll fills.
    _insert_defaults: ClassVar[Mapping[str, Any]] = {"name": "", "status": "unknown"}

    async def _apply_if_newer(
        self, existing: Product, values: Mapping[str, Any], *, full_snapshot: bool = False
    ) -> Product:
        """Merge one product write into the stored row (P71, same rule as orders' P70).

        Two writers feed ``products``: the poll's whole product (``full_snapshot=True``)
        and PRODUCT_STATUS_CHANGE webhooks that carry only id, status and update time.

        * a snapshot wins when its ``update_time`` is at or after the stored one;
        * a webhook (partial) wins only when strictly newer;
        * a write that does not win still fills gaps: a NULL column, and a title or
          name that is blank or the "Unknown" placeholder;
        * no write replaces a real name with a placeholder or a value with ``None``.
        """
        incoming = values.get("update_time")
        stored = existing.update_time
        if incoming is None or stored is None:
            wins = True
        else:
            wins = incoming >= stored if full_snapshot else incoming > stored
        for name, value in values.items():
            if name == "tiktok_product_id" or value is None:
                continue
            current = getattr(existing, name)
            if name in _PRODUCT_NAME_COLUMNS and is_placeholder_product_name(value):
                if current is None:
                    setattr(existing, name, value)
                continue
            if wins or _product_column_is_gap(name, current):
                setattr(existing, name, value)
        await self._session.flush()
        return existing

    async def has_unnamed_products(self, shop_id: uuid.UUID) -> bool:
        """Whether a product of the shop has no real name yet -- title and name both
        blank or "Unknown" (P71: rows a status webhook created before the poll read them)."""

        def _placeholder(column: Any) -> Any:
            text = func.lower(func.trim(func.coalesce(column, "")))
            return text.in_(("", "unknown"))

        stmt = self._scoped(shop_id, _placeholder(Product.title), _placeholder(Product.name)).limit(
            1
        )
        return (await self._session.execute(stmt)).first() is not None

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

    # ``get_highest_revenue_product`` was DELETED by issue #1702 (W9-A/
    # P-SHARED-2), not merely left unreferenced. It existed for exactly one
    # caller -- ``services/agent/approval.py``'s ADR-082 decision 2 binding,
    # which chose the shop's best-selling product for a run no matter which
    # listing the approved card was about. The run's subject now comes off
    # the card (ADR-087 d.1), so the rule has no remaining meaning; leaving
    # the helper in place would let a future caller reintroduce the
    # substitution by reaching for something that looked supported.
    # ``list_by_revenue`` above still serves the ordinary "products by
    # revenue" read.


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
