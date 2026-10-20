"""Product history, promotions, external changes and run baselines (D30.1, D30.4), migration 087.

Five tenant-direct tables (each row carries ``shop_id``; RLS by
``app_current_shop_id()``):

- ``product_snapshots`` -- a product's content and SKU prices as TikTok showed
  them, written only when they changed since the product's latest snapshot
  (append-only). ``content_hash`` covers title, description, main images and
  attributes; ``state_hash`` adds SKU prices, status and category. One row per
  (shop, product, local day, state): the same state read twice on one day is
  stored once (replays and re-runs are idempotent), a change and its revert on
  later days are both kept (a unique ``content_hash`` alone would lose A→B→A).
- ``promotion_activities`` / ``promotion_activity_products`` -- every seller
  promotion activity Juli has seen, any status, with its per-product / per-SKU
  activity price (upserted; a product removed from an activity keeps its row
  with ``removed_at``).
- ``external_changes`` -- a change to a product (or the shop's promotions) that
  Juli observed: from a webhook (15 / 16 / 18 / 63 / 39) or the daily
  reconciliation. ``juli_write`` marks a change that matched Juli's own write
  (``run_write_values`` / a lever-flow promotion) -- not external. Append-only,
  deduplicated on ``(shop_id, dedup_key)``.
- ``run_baselines`` -- what a card's product looked like when the seller
  approved it and again when its run started: the 14-day daily pre-series per
  metric, price, active promotions, content hash, listing codes and (later, the
  algorithm's) Quality Score. One per (run, phase).

Timestamps naive UTC; ``snapshot_date`` is the shop's (UTC+7) calendar day.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: A description longer than this is kept only as its hash.
DESCRIPTION_MAX_CHARS = 10_000

KIND_CONTENT = "content"
KIND_PRICE = "price"
KIND_PROMOTION = "promotion"
KIND_CATEGORY = "category"
KIND_STATUS = "status"
KIND_CREATION = "creation"
KIND_INVENTORY = "inventory"
CHANGE_KINDS: tuple[str, ...] = (
    KIND_CONTENT,
    KIND_PRICE,
    KIND_PROMOTION,
    KIND_CATEGORY,
    KIND_STATUS,
    KIND_CREATION,
    KIND_INVENTORY,
)

SOURCE_WEBHOOK_15 = "webhook_15"
SOURCE_WEBHOOK_16 = "webhook_16"
SOURCE_WEBHOOK_18 = "webhook_18"
SOURCE_WEBHOOK_39 = "webhook_39"
SOURCE_WEBHOOK_63 = "webhook_63"
SOURCE_RECONCILE = "reconcile"
SOURCE_BASELINE = "baseline"
SOURCE_BACKFILL = "backfill"

PHASE_APPROVAL = "approval"
PHASE_EXECUTION = "execution"
BASELINE_PHASES: tuple[str, ...] = (PHASE_APPROVAL, PHASE_EXECUTION)

_KINDS_SQL = ", ".join(f"'{kind}'" for kind in CHANGE_KINDS)

#: ``external_changes.attribution`` (ADR-107 amendment §8, migration 096).
ATTRIBUTION_JULI = "juli"
ATTRIBUTION_SELLER_REVERT = "seller_revert"
ATTRIBUTION_SELLER_CHANGE = "seller_change"
ATTRIBUTION_MIXED = "mixed"
ATTRIBUTIONS: tuple[str, ...] = (
    ATTRIBUTION_JULI,
    ATTRIBUTION_SELLER_REVERT,
    ATTRIBUTION_SELLER_CHANGE,
    ATTRIBUTION_MIXED,
)
_ATTRIBUTIONS_SQL = ", ".join(f"'{label}'" for label in ATTRIBUTIONS)

#: JSONB on Postgres, plain JSON on the SQLite unit-test schema.
JSONBType = JSON().with_variant(JSONB(), "postgresql")


class ProductSnapshot(Base):
    """One product's content + SKU prices at one moment, stored only on change."""

    __tablename__ = "product_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "tiktok_product_id",
            "snapshot_date",
            "state_hash",
            name="uq_product_snapshots_day_state",
        ),
        Index("ix_product_snapshots_product_taken", "shop_id", "tiktok_product_id", "taken_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Title + description + main images + attributes.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``content_hash`` + SKU prices + status + category: what decides "changed".
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    description_hash: Mapped[str | None] = mapped_column(String(64))
    #: The description itself when it is at most ``DESCRIPTION_MAX_CHARS`` long.
    description: Mapped[str | None] = mapped_column(Text)
    #: ``[{"uri": ..., "hash": ...}]`` in TikTok's order.
    main_images: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    attributes_hash: Mapped[str | None] = mapped_column(String(64))
    #: ``[{"sku_id", "seller_sku", "list_price", "sale_price", "currency"}]`` by sku id.
    skus: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    category_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(50))
    #: TikTok's ``update_time`` (epoch seconds) of the read.
    tiktok_update_time: Mapped[int | None] = mapped_column(BigInteger)
    #: ``baseline`` / ``reconcile`` / ``webhook_15`` ...: why the product was read.
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PromotionActivity(Base):
    """One seller promotion activity (any status), upserted on every read."""

    __tablename__ = "promotion_activities"
    __table_args__ = (
        UniqueConstraint("shop_id", "activity_id", name="uq_promotion_activities_activity"),
        Index("ix_promotion_activities_shop_window", "shop_id", "begin_time", "end_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    activity_type: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str | None] = mapped_column(String(30))
    product_level: Mapped[str | None] = mapped_column(String(30))
    begin_time: Mapped[datetime | None] = mapped_column()
    end_time: Mapped[datetime | None] = mapped_column()
    tiktok_create_time: Mapped[datetime | None] = mapped_column()
    tiktok_update_time: Mapped[datetime | None] = mapped_column()
    #: When Juli first saw the activity DEACTIVATED (TikTok's update time when known).
    deactivated_at: Mapped[datetime | None] = mapped_column()
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Last time the activity's products were read (``None``: never).
    detail_fetched_at: Mapped[datetime | None] = mapped_column()


class PromotionActivityProduct(Base):
    """One product (or SKU) of an activity with its activity price / discount."""

    __tablename__ = "promotion_activity_products"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "activity_id",
            "tiktok_product_id",
            "tiktok_sku_id",
            name="uq_promotion_activity_products_sku",
        ),
        Index("ix_promotion_activity_products_product", "shop_id", "tiktok_product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    #: ``""`` for a product-level entry.
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    activity_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    added_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Set when a later read (or webhook 63's ``product_remove_list``) no longer has it.
    removed_at: Mapped[datetime | None] = mapped_column()


class ExternalChange(Base):
    """A change Juli observed on a product (or the shop's promotions)."""

    __tablename__ = "external_changes"
    __table_args__ = (
        UniqueConstraint("shop_id", "dedup_key", name="uq_external_changes_dedup"),
        Index("ix_external_changes_product_time", "shop_id", "tiktok_product_id", "occurred_at"),
        CheckConstraint(f"kind IN ({_KINDS_SQL})", name="ck_external_changes_kind"),
        CheckConstraint(
            f"attribution IS NULL OR attribution IN ({_ATTRIBUTIONS_SQL})",
            name="ck_external_changes_attribution",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    #: ``None`` for a shop-level change (a promotion covering the whole shop).
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    detected_at: Mapped[datetime] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    #: True when the change matched Juli's own write: not external.
    juli_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Before/after hashes or values; never buyer data.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: Idempotency key (snapshot id + kind, webhook notification id + product ...).
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: ADR-107 amendment §8 (migration 096, P60-1b): ``juli`` / ``seller_revert`` /
    #: ``seller_change`` when every field has that label, else ``mixed``. NULL only
    #: on a row written by pre-096 code.
    attribution: Mapped[str | None] = mapped_column(String(16))
    #: ``{field: label}`` -- the per-field labels ``attribution`` summarises.
    field_attribution: Mapped[dict[str, str] | None] = mapped_column(JSONBType)


class RunBaseline(Base):
    """A run's product baseline at approval or at execution start (D30.1c)."""

    __tablename__ = "run_baselines"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "phase", name="uq_run_baselines_run_phase"),
        CheckConstraint("phase IN ('approval', 'execution')", name="ck_run_baselines_phase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    action_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_cards.id"))
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(nullable=False)
    #: ``{"days": [...14 ISO dates], "series": {metric: [value | null, ...]}}``.
    metrics_pre: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: ``{"skus": [...], "min_list_price", "min_sale_price", "currency", "source"}``.
    price: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    active_promotions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    listing_codes: Mapped[list[Any] | None] = mapped_column(JSON)
    #: Filled later by the Quality Score algorithm (D30.2); ``None`` until then.
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
