"""Ingest gateway and Juli Connector pairing (DECISIONS D31.3 / D31.4), migration 088.

Five tenant-direct tables (each row carries ``shop_id``; RLS by
``app_current_shop_id()``):

- ``ingest_pairing_codes`` -- a short, single-use code the seller creates on
  demo.app-juli.com (10 minutes) and types into the extension. Only its SHA-256
  is stored. The extension knows no shop yet when it redeems the code, so the
  SELECT policy also admits the one row whose ``code_hash`` equals
  ``app_current_pairing_code_hash()`` -- the redeemer sets that GUC to the hash
  of the code it was handed; a wrong code selects nothing (the same
  "asserted identity, policy narrows" shape as ``with_user_scope``).
- ``ingest_tokens`` -- the scoped ingest token the code is exchanged for: one
  shop, ingest endpoints only, stored hashed, 90-day expiry, rotating,
  revocable. The token string embeds its shop id (``jci_<shop hex>_<secret>``)
  so it is resolved under that shop's scope, never by a cross-tenant read.
- ``ingest_raw_payloads`` -- every accepted POST body as posted (append-only),
  deduplicated on ``(shop_id, content_hash)``: a re-post of the same data is a
  no-op.
- ``platform_daily_metrics`` -- THE normalized daily table diagnosis and cards
  read (D31.3): one wide row per (shop, platform, dataset, day, item, stream,
  segment, order type) with Juli's KPIs as columns, the source and its
  confidence, and every other field in ``extra``.
- ``ingest_dataset_status`` -- per (shop, platform, dataset): the last ingest
  and the extension's schema-drift report (``GET /v1/ingest/status``).

Timestamps naive UTC; ``day`` is the platform's calendar day (Shopee VN: GMT+7).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: JSONB on Postgres, plain JSON on the SQLite unit-test schema.
JSONBType = JSON().with_variant(JSONB(), "postgresql")

PLATFORM_TIKTOK = "tiktok"
PLATFORM_SHOPEE = "shopee"
PLATFORMS: tuple[str, ...] = (PLATFORM_TIKTOK, PLATFORM_SHOPEE)

SOURCE_EXTENSION = "extension"
SOURCE_FILE = "file"
SOURCE_API = "api"
SOURCE_VENDOR = "vendor"
SOURCES: tuple[str, ...] = (SOURCE_EXTENSION, SOURCE_FILE, SOURCE_API, SOURCE_VENDOR)

CONFIDENCE_HIGH = "high"
CONFIDENCE_ESTIMATED = "estimated"
#: D31.3: every source lands tagged with its confidence.
SOURCE_CONFIDENCE: dict[str, str] = {
    SOURCE_API: CONFIDENCE_HIGH,
    SOURCE_EXTENSION: CONFIDENCE_HIGH,
    SOURCE_FILE: CONFIDENCE_HIGH,
    SOURCE_VENDOR: CONFIDENCE_ESTIMATED,
}
#: A row is only overwritten by a source of the same or higher rank, so a
#: vendor estimate never replaces what the seller's own Seller Centre showed.
SOURCE_RANK: dict[str, int] = {
    SOURCE_API: 3,
    SOURCE_EXTENSION: 2,
    SOURCE_FILE: 2,
    SOURCE_VENDOR: 1,
}

ORDER_TYPE_NONE = "none"
ORDER_TYPES: tuple[str, ...] = ("placed", "paid", "confirmed")

#: ``item_id`` of a shop-level row (a NULL would defeat the unique key).
SHOP_LEVEL_ITEM = ""
SEGMENT_ALL = "all"

DRIFT_OK = "ok"
DRIFT_DRIFT = "drift"


class IngestPairingCode(Base):
    __tablename__ = "ingest_pairing_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_ingest_pairing_codes_hash"),
        Index("ix_ingest_pairing_codes_shop", "shop_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    code_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    token_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class IngestToken(Base):
    __tablename__ = "ingest_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_ingest_tokens_hash"),
        Index("ix_ingest_tokens_shop", "shop_id", "created_at"),
        CheckConstraint("platform IN ('tiktok', 'shopee')", name="ck_ingest_tokens_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    token_hash: Mapped[str] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(16))
    #: The Seller Centre shop the extension reported at pairing; later posts must match.
    platform_shop_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column()
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    #: Set when a rotation replaced this token; it keeps working for a short grace.
    superseded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IngestRawPayload(Base):
    __tablename__ = "ingest_raw_payloads"
    __table_args__ = (
        UniqueConstraint("shop_id", "content_hash", name="uq_ingest_raw_payloads_hash"),
        Index("ix_ingest_raw_payloads_dataset", "shop_id", "platform", "dataset", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    dataset: Mapped[str] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(16))
    source_version: Mapped[str] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column()
    received_at: Mapped[datetime] = mapped_column()
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    granularity: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    token_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType)


class PlatformDailyMetric(Base):
    """One normalized day: shop or item, one Juli stream, Juli's KPIs as columns."""

    __tablename__ = "platform_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "dataset",
            "day",
            "item_id",
            "stream",
            "segment",
            "order_type",
            name="uq_platform_daily_metrics_key",
        ),
        Index("ix_platform_daily_metrics_day", "shop_id", "platform", "day"),
        Index("ix_platform_daily_metrics_item", "shop_id", "platform", "item_id", "day"),
        CheckConstraint(
            "confidence IN ('high', 'estimated')", name="ck_platform_daily_metrics_confidence"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    dataset: Mapped[str] = mapped_column(String(48))
    day: Mapped[date] = mapped_column(Date)
    item_id: Mapped[str] = mapped_column(String(64), default=SHOP_LEVEL_ITEM, server_default="")
    #: Juli stream: product_card | seller_video | seller_live | affiliate | ads | total.
    stream: Mapped[str] = mapped_column(String(24))
    #: The platform's own label for the stream (e.g. ``psd_label_product_card``).
    platform_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Device split for shop traffic (all | pc | app); ``all`` elsewhere.
    segment: Mapped[str] = mapped_column(String(16), default=SEGMENT_ALL, server_default="all")
    order_type: Mapped[str] = mapped_column(
        String(16), default=ORDER_TYPE_NONE, server_default="none"
    )
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    clicks: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    #: Fractional on Shopee: a multi-item order is apportioned across its items.
    orders: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    #: Shopee "Doanh số": includes orders cancelled / returned later.
    gmv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    buyers: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    visitors: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    add_to_cart: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    page_views: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    bounce_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(16))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column()


class IngestDatasetStatus(Base):
    __tablename__ = "ingest_dataset_status"
    __table_args__ = (
        UniqueConstraint("shop_id", "platform", "dataset", name="uq_ingest_dataset_status_key"),
        CheckConstraint("drift_state IN ('ok', 'drift')", name="ck_ingest_dataset_status_drift"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    dataset: Mapped[str] = mapped_column(String(48))
    last_ingest_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_captured_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    drift_state: Mapped[str] = mapped_column(String(8), default=DRIFT_OK, server_default="ok")
    drift_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    drift_source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    drift_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column()
