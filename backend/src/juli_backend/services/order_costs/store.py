"""Cost-data persistence and the per-cycle work lists (fast track P14-C).

- ``orders_needing_price`` / ``orders_needing_finance`` -- which of the shop's
  orders of the last ``WINDOW_DAYS`` days a cycle should read, newest first.
- ``replace_price_rows`` / ``replace_finance_rows`` -- an order's rows are
  replaced as a set (delete + insert in one flush), so reading the same order
  twice leaves the same rows: idempotent.
- ``record_price_fetch`` / ``record_finance_fetch`` / ``record_error`` -- the
  ``order_cost_fetches`` bookkeeping.

Every function takes the caller's session and shop; nothing commits. Under
Postgres the caller holds the shop's scope, so RLS restates the ``shop_id``
filter every query here already has.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Order
from juli_backend.models.order_costs import (
    FINANCE_AMOUNT_FIELDS,
    ORDER_LEVEL,
    PRICE_AMOUNT_FIELDS,
    OrderCostFetch,
    OrderFinanceTransaction,
    OrderPriceDetail,
)
from juli_backend.services.order_costs.parse import FinanceParse, PriceParse

#: D24.13: cost data for the orders of the last 60 days.
WINDOW_DAYS = 60
#: A vendor error on one order is retried on later cycles this many times, then
#: the order is left alone (its ``last_error`` says why).
MAX_ATTEMPTS = 5
#: An order not yet settled is asked again at most this often.
FINANCE_RECHECK = timedelta(hours=24)

#: Order statuses whose price detail is worth reading (an unpaid or cancelled
#: order costs the seller nothing).
_PRICE_SKIP_STATUSES = ("UNPAID", "CANCELLED")
#: Settlement follows delivery; earlier orders have no finance transactions.
_FINANCE_STATUSES = ("DELIVERED", "COMPLETED")


@dataclass(frozen=True)
class OrderRef:
    tiktok_order_id: str
    update_time: datetime


def _window_start(now: datetime) -> datetime:
    return now - timedelta(days=WINDOW_DAYS)


def _order_created():
    return func.coalesce(Order.tiktok_created_at, Order.created_at)


async def orders_needing_price(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, limit: int
) -> list[OrderRef]:
    """Orders never read, or changed (``update_time``) since their price detail was read."""
    stmt = (
        select(Order.tiktok_order_id, Order.update_time)
        .outerjoin(
            OrderCostFetch,
            and_(
                OrderCostFetch.shop_id == Order.shop_id,
                OrderCostFetch.tiktok_order_id == Order.tiktok_order_id,
            ),
        )
        .where(
            Order.shop_id == shop_id,
            _order_created() >= _window_start(now),
            func.upper(Order.status).not_in(_PRICE_SKIP_STATUSES),
            or_(
                OrderCostFetch.id.is_(None),
                and_(
                    OrderCostFetch.price_attempts < MAX_ATTEMPTS,
                    or_(
                        OrderCostFetch.price_fetched_at.is_(None),
                        OrderCostFetch.price_order_update_time.is_(None),
                        Order.update_time > OrderCostFetch.price_order_update_time,
                    ),
                ),
            ),
        )
        .order_by(_order_created().desc(), Order.tiktok_order_id)
        .limit(limit)
    )
    return [OrderRef(r[0], r[1]) for r in (await session.execute(stmt)).all()]


async def orders_needing_finance(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, limit: int
) -> list[OrderRef]:
    """Delivered orders not yet settled and not asked within ``FINANCE_RECHECK``."""
    stmt = (
        select(Order.tiktok_order_id, Order.update_time)
        .outerjoin(
            OrderCostFetch,
            and_(
                OrderCostFetch.shop_id == Order.shop_id,
                OrderCostFetch.tiktok_order_id == Order.tiktok_order_id,
            ),
        )
        .where(
            Order.shop_id == shop_id,
            _order_created() >= _window_start(now),
            func.upper(Order.status).in_(_FINANCE_STATUSES),
            or_(
                OrderCostFetch.id.is_(None),
                and_(
                    OrderCostFetch.finance_settled.is_(False),
                    OrderCostFetch.finance_attempts < MAX_ATTEMPTS,
                    or_(
                        OrderCostFetch.finance_fetched_at.is_(None),
                        OrderCostFetch.finance_fetched_at <= now - FINANCE_RECHECK,
                    ),
                ),
            ),
        )
        .order_by(_order_created().desc(), Order.tiktok_order_id)
        .limit(limit)
    )
    return [OrderRef(r[0], r[1]) for r in (await session.execute(stmt)).all()]


async def _fetch_row(session: AsyncSession, shop_id: uuid.UUID, order_id: str) -> OrderCostFetch:
    row = (
        await session.execute(
            select(OrderCostFetch).where(
                OrderCostFetch.shop_id == shop_id, OrderCostFetch.tiktok_order_id == order_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = OrderCostFetch(
            shop_id=shop_id,
            tiktok_order_id=order_id,
            price_attempts=0,
            finance_attempts=0,
            finance_settled=False,
        )
        session.add(row)
    return row


async def replace_price_rows(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    parsed: PriceParse,
    *,
    fetched_at: datetime,
) -> int:
    """Replace the order's ``order_price_details`` rows with ``parsed``. Flush, no commit."""
    await session.execute(
        delete(OrderPriceDetail).where(
            OrderPriceDetail.shop_id == shop_id, OrderPriceDetail.tiktok_order_id == order_id
        )
    )
    for row in parsed.rows:
        session.add(
            OrderPriceDetail(
                shop_id=shop_id,
                tiktok_order_id=order_id,
                tiktok_sku_id=row.tiktok_sku_id,
                tiktok_product_id=row.tiktok_product_id,
                line_item_count=row.line_item_count,
                currency=row.currency,
                seller_funded_amount=row.seller_funded_amount,
                platform_funded_amount=row.platform_funded_amount,
                fetched_at=fetched_at,
                **{name: row.amounts.get(name) for name in PRICE_AMOUNT_FIELDS},
            )
        )
    await session.flush()
    return len(parsed.rows)


async def replace_finance_rows(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    parsed: FinanceParse,
    *,
    fetched_at: datetime,
) -> int:
    """Replace the order's ``order_finance_transactions`` rows. Flush, no commit."""
    await session.execute(
        delete(OrderFinanceTransaction).where(
            OrderFinanceTransaction.shop_id == shop_id,
            OrderFinanceTransaction.tiktok_order_id == order_id,
        )
    )
    for row in parsed.rows:
        session.add(
            OrderFinanceTransaction(
                shop_id=shop_id,
                tiktok_order_id=order_id,
                tiktok_sku_id=row.tiktok_sku_id,
                statement_id=row.statement_id,
                currency=row.currency,
                quantity=row.quantity,
                fee_breakdown=row.fee_breakdown or None,
                shipping_breakdown=row.shipping_breakdown or None,
                order_create_time=parsed.order_create_time,
                fetched_at=fetched_at,
                **{name: row.amounts.get(name) for name in FINANCE_AMOUNT_FIELDS},
            )
        )
    await session.flush()
    return len(parsed.rows)


async def record_price_fetch(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    *,
    order_update_time: datetime,
    fetched_at: datetime,
) -> None:
    row = await _fetch_row(session, shop_id, order_id)
    row.price_fetched_at = fetched_at
    row.price_order_update_time = order_update_time
    row.price_attempts = 0
    row.last_error = None
    row.updated_at = fetched_at
    await session.flush()


async def record_finance_fetch(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    *,
    settled: bool,
    fetched_at: datetime,
) -> None:
    row = await _fetch_row(session, shop_id, order_id)
    row.finance_fetched_at = fetched_at
    row.finance_settled = settled
    row.finance_attempts = 0
    row.last_error = None
    row.updated_at = fetched_at
    await session.flush()


async def record_error(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    *,
    read: str,
    error: str,
    at: datetime,
) -> None:
    """Count a failed ``read`` (``price`` | ``finance``) for the order; flush, no commit."""
    row = await _fetch_row(session, shop_id, order_id)
    if read == "price":
        row.price_attempts = (row.price_attempts or 0) + 1
    else:
        row.finance_attempts = (row.finance_attempts or 0) + 1
        row.finance_fetched_at = at
    row.last_error = f"{read}: {error}"[:200]
    row.updated_at = at
    await session.flush()


@dataclass(frozen=True)
class SkuDeductions:
    """One SKU's price-detail totals over a window (the ROI input of D24.12)."""

    tiktok_sku_id: str
    orders: int
    units: int
    sku_list_price: Decimal
    sku_sale_price: Decimal
    seller_funded_amount: Decimal
    platform_funded_amount: Decimal


async def sku_deductions(
    session: AsyncSession, shop_id: uuid.UUID, *, since: datetime
) -> dict[str, SkuDeductions]:
    """Per SKU: seller-funded vs platform-funded deductions of orders read since ``since``.

    Read-only accessor for the ranking / ROI layer; nothing calls it yet. Only
    SKU rows (never the order-level ``''`` row) are summed.
    """
    zero = Decimal(0)
    stmt = (
        select(
            OrderPriceDetail.tiktok_sku_id,
            func.count(func.distinct(OrderPriceDetail.tiktok_order_id)),
            func.coalesce(func.sum(OrderPriceDetail.line_item_count), 0),
            func.coalesce(func.sum(OrderPriceDetail.sku_list_price), zero),
            func.coalesce(func.sum(OrderPriceDetail.sku_sale_price), zero),
            func.coalesce(func.sum(OrderPriceDetail.seller_funded_amount), zero),
            func.coalesce(func.sum(OrderPriceDetail.platform_funded_amount), zero),
        )
        .where(
            OrderPriceDetail.shop_id == shop_id,
            OrderPriceDetail.tiktok_sku_id != ORDER_LEVEL,
            OrderPriceDetail.fetched_at >= since,
        )
        .group_by(OrderPriceDetail.tiktok_sku_id)
    )
    return {
        r[0]: SkuDeductions(
            tiktok_sku_id=r[0],
            orders=int(r[1]),
            units=int(r[2]),
            sku_list_price=Decimal(str(r[3])),
            sku_sale_price=Decimal(str(r[4])),
            seller_funded_amount=Decimal(str(r[5])),
            platform_funded_amount=Decimal(str(r[6])),
        )
        for r in (await session.execute(stmt)).all()
    }
