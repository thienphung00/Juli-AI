"""Materialized Shopee metrics and the frozen plan base (P97 D85.2 / D85.4, migration 123).

Migration 134 (T5) gives the three daily tables platform-neutral names (``shop_metrics_daily``,
``product_metrics_daily``, ``source_metrics_daily``; the ``shopee_*`` names stay as views for one
release) and ``built_at`` becomes ``timestamptz``.

Three tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``; ``juli_app`` SELECT,
INSERT, UPDATE -- rows are rebuilt by upsert, never deleted):

- ``shop_metrics_daily`` -- one row per (shop, GMT+7 day, order type): the headline GMV /
  đơn / AOV, the funnel, ads, profit, with a source tag per column and a ``complete`` flag (the
  day's shop totals came from Shopee's own daily numbers, not from order lines standing in).
- ``product_metrics_daily`` -- the day's product rows: order lines scaled to the shop row.
  The product rows of a day, plus the ``__residual__`` row, add up to the shop row; the residual
  (the part of the shop GMV no order line explains) is stored, never hidden.
- ``shopee_plan_base_snapshots`` -- the base a draft plan was evaluated on (``as_of`` and the
  aggregates the plan math shows), versioned: "Cập nhật số" writes the next version, the highest
  version is the active one.
- ``source_metrics_daily`` (P98 / ADR-122 d.3, migration 126) -- the funnel per traffic
  source: one row per (shop, day, item or NULL = the shop, source). Lượt xem / lượt nhấp from the
  traffic tables; đơn / GMV / lợi nhuận are ShopMetrics allocated over the sources, so the six
  sources of a scope add up to its shop (or product) row exactly; ``chenh_lech_nguon`` holds what
  Shopee does not assign. ``ads_*`` is the "trong đó Quảng cáo" share of ``the_san_pham_khac``.

Migration 140 (data layer, decision #62/#66) adds the registry components every screen, export
and Chat reads as additive numeric columns (ids = ``services/metrics/components.py``; NULL =
missing, never 0) and ``derivation_version`` on every row; ratios are never stored, they are
evaluated at read time from summed components. ``campaign_metrics_daily``: one row per (shop,
day, campaign) from the Connector's ``ads_campaign_daily`` (only days with spend or GMV).

Written by ``services/shopee_analytics/materialize`` from the raw tables after each ingest write
and by the triggered backfill (``backfill_shop``). Money is VND.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.models.shopee_profit import UTC_TIME
from juli_backend.orm_base import Base

ORDER_TYPES: tuple[str, ...] = ("placed", "paid", "confirmed")
SOURCES: tuple[str, ...] = ("shop_totals", "order_lines", "connector", "file")
RESIDUAL_ITEM = "__residual__"
#: ADR-122 d.3 source keys, as ``shopee_builder.engine.contract.SOURCES`` (checked by a test)
FUNNEL_SOURCES: tuple[str, ...] = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
    "chenh_lech_nguon",
)
_MONEY = Numeric(18, 2)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopeeShopMetricsDaily(Base):
    __tablename__ = "shop_metrics_daily"
    __table_args__ = (
        UniqueConstraint("shop_id", "day", "order_type", name="uq_shop_metrics_daily"),
        CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})", name="ck_shop_metrics_daily_order_type"
        ),
        Index("ix_shop_metrics_daily_complete", "shop_id", "complete", "day"),
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
    #: migration 140: the registry components of the day (``metrics/components.py`` ids)
    net_revenue: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    net_revenue_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs_known_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    packaging: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    shipping_net: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_promo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_voucher: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_combo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_commission: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    other_marketing: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: A2 (contract §6): the AFF / ads cost of the covered orders (registry ``KNOWN_SHARE_RULE``)
    affiliate_commission_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_spend_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: the ads funnel components (registry ids); NULL = the report has none that day
    ads_gmv_direct: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_gmv_confirmed: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    derivation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: column -> shop_totals | order_lines | connector | file
    sources: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    #: figures the screens need that are not columns: the Seller Centre AOV numerator, the
    #: partial-profit flag
    detail: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


class ShopeeProductMetricsDaily(Base):
    __tablename__ = "product_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "day", "order_type", "item_id", name="uq_product_metrics_daily"
        ),
        CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})",
            name="ck_product_metrics_daily_order_type",
        ),
        Index("ix_product_metrics_daily_item", "shop_id", "item_id", "day"),
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
    #: migration 140: the registry components of the day (``metrics/components.py`` ids)
    net_revenue: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    net_revenue_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs_known_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    packaging: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    shipping_net: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_promo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_voucher: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_combo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_commission: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: the ads-by-product GMV of the day, each campaign-day counted once (A6)
    ads_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: A2 (contract §6): the AFF / ads cost of the covered orders (registry ``KNOWN_SHARE_RULE``)
    affiliate_commission_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_spend_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: the ads funnel components (registry ids); NULL = the report has none that day
    ads_gmv_direct: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_gmv_confirmed: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    derivation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    scaled_to_totals: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


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


class ShopeeSourceMetricsDaily(Base):
    """One source of one scope on one day (ADR-122 d.3). ``item_id`` NULL = the shop row; the
    natural key is (shop, day, item, source), enforced by two partial unique indexes because a
    NULL never collides in a plain unique constraint."""

    __tablename__ = "source_metrics_daily"
    __table_args__ = (
        CheckConstraint(
            f"source IN ({_in(FUNNEL_SOURCES)})", name="ck_source_metrics_daily_source"
        ),
        Index(
            "uq_source_metrics_daily_shop",
            "shop_id",
            "day",
            "source",
            unique=True,
            postgresql_where=text("item_id IS NULL"),
            sqlite_where=text("item_id IS NULL"),
        ),
        Index(
            "uq_source_metrics_daily_item",
            "shop_id",
            "day",
            "item_id",
            "source",
            unique=True,
            postgresql_where=text("item_id IS NOT NULL"),
            sqlite_where=text("item_id IS NOT NULL"),
        ),
        Index("ix_source_metrics_daily_item", "shop_id", "item_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    #: NULL = the shop's row
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(24))
    #: NULL = the traffic tables have no rows for this source ("chưa có dữ liệu")
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    gmv: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal(0))
    #: NULL = a giá vốn is missing ("chưa tính")
    profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ads_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: the traffic tables' own đơn / GMV for this source were scaled to the ShopMetrics totals
    scaled_to_totals: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    derivation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


CHANNELS: tuple[str, ...] = ("organic", "ads", "affiliate")
#: A9: bought with / without a shop discount; ``unknown`` = GMV no order line explains
DISCOUNTED: tuple[str, ...] = ("with", "without", "unknown")


class ProductChannelMetricsDaily(Base):
    """One product, one day, one channel, one discount state (migration 140, F2 / A7 / A9).

    Organic / Quảng cáo / TTLK x bought with / without a shop discount; the cells of a product
    day add up to its ``product_metrics_daily`` row exactly (GMV, đơn once per order, every line
    component). TTLK first (the order-line affiliate flag), Quảng cáo capped at what it leaves
    (``capped_gmv`` records a cap that bites), Organic the rest. Sparse: no row for an empty
    cell."""

    __tablename__ = "product_channel_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "day",
            "item_id",
            "channel",
            "discounted",
            name="uq_product_channel_metrics_daily",
        ),
        CheckConstraint(
            f"channel IN ({_in(CHANNELS)})", name="ck_product_channel_metrics_daily_channel"
        ),
        CheckConstraint(
            f"discounted IN ({_in(DISCOUNTED)})",
            name="ck_product_channel_metrics_daily_discounted",
        ),
        Index("ix_product_channel_metrics_daily_item", "shop_id", "item_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    item_id: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(12))
    discounted: Mapped[str] = mapped_column(String(8))
    gmv: Mapped[Decimal] = mapped_column(_MONEY)
    orders: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer, default=0)
    net_revenue: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    net_revenue_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs_known_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    packaging: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    shipping_net: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_promo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_voucher: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_combo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_commission: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: A7: what the channel's source said beyond the cap (on the ``without`` cell)
    capped_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    derivation_version: Mapped[str] = mapped_column(String(32))
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


class ShopChannelMetricsDaily(Base):
    """The shop's day per channel and discount state (migration 140, contract §6): the shop's own
    đơn, counted once per order (B1: an order is TTLK when any of its lines is), so the cells add
    up to the ``shop_metrics_daily`` row; product đơn are never summed into it. Same rule as
    :class:`ProductChannelMetricsDaily` over all the shop's lines."""

    __tablename__ = "shop_channel_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "day",
            "channel",
            "discounted",
            name="uq_shop_channel_metrics_daily",
        ),
        CheckConstraint(
            f"channel IN ({_in(CHANNELS)})", name="ck_shop_channel_metrics_daily_channel"
        ),
        CheckConstraint(
            f"discounted IN ({_in(DISCOUNTED)})",
            name="ck_shop_channel_metrics_daily_discounted",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(12))
    discounted: Mapped[str] = mapped_column(String(8))
    gmv: Mapped[Decimal] = mapped_column(_MONEY)
    orders: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer, default=0)
    net_revenue: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    net_revenue_known: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    cogs_known_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    packaging: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    shipping_net: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_promo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_voucher: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    offer_combo: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    affiliate_commission: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    ads_spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: A7: what the channel's source said beyond the cap (on the ``without`` cell)
    capped_gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    derivation_version: Mapped[str] = mapped_column(String(32))
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


class ShopFactsStatus(Base):
    """Is a shop's stored daily facts layer current (migration 140, deploy plan #74)?

    One row per shop, written by the triggered facts backfill and the rebuilds: the
    ``derivation_version`` the shop's days were last brought to, ``complete`` when no stored or
    data day is older than it, else ``ready_from`` = the first day from which every day is current
    (the backfill goes newest first, so a 90-day window is ready before the older days are).
    Readers (``facts.query``) use stored rows only when :func:`materialize.facts_ready` says so."""

    __tablename__ = "shop_facts_status"
    __table_args__ = (UniqueConstraint("shop_id", name="uq_shop_facts_status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    derivation_version: Mapped[str] = mapped_column(String(32))
    complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: NULL = no day is current yet
    ready_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: days still to rebuild at the last check
    pending_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: when the status last changed
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


class CampaignMetricsDaily(Base):
    """One ads campaign on one day (migration 140, F3): the Connector's ``ads_campaign_daily``
    row, stored only when it spent or sold. A day before the shop's first campaign row has no
    row (missing, never 0). ``contribution_products`` (its products' contribution) is not
    additive across campaigns: two campaigns can advertise one product (registry
    ``sums_across``)."""

    __tablename__ = "campaign_metrics_daily"
    __table_args__ = (
        UniqueConstraint("shop_id", "day", "campaign_id", name="uq_campaign_metrics_daily"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    day: Mapped[date] = mapped_column(Date)
    #: the Connector's campaign key (segment hash)
    campaign_id: Mapped[str] = mapped_column(String(64))
    ad_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    spend: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    gmv: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    gmv_direct: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orders_direct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contribution_products: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: the campaign's daily budget that day (``ads_campaign_daily`` extra); NULL = not read
    daily_budget: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    derivation_version: Mapped[str] = mapped_column(String(32))
    built_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())
