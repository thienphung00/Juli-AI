import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from juli_backend.orm_base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    shops: Mapped[list["Shop"]] = relationship(back_populates="owner")


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tiktok_shop_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="shops")
    credentials: Mapped[list["TikTokCredential"]] = relationship(back_populates="shop")

    __table_args__ = (Index("ix_shops_user_id", "user_id"),)


class TikTokCredential(Base):
    """TikTok OAuth credential row for a shop/merchant capability.

    ``status``/``last_refreshed_at``/``last_refresh_error``/``refresh_count``/
    ``refresh_token_expires_at`` (ADR-081 decision 7, migration 038) are
    persistence only in this slice -- the scan predicate, fail-closed
    resolver and the three refresh layers that read/write them land in
    #1231/#1232. ``status`` is a plain varchar (``active`` | ``needs_reauth``)
    checked in application code, mirroring ``workflow_runs.status`` -- no
    native DB enum. ``refresh_token_expires_at`` is populated only if a
    vendor response ever carries ``refresh_token_expire_in``; nothing may
    assume it is non-null.
    """

    __tablename__ = "tiktok_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    merchant_authorization_id: Mapped[str | None] = mapped_column(String(100))
    capability: Mapped[str | None] = mapped_column(String(50))
    shop_cipher: Mapped[str | None] = mapped_column(String(200))
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    shop: Mapped["Shop"] = relationship(back_populates="credentials")

    __table_args__ = (
        Index("ix_tiktok_credentials_shop_id", "shop_id"),
        Index(
            "ix_tiktok_credentials_merchant_capability",
            "merchant_authorization_id",
            "capability",
        ),
    )


class TikTokSyncState(Base):
    """Per-endpoint incremental sync cursor for Fujiwa production polling."""

    __tablename__ = "tiktok_sync_state"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(50), nullable=False)
    last_update_time: Mapped[int] = mapped_column(nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_tiktok_sync_state_shop_endpoint",
            "shop_id",
            "endpoint",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# Commerce models (#28)
# ---------------------------------------------------------------------------


class Order(Base):
    """Silver domain order — idempotent upsert SoT (#607)."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    buyer_id: Mapped[str | None] = mapped_column(String(100))
    order_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_time: Mapped[datetime | None] = mapped_column()
    ship_time: Mapped[datetime | None] = mapped_column()
    delivery_time: Mapped[datetime | None] = mapped_column()
    tiktok_created_at: Mapped[datetime | None] = mapped_column()
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    is_seller_fault: Mapped[bool | None] = mapped_column(Boolean())
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    line_items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    returns: Mapped[list["Return"]] = relationship(back_populates="order")

    __table_args__ = (
        Index("ix_silver_orders_shop_created", "shop_id", "created_at"),
        UniqueConstraint(
            "shop_id",
            "tiktok_order_id",
            name="uq_silver_orders_shop_tiktok",
        ),
        {"schema": "silver"},
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("silver.orders.id"),
        nullable=False,
    )
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    order: Mapped["Order"] = relationship(back_populates="line_items")

    __table_args__ = (
        Index("ix_order_items_shop_order", "shop_id", "order_id"),
        Index(
            "ix_order_items_shop_order_sku",
            "shop_id",
            "tiktok_order_id",
            "tiktok_sku_id",
            unique=True,
        ),
    )


class Return(Base):
    """Silver domain return/cancellation — idempotent upsert SoT (#607)."""

    __tablename__ = "returns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("silver.orders.id"))
    tiktok_return_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    buyer_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_sku_id: Mapped[str | None] = mapped_column(String(100))
    return_type: Mapped[str] = mapped_column(String(30), nullable=False)
    return_condition: Mapped[str] = mapped_column(
        String(30), default="unknown", server_default="unknown", nullable=False
    )
    return_reason: Mapped[str | None] = mapped_column(String(500))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    order: Mapped["Order | None"] = relationship(back_populates="returns")

    __table_args__ = (
        Index("ix_silver_returns_shop_created", "shop_id", "created_at"),
        UniqueConstraint(
            "shop_id",
            "tiktok_return_id",
            name="uq_silver_returns_shop_tiktok",
        ),
        {"schema": "silver"},
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price_currency: Mapped[str | None] = mapped_column(String(10))
    inventory: Mapped[int | None] = mapped_column()
    audit_status: Mapped[str | None] = mapped_column(String(30))
    tiktok_created_at: Mapped[datetime | None] = mapped_column()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    units_sold: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_products_shop_created", "shop_id", "created_at"),
        Index("ix_products_shop_tiktok", "shop_id", "tiktok_product_id", unique=True),
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    warehouse_id: Mapped[str | None] = mapped_column(String(100))
    velocity: Mapped[str] = mapped_column(
        String(20), default="low", server_default="low", nullable=False
    )
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_inventory_shop_created", "shop_id", "created_at"),
        Index(
            "ix_inventory_shop_sku",
            "shop_id",
            "tiktok_sku_id",
            unique=True,
        ),
    )


class Settlement(Base):
    """Settlement values stay pending 7-14 days before confirming.
    ``update_time`` is the reconciliation key (not insertion order).
    """

    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_settlement_id: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    platform_commission: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    affiliate_commission: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    settlement_time: Mapped[datetime | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_settlements_shop_created", "shop_id", "created_at"),
        Index(
            "ix_settlements_shop_tiktok",
            "shop_id",
            "tiktok_settlement_id",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# Analytics models (#28)
# ---------------------------------------------------------------------------


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_creator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    follower_count: Mapped[int | None] = mapped_column()
    total_gmv: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False
    )
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    update_time: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    livestreams: Mapped[list["Livestream"]] = relationship(back_populates="creator")

    __table_args__ = (
        Index(
            "ix_creators_shop_tiktok",
            "shop_id",
            "tiktok_creator_id",
            unique=True,
        ),
    )


class Livestream(Base):
    __tablename__ = "livestreams"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_livestream_id: Mapped[str] = mapped_column(String(100), nullable=False)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("creators.id"))
    title: Mapped[str | None] = mapped_column(String(500))
    start_time: Mapped[datetime | None] = mapped_column()
    end_time: Mapped[datetime | None] = mapped_column()
    viewer_count: Mapped[int | None] = mapped_column()
    peak_concurrent_viewers: Mapped[int | None] = mapped_column()
    click_count: Mapped[int | None] = mapped_column()
    order_count: Mapped[int | None] = mapped_column()
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    update_time: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    creator: Mapped["Creator | None"] = relationship(back_populates="livestreams")

    __table_args__ = (
        Index(
            "ix_livestreams_shop_tiktok",
            "shop_id",
            "tiktok_livestream_id",
            unique=True,
        ),
    )


class AnalyticsPerformanceInterval(Base):
    """Daily/hourly analytics performance snapshot from Partner API polls (#425)."""

    __tablename__ = "analytics_performance_intervals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    snapshot_key: Mapped[str] = mapped_column(String(300), nullable=False)
    grain: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    hour_index: Mapped[int | None] = mapped_column()
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_sku_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_live_id: Mapped[str | None] = mapped_column(String(100))
    gmv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gmv_currency: Mapped[str | None] = mapped_column(String(10))
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    click_through_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    click_order_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    click_to_order_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sku_orders: Mapped[int | None] = mapped_column()
    items_sold: Mapped[int | None] = mapped_column()
    orders_count: Mapped[int | None] = mapped_column()
    customers: Mapped[int | None] = mapped_column()
    visitors: Mapped[int | None] = mapped_column()
    impressions: Mapped[int | None] = mapped_column()
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    live_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    live_sessions: Mapped[int | None] = mapped_column()
    active_products: Mapped[int | None] = mapped_column()
    new_products: Mapped[int | None] = mapped_column()
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_analytics_perf_shop_snapshot",
            "shop_id",
            "snapshot_key",
            unique=True,
        ),
        Index(
            "ix_analytics_perf_shop_grain_date",
            "shop_id",
            "grain",
            "start_date",
        ),
    )


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    threshold_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    history: Mapped[list["AlertHistory"]] = relationship(back_populates="alert_config")

    __table_args__ = (
        Index("ix_alert_configs_shop", "shop_id"),
        Index("ix_alert_configs_shop_type", "shop_id", "alert_type", unique=True),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    alert_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_configs.id"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(nullable=False)
    payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    alert_config: Mapped["AlertConfig"] = relationship(back_populates="history")

    __table_args__ = (
        Index("ix_alert_history_shop", "shop_id"),
        Index("ix_alert_history_config", "alert_config_id"),
    )


class WorkflowWebhookSignal(Base):
    """Durable workflow-intent record emitted by Phase 2 catalog webhooks (#354)."""

    __tablename__ = "workflow_webhook_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_shop_id: Mapped[str] = mapped_column(String(100), nullable=False)
    catalog_id: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_keys: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_workflow_webhook_signals_shop", "shop_id"),
        Index("ix_workflow_webhook_signals_catalog", "catalog_id"),
    )


class WebhookRawEvent(Base):
    """Redacted TikTok webhook delivery archive for audit/replay (#392).

    ``tiktok_shop_id`` is intentionally not an FK — unknown/unresolvable shops
    must still insert (that is the point of this table).
    """

    __tablename__ = "webhook_raw_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    tiktok_shop_id: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str | None] = mapped_column(String(100))
    event_id: Mapped[str | None] = mapped_column(String(255))
    signature_header: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[str | None] = mapped_column(Text)
    raw_body: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int] = mapped_column(nullable=False)
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False)
    parse_version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        Index("ix_webhook_raw_events_received_at", "received_at"),
        Index("ix_webhook_raw_events_tiktok_shop_id", "tiktok_shop_id"),
        Index("ix_webhook_raw_events_event_type", "event_type"),
    )


class WorkflowRun(Base):
    """Agent execution-loop run record — WorkflowRunner's persisted run, P1
    (ADR-073 decisions 1, 2 and 4; #1117 / AGT-W3A).

    ``state`` is the JSONB blob that stands in for the deferred P-CS chat
    store (conversation window, iteration count, pending confirmation, basis
    snapshots — ADR-073 decision 1/5); the runner that reads/writes it lands
    in a later slice, not this one.

    ``status``/``stop_reason`` mirror the vocabulary in
    ``services/agent/status.py`` (``WorkflowRunStatus``/``StopReason``)
    but are stored as plain check-constrained strings rather than a native DB
    enum — the same choice ``impact_readings.kind``/``confidence`` made
    (migration 033) so a future vocabulary addition is an additive migration,
    not an ``ALTER TYPE``. The check constraints are the DB-level backstop;
    the Python vocabulary module is the source of truth other code imports.

    ``started_at``/``completed_at``/``waiting_approval_since``/
    ``running_seconds_elapsed`` exist so later slices can implement the
    wall-clock timeout (300s of *running* time only, per ADR-073 decision 2 —
    the clock pauses while ``waiting_approval``) and the 4h
    ``confirmation_expired`` reaper check (ADR-074 amendment) without a
    further migration. This slice does not write the accounting logic itself.

    Only one active run per ``(shop_id, product_id)`` is allowed structurally
    via the partial unique index below, scoped to
    ``status IN ('queued', 'running', 'waiting_approval')`` — ADR-073
    decision 4, the guard against a second Juli-initiated run racing the
    same product.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_approval_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    running_seconds_elapsed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Outcome fact, not a status field (migration 037, issue #1220,
    #: ADR-073 decision 2): whether every operation named by the active
    #: `Playbook`'s `TerminationPolicy.required_steps` completed
    #: successfully during this run -- the "did the job" signal feeding the
    #: execution-quality metric. Nullable, default NULL ("not yet
    #: determined") -- distinct from `False` ("determined: not all
    #: required steps completed"). Never drives `status`/`stop_reason`: a
    #: `final_response` (or any other terminal stop_reason) with this
    #: `False` is honest data, not a synthetic failure. Written by
    #: `WorkflowRunner` (via `ConversationStore.persist`) and the reaper
    #: (`_ReaperEventSink.emit`) at every terminal exit, alongside
    #: `status`/`stop_reason` -- never a second, independent write path.
    required_steps_completed: Mapped[bool | None] = mapped_column(Boolean)
    #: The ActionCard whose approval created this run (migration 040, issue
    #: #1269, ADR-082 decision 6): ADR-075 decision 1 has always specified
    #: "INSERT the `workflow_run` (FK to the card)", but #1214 shipped no
    #: link in either direction. Nullable, no backfill -- runs created
    #: before this column existed have no card, and inventing one would be
    #: false data. Nothing writes this column yet; #1222's approve
    #: transaction is the first writer.
    action_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_cards.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_workflow_runs_shop", "shop_id"),
        Index("ix_workflow_runs_action_card", "action_card_id"),
        Index(
            "uq_workflow_runs_active_shop_product",
            "shop_id",
            "product_id",
            unique=True,
            postgresql_where="status IN ('queued', 'running', 'waiting_approval')",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'completed', "
            "'cancelled', 'timed_out', 'failed')",
            name="ck_workflow_runs_status",
        ),
        CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ("
            "'final_response', 'confirmation_declined', 'paused_for_confirmation', "
            "'cancelled_by_seller', 'confirmation_expired', 'confirmation_diverged', "
            "'iteration_cap_exceeded', "
            "'wall_clock_timeout', 'tool_error_unrecoverable', 'llm_error', "
            "'concurrency_conflict', 'output_validation_failed', 'worker_lost')",
            name="ck_workflow_runs_stop_reason",
        ),
    )


class WorkflowRunEvent(Base):
    """Append-only event-log row for a `workflow_runs` row — the Postgres
    replay authority ADR-074 decision 1 establishes (#1125 / AGT-W3B):
    anything a client sees on the SSE stream must exist as a row here
    first, Redis (a later slice) only makes it fast.

    Mirrors the Pydantic envelope in ``services/agent/events/envelope.py``
    field-for-field (``workflow_run_id``, ``sequence_number``,
    ``event_type``, ``timestamp``, ``payload``, ``v``) plus the ORM-only
    surrogate primary key ``id``. ``sequence_number`` is minted by the
    ``WorkflowRunner`` (a later slice) from its run-state blob, never by
    this table or any code in this slice.

    The unique ``(workflow_run_id, sequence_number)`` index is the
    mechanism, not decoration: exactly one writer per run exists (a
    partial-unique active-run index plus one Celery task per
    ``workflow_run_id``), so a crash-replayed emit racing the same
    sequence number hits this constraint and becomes a no-op instead of a
    duplicate row.
    """

    __tablename__ = "workflow_run_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    v: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        Index(
            "uq_workflow_run_events_run_sequence",
            "workflow_run_id",
            "sequence_number",
            unique=True,
        ),
        Index("ix_workflow_run_events_run_id", "workflow_run_id"),
    )


class RunConfirmation(Base):
    """Decision request presented at a CONFIRM pause -- one row per pause
    (ADR-075 decision 2, #1214 / AGT-W5A-DP).

    ``options`` is a list of ``{option_id, proposed_change, rationale,
    params_sha}``; ``proposed_change`` is stored VERBATIM -- the audit is
    what was shown to the seller, never a re-derivation from later run
    state. ``status`` mirrors the "string + CHECK, not a native DB enum"
    choice ``workflow_runs.status`` made in migration 034, so a later
    vocabulary addition stays additive.

    The partial unique index ``uq_run_confirmations_pending_run`` on
    ``workflow_run_id`` (filtered to ``status = 'pending'``) is the
    structural guard the confirmation-authorization ladder assumes: a run
    has at most one open decision request at a time, though any number of
    terminal (approved/declined/expired) rows may accumulate over its
    lifetime.

    This slice ships schema only -- the runner that writes these rows at a
    CONFIRM pause, and the route that resolves them, land in later W5-A
    slices (#1221-#1225).
    """

    __tablename__ = "run_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_option_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_run_confirmations_workflow_run", "workflow_run_id"),
        Index(
            "uq_run_confirmations_pending_run",
            "workflow_run_id",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'expired')",
            name="ck_run_confirmations_status",
        ),
    )


class ToolExecution(Base):
    """Approved tool call dispatched to Celery — P2-B4 (#305).

    Promoted from an audit-only row to an idempotency ledger by ADR-073
    decision 3 (#1117 / AGT-W3A): ``workflow_run_id``/``tool_call_id``/
    ``operation`` plus the unique constraint over the three let
    ``WorkflowRunner`` (a later slice) SELECT-before-write on retry and
    replay a stored sanitized result byte-identically instead of re-calling
    TikTok. All three are nullable — pre-agent legacy rows (and the
    Celery-approval write path this class already served) have none of
    them, and that must keep inserting unchanged.
    """

    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    outcome_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_category: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    # --- Idempotency-ledger columns, ADR-073 decision 3 (#1117 / AGT-W3A) ---
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    tool_call_id: Mapped[str | None] = mapped_column(String(255))
    operation: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        Index("ix_tool_executions_shop", "shop_id"),
        Index("ix_tool_executions_status", "shop_id", "status"),
        UniqueConstraint(
            "workflow_run_id",
            "tool_call_id",
            "operation",
            name="uq_tool_executions_run_call_operation",
        ),
    )


class WorkflowOutcomeRecord(Base):
    """Persisted workflow outcome metrics after tool execution — P2-B5 (#306)."""

    __tablename__ = "workflow_outcome_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_executions.id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(20), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_workflow_outcome_records_shop", "shop_id"),
        Index("ix_workflow_outcome_records_approval", "shop_id", "approval_id"),
        UniqueConstraint(
            "shop_id",
            "execution_id",
            name="uq_workflow_outcome_records_shop_execution",
        ),
    )


class ImpactReading(Base):
    """Incremental-impact reading — control-adjusted pre/post per (execution, metric,
    kind) — ADR-077 decision 5, I9 (#1040).

    Source of truth for every impact reading computed by the daily impact-reader
    beat task: the four-metric business-impact aggregation and the eval pipeline
    need cross-run *queries* over this table, not JSON parsing of the legacy
    outcome envelope.

    ``run_id`` was a deliberate deferred constraint, not an oversight: ADR-077
    d.5 names ``run_id`` alongside ``tool_execution_id``, but the
    ``workflow_runs`` table (W3-A, ADR-073) did not exist when migration 033
    landed — P-IM "depends on nothing in the agent stack" per the wave
    handoff, so the column shipped as a plain nullable UUID with no foreign
    key. Migration 034 (#1117 / AGT-W3A) adds
    ``ForeignKeyConstraint(["run_id"], ["workflow_runs.id"])`` now that
    ``workflow_runs`` exists; no data is backfilled by that migration, and
    ``run_id`` stays nullable — legacy readings predate ``workflow_runs``.

    Numeric precision deliberately reuses the two scales
    ``AnalyticsPerformanceInterval`` already established rather than inventing a
    third: ``pre``/``post``/``expected``/``incremental`` carry the raw metric
    reading on the same money/count scale as ``gmv`` (``Numeric(18, 2)``);
    ``impact_pct`` is always a ratio (``incremental / expected``) regardless of
    which underlying metric produced it, so it uses the same rate scale as
    ``ctr``/``conversion_rate`` (``Numeric(10, 6)``).
    """

    __tablename__ = "impact_readings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # FK added by migration 034 (#1117 / AGT-W3A) — see class docstring.
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    tool_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_executions.id"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    pre: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    post: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expected: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    incremental: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    # Chosen control set (IDs, correlations, windows) — required on every reading
    # for audit and placebo verification (ADR-077 d.3), not only on Cao/Trung
    # binh readings.
    control_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_impact_readings_run_id", "run_id"),
        Index("ix_impact_readings_tool_execution", "tool_execution_id"),
        UniqueConstraint(
            "tool_execution_id",
            "metric",
            "kind",
            name="uq_impact_readings_execution_metric_kind",
        ),
        CheckConstraint(
            "kind IN ('preliminary', 'final')",
            name="ck_impact_readings_kind",
        ),
        CheckConstraint(
            "confidence IN ('cao', 'trung_binh', 'thap', 'suppressed', 'confounded')",
            name="ck_impact_readings_confidence",
        ),
    )


class ActionCard(Base):
    """Persisted Decision row from the rules pipeline — P2-B1 (#303, ADR-021)."""

    __tablename__ = "action_cards"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation_payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    approved_at: Mapped[datetime | None] = mapped_column()
    executed_at: Mapped[datetime | None] = mapped_column()
    outcome: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    # Scoring-run freshness timestamp (#715, B-3, ADR-038) — mirrors
    # GoldKpiEnvelope.computed_at / AnalyticsKpiEnvelope.computed_at so Decision
    # feed freshness reads on the same semantics as the Analytics envelope.
    # Nullable/additive: existing rows predate this column and read unchanged.
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Decision emission/surfacing budget (#716, B-4, ADR-038 §6, migration 027).
    # Deliberately additive *columns* alongside the existing seller-lifecycle
    # ``status`` (active/approved/dismissed/executing) rather than new status
    # enum values — see services/action_cards/MODULE.md "Emission/surfacing
    # persistence model" for the full rationale.
    #
    # ``dismissed_at``: terminal timestamp for a seller "dismiss" action,
    # paralleling approved_at/executed_at. Used for the 7-day per-workflow
    # cooldown (services.action_cards.persist / services.action_cards.emission_budget).
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ``surfaced_at``: last time services.action_cards.emission_budget selected
    # this candidate into the Demo active surfaced set. NULL means "not
    # currently surfaced" — either never evaluated yet, or suppressed (see
    # ``suppressed_reason``). Mutually exclusive with suppressed_reason after
    # each apply_emission_budget run.
    surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ``suppressed_reason``: why the emission budget did not surface this
    # candidate on its most recent evaluation — "active_cap" / "cooldown" /
    # "weekly_novelty_cap" (services.action_cards.emission_budget) — or NULL
    # when currently surfaced / not yet evaluated.
    suppressed_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_action_cards_shop", "shop_id"),
        Index("ix_action_cards_shop_status", "shop_id", "status"),
        # Provisioned ahead of need (#716, B-4, ADR-038 §6) for a cooldown
        # lookup by (shop_id, workflow_key) plus terminal markers that a
        # future slice may query directly. Not exercised today:
        # apply_emission_budget's only query is
        # WHERE shop_id=:s AND status='active' (served by the
        # ix_action_cards_shop_status index above); the cooldown check
        # itself runs in Python over those already-loaded rows.
        Index(
            "ix_action_cards_shop_workflow_terminal",
            "shop_id",
            "workflow_key",
            "dismissed_at",
            "approved_at",
            "executed_at",
        ),
        # Surfacing state must be queryable separately from "all scored rows"
        # (#716, B-4).
        Index("ix_action_cards_shop_surfaced_at", "shop_id", "surfaced_at"),
        UniqueConstraint(
            "shop_id",
            "workflow_key",
            name="uq_action_cards_shop_workflow",
        ),
    )


class ActionCardApproval(Base):
    """Approval audit record -- who approved which `ActionCard`, when, and a
    snapshot of the card as shown (ADR-075 decision 1, #1214 / AGT-W5A-DP).

    A NEW TABLE, not additive columns on `ActionCard` -- see
    `039_run_confirmations.py`'s module docstring for the full rationale.
    In short: `ActionCard.approved_at`/`executed_at`/`dismissed_at`/
    `surfaced_at` (#716) are seller-lifecycle state on the live row, not an
    audit trail, and must not be repurposed; `card_snapshot` must survive
    the card later changing, which a column on the card itself cannot do
    (it IS the thing that changes); and `action_cards` allows only one row
    per `(shop_id, workflow_key)`, so columns there could only ever hold the
    most recent approval, not a history.

    `card_snapshot` is stored VERBATIM -- the audit is what was shown to
    the seller at approval time, mirroring `RunConfirmation.options[].
    proposed_change`'s discipline.

    This slice ships schema only -- the transactional approve-is-run-
    creation write path lands in a later W5-A slice.
    """

    __tablename__ = "action_card_approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action_card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_cards.id"), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(server_default=func.now())
    card_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_action_card_approvals_action_card", "action_card_id"),)


class DecisionEmissionNoveltyLedger(Base):
    """Durable weekly novelty ledger for the Decision emission budget.

    Server-side (Postgres) record of which ``workflow_key``s have already
    consumed a "new this week" novelty slot for a shop — #716 (B-4), ADR-038
    §6. Postgres is the source of truth; Redis (if ever used as a read-through
    cache in front of this) must never be the only place this state lives.
    One row per (shop_id, week_start, workflow_key) — inserted the first time
    ``services.action_cards.emission_budget.apply_emission_budget`` surfaces a
    workflow_key that has not yet been counted in the current ISO week.
    """

    __tablename__ = "decision_emission_novelty_ledger"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    # Monday (UTC date) of the ISO week this novelty slot was consumed in.
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False)
    first_surfaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_decision_emission_novelty_shop_week", "shop_id", "week_start"),
        UniqueConstraint(
            "shop_id",
            "week_start",
            "workflow_key",
            name="uq_decision_emission_novelty_shop_week_workflow",
        ),
    )


class DemoExecutionRecord(Base):
    """Local/demo dry-run execution record for a Decision approve (#717, B-5).

    ADR-037/ADR-038 §9: Public Mock Demo approve→execute never calls a real
    Partner write client and never uses reference-merchant credentials. This
    table is the *entire* durability boundary for that dry-run — it is
    deliberately a standalone table, not a reuse of ``tool_executions``
    (``ToolExecution``, migration 015), because ``tool_executions`` rows are
    Celery-dispatched and mean "this really called a TikTok write endpoint via
    ``services.execution.dispatch.enqueue_approved_tool``". Mixing dry-run rows
    into that table would blur a real-execution reconciliation job's view of
    "what actually still needs a Partner call" with rows that will never be
    picked up by Celery. See ``services/demo_execution/MODULE.md`` for the
    full write-up of this decision.

    Progress state machine (``status``): ``queued`` -> ``running`` -> ``done``
    — entirely local/in-process; no Celery task, no TikTok call. ``narrative_json``
    is the ordered list of ``{state, message, at}`` steps Track B UI (#600,
    execution progress card #696/#697) reads to render dry-run progress.
    """

    __tablename__ = "demo_execution_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    action_card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_cards.id"), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    narrative_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_demo_execution_records_shop", "shop_id"),
        Index("ix_demo_execution_records_shop_status", "shop_id", "status"),
        Index(
            "ix_demo_execution_records_action_card",
            "shop_id",
            "action_card_id",
        ),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# Commerce graph (P1-1 — Issue #92)
# ---------------------------------------------------------------------------


class Campaign(Base):
    """Campaign node: creator + shop collaboration with predicted/realized outcomes."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("creators.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    product_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    predicted_gmv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    realized_gmv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    predicted_conversion: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    realized_conversion: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_campaigns_shop_created", "shop_id", "created_at"),
        Index("ix_campaigns_shop_creator", "shop_id", "creator_id"),
        Index(
            "ix_campaigns_shop_idempotency",
            "shop_id",
            "idempotency_key",
            unique=True,
        ),
    )


class GraphEdge(Base):
    """Relationship edge between commerce graph nodes (creator, shop, product, campaign)."""

    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_graph_edges_shop_type", "shop_id", "edge_type"),
        Index(
            "ix_graph_edges_natural_key",
            "shop_id",
            "edge_type",
            "source_node_type",
            "source_node_id",
            "target_node_type",
            "target_node_id",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# Analytics backfill partition progress (P2-9-2 — Issue #464)
# ---------------------------------------------------------------------------


class AnalyticsBackfillPartition(Base):
    """Durable (shop_id, bucket, date) progress for resumable analytics backfill."""

    __tablename__ = "analytics_backfill_partitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    partition_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_analytics_backfill_partitions_shop_bucket_date",
            "shop_id",
            "bucket",
            "partition_date",
        ),
        UniqueConstraint(
            "shop_id",
            "bucket",
            "partition_date",
            name="uq_analytics_backfill_partitions_shop_bucket_date",
        ),
        {"schema": "ops"},
    )


# ---------------------------------------------------------------------------
# Analytics KPI envelopes (P2.10-A1 — Issue #525)
# ---------------------------------------------------------------------------


class GoldKpiEnvelope(Base):
    """Serving gold KPI envelope — one row per shop (ADR-046 Q3 / #606)."""

    __tablename__ = "kpi_envelopes"
    __table_args__ = {"schema": "gold"}

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    envelope_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AnalyticsKpiEnvelope(Base):
    """Legacy public envelope table — read-only after gold cutover (#606)."""

    __tablename__ = "analytics_kpi_envelopes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    envelope_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "kind",
            name="uq_analytics_kpi_envelopes_shop_kind",
        ),
    )


# ---------------------------------------------------------------------------
# Bronze raw landing — orders/returns append-only (#605)
# ---------------------------------------------------------------------------


class BronzeOrderRawPayload(Base):
    """Append-only raw order payloads from webhooks or targeted fetch."""

    __tablename__ = "order_raw_payloads"
    __table_args__ = (
        Index(
            "ix_bronze_order_raw_payloads_shop_received",
            "shop_id",
            "received_at",
        ),
        {"schema": "bronze"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    ingest_source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tiktok_order_id: Mapped[str | None] = mapped_column(String(100))
    source_event_id: Mapped[str | None] = mapped_column(String(255))


class BronzeReturnRawPayload(Base):
    """Append-only raw return/cancellation payloads from webhooks or targeted fetch."""

    __tablename__ = "return_raw_payloads"
    __table_args__ = (
        Index(
            "ix_bronze_return_raw_payloads_shop_received",
            "shop_id",
            "received_at",
        ),
        {"schema": "bronze"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    ingest_source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tiktok_return_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_order_id: Mapped[str | None] = mapped_column(String(100))
    source_event_id: Mapped[str | None] = mapped_column(String(255))


class BronzeCtorPerformanceRawPayload(Base):
    """Append-only raw A-34 product performance rows (ctor domain, #880)."""

    __tablename__ = "ctor_performance_raw_payloads"
    __table_args__ = (
        Index(
            "ix_bronze_ctor_performance_raw_payloads_shop_received",
            "shop_id",
            "received_at",
        ),
        {"schema": "bronze"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    ingest_source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    source_event_id: Mapped[str | None] = mapped_column(String(255))


class BronzeLiveHoursRawPayload(Base):
    """Append-only raw A-28 LIVE performance rows (live_hours domain, #880)."""

    __tablename__ = "live_hours_raw_payloads"
    __table_args__ = (
        Index(
            "ix_bronze_live_hours_raw_payloads_shop_received",
            "shop_id",
            "received_at",
        ),
        {"schema": "bronze"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    ingest_source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tiktok_live_id: Mapped[str | None] = mapped_column(String(100))
    source_event_id: Mapped[str | None] = mapped_column(String(255))


class ProductionWriteAuthorization(Base):
    """Single-use owner authorization for a production mutation on a listing.

    Scoped to exactly one shop, one product, and one mutation kind. Expires
    after a configurable TTL (default 24h) and is consumed atomically by the
    write path. An operator issues authorizations after verifying the
    credential binding; a revoked authorization is preserved for audit.

    Tenant treatment: direct shop_id (ADR-068 decision, #1328).
    """

    __tablename__ = "production_write_authorizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mutation_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    authorized_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    consumed_by_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_production_write_authorizations_shop_id", "shop_id"),
        Index(
            "ix_production_write_authorizations_lookup",
            "shop_id",
            "tiktok_product_id",
            "mutation_kind",
        ),
    )


class ProductionWriteAudit(Base):
    """Append-only audit trail of every production write attempt (issue #1337).

    Records every production write attempt—allowed and refused—carrying:
    - run_id: the workflow run identifier
    - shop_id: the tenant (for RLS isolation)
    - tiktok_product_id: the target product
    - mutation_kind: the operation type
    - authorization_id: set if attempt succeeded, NULL if refused
    - precondition_name: set if attempt was refused, NULL if succeeded
    - release_sha: the deployed release SHA
    - created_at: server timestamp

    Tenant treatment: direct shop_id (ADR-068 decision, #1328).
    Append-only: no UPDATE or DELETE grants to juli_app.
    """

    __tablename__ = "production_write_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mutation_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_write_authorizations.id")
    )
    precondition_name: Mapped[str | None] = mapped_column(String(100))
    release_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_production_write_audit_shop_id", "shop_id"),
        Index("ix_production_write_audit_run_id", "run_id"),
        Index("ix_production_write_audit_created_at", "created_at"),
    )


from juli_backend.services.etl.persistence.ingest import (  # noqa: E402, F401
    ProcessedEvent,
)
