"""Client-lane platform data beside ``platform_daily_metrics`` (ADR-117), migration 108.

Four tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``; ``juli_app``
SELECT, INSERT, UPDATE), written by the ingest gateway path only:

- ``platform_period_metrics`` -- totals over a period (one day .. one month) per item x
  variation x stream x segment x order type: Seller Centre's ``parentskudetail`` and the
  monthly source files. A period is never written as a fake day in
  ``platform_daily_metrics``, where a reader summing by day would count it twice.
- ``platform_items`` -- the platform's items and variations (``variation_id = ''`` is the
  item itself). ``products`` stays TikTok-shaped: its ``tiktok_product_id`` is NOT NULL.
- ``platform_product_flags`` -- Shopee's per-item flags for a period.
- ``platform_promotions`` -- one row per promotion program x order type. Shopee exports no
  program id, so the program's name is part of the key.

Every row records where it came from like 088's (``source``, ``source_rank``,
``source_version``, ``raw_payload_id``) plus ``mapper_version``. Timestamps naive UTC;
dates are the platform's calendar day (Shopee VN: GMT+7).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import (
    ORDER_TYPE_NONE,
    SEGMENT_ALL,
    SHOP_LEVEL_ITEM,
    JSONBType,
)
from juli_backend.orm_base import Base

#: ``variation_id`` of an item-level row (a NULL would defeat the unique key).
ITEM_LEVEL_VARIATION = ""

FLAG_NEW_PRODUCT = "new_product"
FLAG_PRICE_COMPETITIVE = "price_competitive"
FLAG_PRICE_UNCOMPETITIVE = "price_uncompetitive"
FLAG_ADS_GROW = "ads_grow"
FLAG_ADS_OPTIMIZE = "ads_optimize"
FLAG_ADS_TRACK = "ads_track"
#: The ``parentskudetail`` sheets that are flags, in the export's order.
PRODUCT_FLAGS: tuple[str, ...] = (
    FLAG_NEW_PRODUCT,
    FLAG_PRICE_COMPETITIVE,
    FLAG_PRICE_UNCOMPETITIVE,
    FLAG_ADS_GROW,
    FLAG_ADS_OPTIMIZE,
    FLAG_ADS_TRACK,
)


class PlatformPeriodMetric(Base):
    """One period total: shop or item (or variation), one stream, Juli's KPIs as columns."""

    __tablename__ = "platform_period_metrics"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "dataset",
            "period_start",
            "period_end",
            "item_id",
            "variation_id",
            "stream",
            "segment",
            "order_type",
            name="uq_platform_period_metrics_key",
        ),
        CheckConstraint("period_end >= period_start", name="ck_platform_period_metrics_period"),
        CheckConstraint(
            "confidence IN ('high', 'estimated')", name="ck_platform_period_metrics_confidence"
        ),
        Index("ix_platform_period_metrics_item", "shop_id", "platform", "item_id", "period_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    dataset: Mapped[str] = mapped_column(String(48))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    item_id: Mapped[str] = mapped_column(
        String(64), default=SHOP_LEVEL_ITEM, server_default=SHOP_LEVEL_ITEM
    )
    variation_id: Mapped[str] = mapped_column(
        String(64), default=ITEM_LEVEL_VARIATION, server_default=ITEM_LEVEL_VARIATION
    )
    stream: Mapped[str] = mapped_column(String(24))
    platform_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    segment: Mapped[str] = mapped_column(String(16), default=SEGMENT_ALL, server_default="all")
    order_type: Mapped[str] = mapped_column(
        String(16), default=ORDER_TYPE_NONE, server_default="none"
    )
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    clicks: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    orders: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    gmv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    buyers: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    visitors: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    add_to_cart: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    page_views: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    bounce_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    confidence: Mapped[str] = mapped_column(String(16))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    mapper_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column()


class PlatformItem(Base):
    """One platform item or variation as the seller's own export names it."""

    __tablename__ = "platform_items"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "platform", "item_id", "variation_id", name="uq_platform_items_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(64))
    variation_id: Mapped[str] = mapped_column(
        String(64), default=ITEM_LEVEL_VARIATION, server_default=ITEM_LEVEL_VARIATION
    )
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    variation_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_seen_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    mapper_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column()


class PlatformProductFlag(Base):
    """An item the platform placed in one of its flag lists for a period."""

    __tablename__ = "platform_product_flags"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "item_id",
            "period_start",
            "period_end",
            "flag",
            name="uq_platform_product_flags_key",
        ),
        CheckConstraint(
            "flag IN ('new_product', 'price_competitive', 'price_uncompetitive', "
            "'ads_grow', 'ads_optimize', 'ads_track')",
            name="ck_platform_product_flags_flag",
        ),
        CheckConstraint("period_end >= period_start", name="ck_platform_product_flags_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    flag: Mapped[str] = mapped_column(String(32))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    mapper_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column()


class PlatformPromotion(Base):
    """One promotion program's results for one order type."""

    __tablename__ = "platform_promotions"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "promo_type",
            "program_name",
            "starts_on",
            "order_type",
            name="uq_platform_promotions_key",
        ),
        Index("ix_platform_promotions_dates", "shop_id", "platform", "starts_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    promo_type: Mapped[str] = mapped_column(String(32))
    #: The seller's own program name (listing text, not buyer text; ADR-117 §3).
    program_name: Mapped[str] = mapped_column(String(255))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_type: Mapped[str] = mapped_column(String(16))
    gmv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    orders: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    buyers: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    mapper_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column()
