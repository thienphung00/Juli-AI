"""Per-order cost data (fast track P14-C, D24.13), migration 081.

Three tenant-direct tables (each row carries ``shop_id``), filled read-only from
TikTok by ``services/order_costs/sync.py`` (run inside the poll cycle):

- ``order_price_details`` -- ``GET /order/202407/orders/{id}/price_detail``.
  One row per (shop, order, SKU), the SKU's line items summed; plus one
  ORDER-LEVEL row per order with ``tiktok_sku_id = ''`` holding the order's
  own totals (shipping deductions live there). Never sum the ``''`` row with
  the SKU rows of the same order.
- ``order_finance_transactions`` --
  ``GET /finance/202501/orders/{id}/statement_transactions``. One row per
  (shop, order, SKU, statement); plus an order-level row (``tiktok_sku_id`` and
  ``statement_id`` both ``''``) with the order's settlement totals.
- ``order_cost_fetches`` -- one row per (shop, order): what was fetched when,
  so each poll cycle fetches only what is new or changed.

Only amounts and ids are stored. The vendor payloads also carry product and SKU
names (and the order detail used to map line items to SKUs carries the buyer's
address and e-mail); none of it is kept.

Timestamps naive UTC, like ``models/run_changes.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: The order-level row's SKU id (and statement id) -- not a real SKU.
ORDER_LEVEL = ""

#: ``price_detail`` amount fields stored as columns, vendor names. The two
#: ``voucher_deduction_*`` fields and ``shipping_fee_deduction_platform_voucher``
#: are documented ambiguously (described as a "type" with enum codes, while the
#: example shows a number); they are stored as amounts but are UNVERIFIED and are
#: left out of the seller/platform-funded totals until a live read confirms them.
PRICE_AMOUNT_FIELDS: tuple[str, ...] = (
    "sku_list_price",
    "sku_sale_price",
    "subtotal",
    "subtotal_deduction_seller",
    "subtotal_deduction_platform",
    "subtotal_tax_amount",
    "voucher_deduction_seller",
    "voucher_deduction_platform",
    "shipping_list_price",
    "shipping_sale_price",
    "shipping_fee_deduction_seller",
    "shipping_fee_deduction_platform",
    "shipping_fee_deduction_platform_voucher",
    "tax_amount",
    "net_price_amount",
    "payment",
    "total",
)
PRICE_UNVERIFIED_FIELDS: frozenset[str] = frozenset(
    {
        "voucher_deduction_seller",
        "voucher_deduction_platform",
        "shipping_fee_deduction_platform_voucher",
    }
)

#: ``statement_transactions`` amounts stored as columns: the SKU (or order)
#: totals, the revenue breakdown, and the fee lines that matter for a VN
#: seller's promotion cost. Every other fee / tax / shipping line is kept, as
#: a string, in the ``fee_breakdown`` / ``shipping_breakdown`` JSON.
FINANCE_AMOUNT_FIELDS: tuple[str, ...] = (
    "revenue_amount",
    "settlement_amount",
    "fee_tax_amount",
    "shipping_cost_amount",
    "subtotal_before_discount_amount",
    "seller_discount_amount",
    "refund_subtotal_before_discount_amount",
    "seller_discount_refund_amount",
    "platform_commission_amount",
    "transaction_fee_amount",
    "affiliate_commission_amount",
    "voucher_xtra_service_fee_amount",
    "flash_sales_service_fee_amount",
    "campaign_resource_fee",
    "sfp_service_fee_amount",
    "vn_fix_infrastructure_fee",
)

_AMOUNT = Numeric(18, 2)


class OrderPriceDetail(Base):
    """One order's (``tiktok_sku_id = ''``) or one SKU's price detail."""

    __tablename__ = "order_price_details"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "tiktok_order_id", "tiktok_sku_id", name="uq_order_price_details_sku"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False, default=ORDER_LEVEL)
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    #: Line items summed into this row (TikTok has one line item per unit).
    line_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str | None] = mapped_column(String(10))
    sku_list_price: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    sku_sale_price: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    subtotal: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    subtotal_deduction_seller: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    subtotal_deduction_platform: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    subtotal_tax_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    voucher_deduction_seller: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    voucher_deduction_platform: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_list_price: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_sale_price: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_fee_deduction_seller: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_fee_deduction_platform: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_fee_deduction_platform_voucher: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    tax_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    net_price_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    payment: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    total: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    #: subtotal_deduction_seller + shipping_fee_deduction_seller (verified fields only).
    seller_funded_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)
    #: subtotal_deduction_platform + shipping_fee_deduction_platform (verified fields only).
    platform_funded_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)
    fetched_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class OrderFinanceTransaction(Base):
    """One SKU's settlement line in one statement, or the order's totals (both ids ``''``)."""

    __tablename__ = "order_finance_transactions"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "tiktok_order_id",
            "tiktok_sku_id",
            "statement_id",
            name="uq_order_finance_tx_sku_statement",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False, default=ORDER_LEVEL)
    statement_id: Mapped[str] = mapped_column(String(100), nullable=False, default=ORDER_LEVEL)
    currency: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[int | None] = mapped_column(Integer)
    revenue_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    settlement_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    fee_tax_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    shipping_cost_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    subtotal_before_discount_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    seller_discount_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    refund_subtotal_before_discount_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    seller_discount_refund_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    platform_commission_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    transaction_fee_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    affiliate_commission_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    voucher_xtra_service_fee_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    flash_sales_service_fee_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    campaign_resource_fee: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    sfp_service_fee_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    vn_fix_infrastructure_fee: Mapped[Decimal | None] = mapped_column(_AMOUNT)
    #: Every fee and tax line of the SKU, ``{"fee.<name>"|"tax.<name>": "<amount>"}``.
    fee_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: Every shipping cost line, ``{"<name>"|"supplementary_component.<name>": "<amount>"}``.
    shipping_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    order_create_time: Mapped[datetime | None] = mapped_column()
    fetched_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class OrderCostFetch(Base):
    """What was fetched for one order, so a cycle fetches only what is new."""

    __tablename__ = "order_cost_fetches"
    __table_args__ = (
        UniqueConstraint("shop_id", "tiktok_order_id", name="uq_order_cost_fetches_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The order's ``update_time`` when its price detail was read: a later
    #: ``update_time`` (refund, cancellation) makes the next cycle read it again.
    price_order_update_time: Mapped[datetime | None] = mapped_column()
    price_fetched_at: Mapped[datetime | None] = mapped_column()
    price_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finance_fetched_at: Mapped[datetime | None] = mapped_column()
    #: True once TikTok returned SKU transactions (the order has settled).
    finance_settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finance_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: The last vendor error's class and code -- never the payload.
    last_error: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
