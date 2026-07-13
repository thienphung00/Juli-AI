import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from juli_backend.orm_base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    shops: Mapped[list["Shop"]] = relationship(back_populates="owner")


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    shop_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tiktok_shop_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="shops")
    credentials: Mapped[list["TikTokCredential"]] = relationship(
        back_populates="shop"
    )

    __table_args__ = (Index("ix_shops_user_id", "user_id"),)


class TikTokCredential(Base):
    __tablename__ = "tiktok_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    merchant_authorization_id: Mapped[str | None] = mapped_column(String(100))
    capability: Mapped[str | None] = mapped_column(String(50))
    shop_cipher: Mapped[str | None] = mapped_column(String(200))
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(50), nullable=False)
    last_update_time: Mapped[int] = mapped_column(nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    line_items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    returns: Mapped[list["Return"]] = relationship(back_populates="order")

    __table_args__ = (
        Index("ix_orders_shop_created", "shop_id", "created_at"),
        Index("ix_orders_shop_tiktok", "shop_id", "tiktok_order_id", unique=True),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id"), nullable=False
    )
    tiktok_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    __tablename__ = "returns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    order: Mapped["Order | None"] = relationship(back_populates="returns")

    __table_args__ = (
        Index("ix_returns_shop_created", "shop_id", "created_at"),
        Index(
            "ix_returns_shop_tiktok",
            "shop_id",
            "tiktok_return_id",
            unique=True,
        ),
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_products_shop_created", "shop_id", "created_at"),
        Index("ix_products_shop_tiktok", "shop_id", "tiktok_product_id", unique=True),
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    tiktok_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tiktok_sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    warehouse_id: Mapped[str | None] = mapped_column(String(100))
    velocity: Mapped[str] = mapped_column(
        String(20), default="low", server_default="low", nullable=False
    )
    update_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    creator: Mapped["Creator | None"] = relationship(back_populates="livestreams")

    __table_args__ = (
        Index(
            "ix_livestreams_shop_tiktok",
            "shop_id",
            "tiktok_livestream_id",
            unique=True,
        ),
    )


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    threshold_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    history: Mapped[list["AlertHistory"]] = relationship(back_populates="alert_config")

    __table_args__ = (
        Index("ix_alert_configs_shop", "shop_id"),
        Index("ix_alert_configs_shop_type", "shop_id", "alert_type", unique=True),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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


class ProcessedEvent(Base):
    """Idempotency ledger for ETL ingest consumers (#32)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_processed_events_shop", "shop_id"),)


class WorkflowWebhookSignal(Base):
    """Durable workflow-intent record emitted by Phase 2 catalog webhooks (#354)."""

    __tablename__ = "workflow_webhook_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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


class ToolExecution(Base):
    """Approved tool call dispatched to Celery — P2-B4 (#305)."""

    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_tool_executions_shop", "shop_id"),
        Index("ix_tool_executions_status", "shop_id", "status"),
    )


class WorkflowOutcomeRecord(Base):
    """Persisted workflow outcome metrics after tool execution — P2-B5 (#306)."""

    __tablename__ = "workflow_outcome_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    approval_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_executions.id"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(20), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_workflow_outcome_records_shop", "shop_id"),
        Index("ix_workflow_outcome_records_approval", "shop_id", "approval_id"),
        UniqueConstraint(
            "shop_id",
            "execution_id",
            name="uq_workflow_outcome_records_shop_execution",
        ),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    recommendation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Commerce graph (P1-1 — Issue #92)
# ---------------------------------------------------------------------------


class Campaign(Base):
    """Campaign node: creator + shop collaboration with predicted/realized outcomes."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("creators.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

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
