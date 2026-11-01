"""The public Shopee market lane (ADR-116 §1, ADR-117 §5), migration 108.

Public search pages are not any client's data: no ``shop_id``, shared, allowed in shared
models. Both tables are Ops-only (``juli_ops``; ``juli_app`` has no grant) until a
seller-facing reader exists.

- ``market_listing_snapshots`` -- one row per search card seen (keyword x sort x page x
  position x collection time). ``page`` / ``pos`` are provenance only, never a model
  feature (D61.9). The platform's shop id is ``platform_shop_id`` so the tenant sweep
  never reads it as Juli's ``shop_id``.
- ``market_keyword_snapshots`` -- one row per keyword x sort x collection day.

Frozen test sets (``ml_guard``) are never loaded here. Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base


class MarketListingSnapshot(Base):
    __tablename__ = "market_listing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "keyword",
            "sort",
            "page",
            "pos",
            "collected_at",
            name="uq_market_listing_snapshots_card",
        ),
        CheckConstraint(
            "platform IN ('tiktok', 'shopee')", name="ck_market_listing_snapshots_platform"
        ),
        Index("ix_market_listing_snapshots_item", "platform", "platform_item_id", "collected_at"),
        Index("ix_market_listing_snapshots_shop", "platform", "platform_shop_id", "collected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16))
    keyword: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort: Mapped[str] = mapped_column(String(16))
    page: Mapped[int] = mapped_column(SmallInteger)
    pos: Mapped[int] = mapped_column(SmallInteger)
    collected_at: Mapped[datetime] = mapped_column()
    platform_item_id: Mapped[str] = mapped_column(String(32))
    platform_shop_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    #: The card's own "đã bán" text, kept so a parser change can be replayed.
    sold_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sold_monthly: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    sold_lifetime: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    collector: Mapped[str] = mapped_column(String(64))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MarketKeywordSnapshot(Base):
    __tablename__ = "market_keyword_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "platform", "keyword", "sort", "collected_on", name="uq_market_keyword_snapshots_key"
        ),
        CheckConstraint(
            "platform IN ('tiktok', 'shopee')", name="ck_market_keyword_snapshots_platform"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16))
    keyword: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort: Mapped[str] = mapped_column(String(16))
    collected_on: Mapped[date] = mapped_column(Date)
    pages: Mapped[int] = mapped_column(SmallInteger)
    n_cards: Mapped[int] = mapped_column(Integer)
    n_shops: Mapped[int] = mapped_column(Integer)
    median_price_page1: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    share_discounted: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    sold_monthly_median: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    sold_monthly_p75: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
