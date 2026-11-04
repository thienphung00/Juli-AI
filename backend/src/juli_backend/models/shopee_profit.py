"""Shopee profit and history tables (ADR-120), migration 112.

Migration 119 (P91 D-12) adds ``shopee_order_income`` (the income export, per order) and
``shopee_order_lines.variation_name``.

Migration 113 (P90 step 2) adds order-export columns to ``shopee_order_lines`` and the two
append-only tables ``shop_health_daily`` and ``ads_change_log``.

Client lane, tenant-direct (``shop_id``, RLS by ``app_current_shop_id()``):

- ``platform_item_snapshots`` -- append-only history of an item / variation as the
  platform showed it (title, images, prices, promo, stock, rating ...). Written by the
  ingest gateway only when a tracked field changed since the latest snapshot; that
  "insert only on change" rule lives in the service, not in SQL. ``juli_app`` SELECT,
  INSERT.
- ``product_image_assets`` -- Juli's private copy of each image version, keyed by content
  hash, so the gallery history survives the platform replacing the image. SELECT, INSERT.
- ``shopee_order_lines`` -- one row per order line, PII-free by construction: there is no
  column for a buyer name, contact number or address, and ``order_ref`` is a keyed hash made in the
  browser, never the platform's order id. SELECT, INSERT, UPDATE (a status or payout
  moves as the order completes). Money is VND.
- ``shop_rule_versions`` -- append-only history of seller / team rule values; ``shop_rules``
  (models/run_changes.py) stays the CURRENT projection. See ``run_changes.ShopRuleVersion``.
- ``ad_campaign_purposes`` -- what each ad campaign is FOR (views, shop visits,
  conversion, launch). Append-only: a change of purpose is a new row, the latest
  ``set_at`` wins.

Reference (no ``shop_id``):

- ``platform_fee_formulas`` -- the platform's public fee policy, versioned by
  ``effective_from`` / ``effective_to``. ``juli_ops`` writes, ``juli_app`` may only read.
  Classified ``non_tenant`` (as ``ops_system_settings``), because the seller-side profit
  calculation reads it.

Timestamps naive UTC; dates are the platform's calendar day (Shopee VN: GMT+7).
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    desc,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

PLATFORMS: tuple[str, ...] = ("tiktok", "shopee")
#: ``variation_id`` of an item-level row (a NULL would defeat the unique key).
ITEM_LEVEL_VARIATION = ""

PROMO_KINDS: tuple[str, ...] = ("none", "voucher", "discount", "flash_sale", "bundle", "add_on")
FEE_COMPONENT_KINDS: tuple[str, ...] = ("pct", "fixed")
AD_PURPOSES: tuple[str, ...] = ("hien_thi", "luot_vao_shop", "chuyen_doi", "ra_mat")
PURPOSE_LAUNCH = "ra_mat"
SET_BY: tuple[str, ...] = ("team", "seller")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class PlatformItemSnapshot(Base):
    """One observed state of an item / variation (append-only, insert only on change)."""

    __tablename__ = "platform_item_snapshots"
    __table_args__ = (
        Index(
            "ix_platform_item_snapshots_item_time",
            "shop_id",
            "platform",
            "item_id",
            "variation_id",
            desc("captured_at"),
            unique=True,
        ),
        CheckConstraint(
            f"platform IN ({_in(PLATFORMS)})", name="ck_platform_item_snapshots_platform"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(64))
    variation_id: Mapped[str] = mapped_column(
        String(64), default=ITEM_LEVEL_VARIATION, server_default=ITEM_LEVEL_VARIATION
    )
    captured_at: Mapped[datetime] = mapped_column()
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_urls: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    #: Content hashes of the images, in gallery order; join to ``product_image_assets``.
    image_hashes: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    promo_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    promo_start: Mapped[datetime | None] = mapped_column(nullable=True)
    promo_end: Mapped[datetime | None] = mapped_column(nullable=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_path: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The date the item was created on the platform.
    created_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )


class ProductImageAsset(Base):
    """Juli's private copy of one image version, unique per shop and content hash."""

    __tablename__ = "product_image_assets"
    __table_args__ = (
        UniqueConstraint("shop_id", "image_hash", name="uq_product_image_assets_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    image_hash: Mapped[str] = mapped_column(String(128))
    storage_path: Mapped[str] = mapped_column(String(500))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column()


class ShopeeOrderLine(Base):
    """One order line. No buyer name / contact number / address column exists, by design."""

    __tablename__ = "shopee_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "platform", "order_ref", "line_no", name="uq_shopee_order_lines_key"
        ),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_shopee_order_lines_platform"),
        CheckConstraint(
            f"promo_kind IN ({_in(PROMO_KINDS)})", name="ck_shopee_order_lines_promo_kind"
        ),
        CheckConstraint("qty >= 0", name="ck_shopee_order_lines_qty"),
        Index("ix_shopee_order_lines_item_time", "shop_id", "item_id", "ordered_at"),
        Index("ix_shopee_order_lines_time", "shop_id", "ordered_at"),
        Index(
            "ix_shopee_order_lines_kol",
            "shop_id",
            "kol_key",
            "ordered_at",
            postgresql_where=text("kol_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    #: A keyed hash of the platform's order id, made in the browser. Never the raw id.
    order_ref: Mapped[str] = mapped_column(String(128))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    ordered_at: Mapped[datetime] = mapped_column()
    status: Mapped[str] = mapped_column(String(64))
    item_id: Mapped[str] = mapped_column(String(64))
    variation_id: Mapped[str] = mapped_column(
        String(64), default=ITEM_LEVEL_VARIATION, server_default=ITEM_LEVEL_VARIATION
    )
    qty: Mapped[int] = mapped_column(Integer)
    original_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    deal_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    shop_voucher_share: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal(0), server_default="0"
    )
    platform_voucher_share: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal(0), server_default="0"
    )
    bundle_discount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal(0), server_default="0"
    )
    promo_kind: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    voucher_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    traffic_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    affiliate: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    #: Fees and payout stay NULL when the export does not carry them; NULL is not zero.
    commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_fixed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_service: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_payment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_other: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    payout: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    source_version: Mapped[str] = mapped_column(String(64))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Migration 113 (order export): order-level amounts split across the order's lines by line
    # value, the seller / Shopee split of the line promotion, returns and the two settlement
    # times. ``ad_attributed`` has no source yet (G-04): NULL = unknown, never False.
    buyer_shipping_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    bank_promo: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_attributed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    seller_subsidy: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal(0), server_default="0"
    )
    shopee_subsidy: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal(0), server_default="0"
    )
    returned_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: The export names the product by SKU only; the gateway fills ``item_id`` from the
    #: catalogue when it knows the SKU (else ``item_id`` is ``sku:<sku>``).
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variation_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Migration 118 (P91 D-9): the KOL on an affiliate-marked line. ``kol_key`` is a keyed-free
    # short hash of the creator's PUBLIC account handle (never the platform's raw affiliate id);
    # ``kol_handle`` is that public handle; no buyer data.
    kol_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kol_handle: Mapped[str | None] = mapped_column(String(120), nullable=True)
    affiliate_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    affiliate_campaign_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    affiliate_mcn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Migration 119: the export's "Tên phân loại hàng" (a product's variation NAME, no buyer
    #: data). Variations that share one SKU (combos) tell apart by it; the pack count
    #: ("Combo 3 hộp") is read from it when the seller has set none.
    variation_name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ShopeeOrderIncome(Base):
    """What Shopee ACTUALLY charged and paid for one order (the income export, migration 119).

    One row per (shop, platform, ``order_ref``); ``order_ref`` is the same keyed hash as on
    ``shopee_order_lines``, so the two join on it. Every cost column is a POSITIVE amount the
    seller bore (a reversal is negative); ``payout`` is signed; ``net_shipping_cost`` is the
    shipping actually charged minus what Shopee, the buyer and PiShip paid back. NULL = the
    source did not state it (never 0). A per-order table, not columns on the lines: an income row
    exists for orders the order export may not hold, and an order's amounts are split across its
    lines by value only when the engine reads them.
    """

    __tablename__ = "shopee_order_income"
    __table_args__ = (
        UniqueConstraint("shop_id", "platform", "order_ref", name="uq_shopee_order_income_key"),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_shopee_order_income_platform"),
        Index("ix_shopee_order_income_paid", "shop_id", "paid_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    order_ref: Mapped[str] = mapped_column(String(128))
    ordered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    payout: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    product_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_fixed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    #: Phí Dịch Vụ as stated: it INCLUDES ``fee_infra`` and ``fee_voucher_xtra``.
    fee_service: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_infra: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_voucher_xtra: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_payment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_piship: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_nttd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    affiliate_commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ship_actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ship_shopee_subsidy: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ship_buyer_paid: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ship_piship_refund: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    #: A reference value of the export, not part of the payout.
    ship_seller_support: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    return_ship_refund: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    return_ship_failed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    lost_compensation: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    vat_withheld: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    pit_withheld: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    seller_voucher_borne: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    seller_coin_borne: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    trade_in_bonus_seller: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    #: A fraction, 0.06 for 6 %.
    transaction_fee_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlatformFeeFormula(Base):
    """One version of a platform's fee policy for a category (public reference data)."""

    __tablename__ = "platform_fee_formulas"
    __table_args__ = (
        UniqueConstraint(
            "platform", "category_path", "effective_from", name="uq_platform_fee_formulas_key"
        ),
        CheckConstraint(
            f"platform IN ({_in(PLATFORMS)})", name="ck_platform_fee_formulas_platform"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_platform_fee_formulas_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16))
    #: Category names from the root; ``[]`` is the platform-wide default.
    category_path: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: A list of ``{code, kind: pct|fixed, base, rate|amount, cap}``.
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONBType, default=list)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A plain staff uuid, not a foreign key into an Ops-only table (as 109).
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopHealthDaily(Base):
    """One Seller Centre account-health metric as the Connector read it (append-only: every
    capture is a row, the latest ``captured_at`` per day and metric is the reading).
    ``metric_id`` is ``''`` on the day's overview row (failed count, penalty points, rating)."""

    __tablename__ = "shop_health_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "day",
            "metric_id",
            "captured_at",
            name="uq_shop_health_daily_key",
        ),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_shop_health_daily_platform"),
        Index("ix_shop_health_daily_day", "shop_id", "platform", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    day: Mapped[date] = mapped_column(Date)
    metric_id: Mapped[str] = mapped_column(String(32), default="", server_default="")
    captured_at: Mapped[datetime] = mapped_column()
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_display: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    compare_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    metric_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_metric_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    penalty_point: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performance_rating: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    source_rank: Mapped[int] = mapped_column(SmallInteger)
    source_version: Mapped[str] = mapped_column(String(64))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AdsChangeLog(Base):
    """One line of an ad campaign's change history (``ops_log_*``): budget changes, product
    changes, Shopee's own optimiser. Append-only; a re-read of an overlapping window inserts
    nothing new (same key). Times are Seller Centre's wall clock (GMT+7), naive."""

    __tablename__ = "ads_change_log"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "platform",
            "campaign_id",
            "item_id",
            "occurred_at",
            "event_type",
            "ordinal",
            name="uq_ads_change_log_key",
        ),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_ads_change_log_platform"),
        CheckConstraint("actor_kind IN ('system', 'user')", name="ck_ads_change_log_actor_kind"),
        Index("ix_ads_change_log_time", "shop_id", "platform", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    campaign_id: Mapped[str] = mapped_column(String(32))
    #: ``''`` for a campaign-level log (a NULL would defeat the unique key).
    item_id: Mapped[str] = mapped_column(String(64), default="", server_default="")
    occurred_at: Mapped[datetime] = mapped_column()
    actor_kind: Mapped[str] = mapped_column(String(8))
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    surface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    budget_from: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    budget_to: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    products_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    products_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordinal: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(16))
    source_version: Mapped[str] = mapped_column(String(64))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_raw_payloads.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AdCampaignPurpose(Base):
    """What an ad campaign is for. Append-only: the latest ``set_at`` per campaign wins."""

    __tablename__ = "ad_campaign_purposes"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "platform", "campaign_key", "set_at", name="uq_ad_campaign_purposes_key"
        ),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_ad_campaign_purposes_platform"),
        CheckConstraint(f"purpose IN ({_in(AD_PURPOSES)})", name="ck_ad_campaign_purposes_purpose"),
        CheckConstraint(f"set_by IN ({_in(SET_BY)})", name="ck_ad_campaign_purposes_set_by"),
        CheckConstraint(
            "purpose <> 'ra_mat' OR (budget_cap_daily IS NOT NULL AND ends_on IS NOT NULL)",
            name="ck_ad_campaign_purposes_launch_capped",
        ),
        Index(
            "ix_ad_campaign_purposes_latest",
            "shop_id",
            "platform",
            "campaign_key",
            desc("set_at"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    campaign_key: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(16))
    budget_cap_daily: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    set_by: Mapped[str] = mapped_column(String(10))
    set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    set_at: Mapped[datetime] = mapped_column()


__all__ = [
    "AD_PURPOSES",
    "FEE_COMPONENT_KINDS",
    "ITEM_LEVEL_VARIATION",
    "PROMO_KINDS",
    "AdCampaignPurpose",
    "AdsChangeLog",
    "PlatformFeeFormula",
    "PlatformItemSnapshot",
    "ProductImageAsset",
    "ShopHealthDaily",
    "ShopeeOrderLine",
]
