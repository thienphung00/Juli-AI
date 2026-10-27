"""Orders-derived KPIs for the sandbox shop (fast track P64, D73.3).

TikTok Analytics (A-34) answers all zeros for a sandbox shop, so its ADR-108
report showed GMV 0 / 0 đơn although real orders ARE synced into
``silver.orders`` / ``order_items``. For a shop read through its own
``sandbox_write`` credential (D73.2a) whose A-34 product-days are all zero, the
daily job builds the report's GMV, SKU orders, AOV and per-product ranking from
those synced orders instead, and marks the stored report
``metrics_source = "orders"`` so the UI says where the numbers come from.

Nothing is invented (Shopee ISV: "actual working integration"): every number is
a sum over real paid orders. The funnel stays empty -- no impression, click or
add-to-cart is derived, so CTR / CTOR stay ``None`` and every traffic channel
reads zero. A real (non-sandbox) shop never takes this path.

Paid set: an order counts once it is paid and not cancelled / returned. Stored
statuses are the ETL's canonical ones (``etl.transform._canonical_order_status``:
``confirmed`` / ``shipped`` / ``delivered``; ``pending`` = TikTok ``UNPAID``) or,
for rows written before that map, TikTok's own (``AWAITING_SHIPMENT`` ...
``COMPLETED``; ``ON_HOLD`` is paid, inside the buyer's cancel window). Compared
case-insensitively.

Per product and local (UTC+7) day of the order's TikTok create time: ``gmv`` =
sum of ``line_total``, ``sku_orders`` = distinct orders (A-34's "SKU orders"
counts an order once per product), ``items_sold`` = sum of quantities.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Order, OrderItem, Product
from juli_backend.services.shop_diagnosis.channels import Channel, read_counts
from juli_backend.services.shop_diagnosis.snapshot import Snapshot

#: The value stored on the report (``report["metrics_source"]``).
METRICS_SOURCE_ORDERS = "orders"
METRICS_SOURCE_ANALYTICS = "analytics"
#: Paid and not cancelled / returned (module doc), lower case.
PAID_ORDER_STATUSES: frozenset[str] = frozenset(
    {
        # canonical (etl.transform)
        "confirmed",
        "shipped",
        "delivered",
        # TikTok's own, for rows written before the canonical map
        "on_hold",
        "awaiting_shipment",
        "partially_shipping",
        "awaiting_collection",
        "in_transit",
        "completed",
    }
)
SHOP_UTC_OFFSET = timedelta(hours=7)


@dataclass(frozen=True)
class OrderLine:
    """One paid order line: the local day it was created, its product and amounts."""

    day: date
    order_id: str
    product_id: str
    quantity: int
    revenue: float


def _local_midnight_utc(day: date) -> datetime:
    """Midnight UTC+7 of ``day`` as the naive UTC the order columns store."""
    return datetime.combine(day, time.min) - SHOP_UTC_OFFSET


async def load_paid_order_lines(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> list[OrderLine]:
    """Paid order lines of orders created on local days ``first..last`` (inclusive).

    The caller holds the shop's scope (``with_shop_scope``); the query also
    filters on ``shop_id`` structurally.
    """
    created = func.coalesce(Order.tiktok_created_at, Order.payment_time)
    stmt = (
        select(
            created,
            Order.tiktok_order_id,
            OrderItem.tiktok_product_id,
            OrderItem.quantity,
            OrderItem.line_total,
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.shop_id == shop_id,
            OrderItem.shop_id == shop_id,
            func.lower(Order.status).in_(sorted(PAID_ORDER_STATUSES)),
            created >= _local_midnight_utc(first),
            created < _local_midnight_utc(last + timedelta(days=1)),
            OrderItem.tiktok_product_id.is_not(None),
        )
    )
    lines: list[OrderLine] = []
    for at, order_id, product_id, quantity, line_total in (await session.execute(stmt)).all():
        if at is None or not product_id:
            continue
        lines.append(
            OrderLine(
                day=(at + SHOP_UTC_OFFSET).date(),
                order_id=str(order_id),
                product_id=str(product_id),
                quantity=int(quantity or 0),
                revenue=float(line_total or 0),
            )
        )
    return lines


async def product_titles(
    session: AsyncSession, shop_id: uuid.UUID, product_ids: Iterable[str]
) -> dict[str, str]:
    """The catalog title per TikTok product id (A-34 gives none for a sandbox)."""
    wanted = sorted(set(product_ids))
    if not wanted:
        return {}
    rows = await session.execute(
        select(Product.tiktok_product_id, Product.title, Product.name).where(
            Product.shop_id == shop_id, Product.tiktok_product_id.in_(wanted)
        )
    )
    return {str(pid): str(title or name or "") for pid, title, name in rows.all()}


def analytics_all_zero(daily: Mapping[date, list[dict]]) -> bool:
    """True when no A-34 product-day carries a click, an impression, an order or GMV."""
    for rows in daily.values():
        for row in rows:
            total = read_counts(row, Channel.TOTAL)
            if total.impressions or total.clicks or total.gmv or total.sku_orders:
                return False
    return True


def daily_rows_from_orders(lines: Iterable[OrderLine]) -> dict[date, list[dict[str, Any]]]:
    """A-34-shaped ``total_performance`` rows per day, from paid order lines only.

    Only the shop-total block is filled (GMV, SKU orders, orders, items sold);
    every traffic field and every channel block is absent, so they read as zero.
    """
    gmv: dict[tuple[date, str], float] = defaultdict(float)
    items: dict[tuple[date, str], int] = defaultdict(int)
    orders: dict[tuple[date, str], set[str]] = defaultdict(set)
    for line in lines:
        key = (line.day, line.product_id)
        gmv[key] += line.revenue
        items[key] += line.quantity
        orders[key].add(line.order_id)
    out: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for (day, product_id), amount in sorted(gmv.items()):
        count = len(orders[(day, product_id)])
        out[day].append(
            {
                "id": product_id,
                "total_performance": {
                    "gmv": {"amount": f"{amount:.2f}"},
                    "sku_orders": count,
                    "orders": count,
                    "items_sold": items[(day, product_id)],
                },
            }
        )
    return dict(out)


def snapshot_from_orders(
    snapshot: Snapshot, lines: Iterable[OrderLine], titles: Mapping[str, str], days: list[date]
) -> Snapshot:
    """``snapshot`` with its daily rows replaced by the orders-derived ones.

    Every day of ``days`` is present (the orders cover the whole window: a day
    without a paid order is a real zero). Catalog titles fill products the
    snapshot has no Get Product payload for.
    """
    by_day = daily_rows_from_orders(lines)
    products = dict(snapshot.products)
    for product_id, title in titles.items():
        if title and product_id not in products:
            products[product_id] = {"id": product_id, "title": title}
    return replace(
        snapshot,
        daily={day: by_day.get(day, []) for day in days},
        products=products,
    )


__all__ = [
    "METRICS_SOURCE_ANALYTICS",
    "METRICS_SOURCE_ORDERS",
    "PAID_ORDER_STATUSES",
    "OrderLine",
    "analytics_all_zero",
    "daily_rows_from_orders",
    "load_paid_order_lines",
    "product_titles",
    "snapshot_from_orders",
]
