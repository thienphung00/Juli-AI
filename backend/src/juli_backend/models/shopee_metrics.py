"""Materialized Shopee metrics and the frozen plan base (P97 D85.2 / D85.4, migration 123).

Three tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``; ``juli_app`` SELECT,
INSERT, UPDATE -- rows are rebuilt by upsert, never deleted):

- ``shopee_shop_metrics_daily`` -- one row per (shop, GMT+7 day, order type): the headline GMV /
  đơn / AOV, the funnel, ads, profit, with a source tag per column and a ``complete`` flag (the
  day's shop totals came from Shopee's own daily numbers, not from order lines standing in).
- ``shopee_product_metrics_daily`` -- the day's product rows: order lines scaled to the shop row.
  The product rows of a day, plus the ``__residual__`` row, add up to the shop row; the residual
  (the part of the shop GMV no order line explains) is stored, never hidden.
- ``shopee_plan_base_snapshots`` -- the base a draft plan was evaluated on (``as_of`` and the
  aggregates the plan math shows), versioned: "Cập nhật số" writes the next version, the highest
  version is the active one.

Written by ``services/shopee_analytics/materialize`` from the raw tables after each ingest write
and by the backfill CLI (``scripts/backfill_shopee_metrics.py``). Money is VND.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

ORDER_TYPES: tuple[str, ...] = ("placed", "paid", "confirmed")
SOURCES: tuple[str, ...] = ("shop_totals", "order_lines", "connector", "file")
RESIDUAL_ITEM = "__residual__"
_MONEY = Numeric(18, 2)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopeeShopMetricsDaily(Base):
    __tablename__ = "shopee_shop_metrics_daily"
    __table_args__ = (
        UniqueConstraint("shop_id", "day", "order_type", name="uq_shopee_shop_metrics_daily"),
        CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})", name="ck_shopee_shop_metrics_daily_order_type"
        ),
        Index("ix_shopee_shop_metrics_daily_complete", "shop_id", "complete", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    order_type: Mapped[str] = mapped_column(String(12))
    gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aov: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: page views (pv); ``visitors`` (uv) stays NULL until a reader supplies it
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visitors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: margin numerator / denominator (covered lines): Σ margin_profit ÷ Σ buyer_paid_known
    margin_profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    buyer_paid_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs_coverage: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    line_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    line_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: column -> shop_totals | order_lines | connector | file
    sources: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: figures the screens need that are not columns: the Seller Centre AOV numerator, the
    #: partial-profit flag
    detail: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    built_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopeeProductMetricsDaily(Base):
    __tablename__ = "shopee_product_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "day", "order_type", "item_id", name="uq_shopee_product_metrics_daily"
        ),
        CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})",
            name="ck_shopee_product_metrics_daily_order_type",
        ),
        Index("ix_shopee_product_metrics_daily_item", "shop_id", "item_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    order_type: Mapped[str] = mapped_column(String(12))
    item_id: Mapped[str] = mapped_column(String(64))
    #: NULL = the item's row (variation rows are not materialized yet)
    variation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gmv: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal(0))
    orders: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    line_gmv: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal(0))
    line_orders: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16))
    scaled_to_totals: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    built_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopeePlanBaseSnapshot(Base):
    __tablename__ = "shopee_plan_base_snapshots"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_shopee_plan_base_snapshots_version"),
        Index("ix_shopee_plan_base_snapshots_shop", "shop_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_reco_plans.id"))
    #: 1, 2, ... ("Cập nhật số" adds the next); the highest is the active snapshot
    version: Mapped[int] = mapped_column(Integer, default=1)
    as_of: Mapped[date] = mapped_column(Date)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    base: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_by: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
