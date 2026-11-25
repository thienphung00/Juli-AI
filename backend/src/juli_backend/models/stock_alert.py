"""Stock alert tables (Part S, migration 129). All tenant-direct (RLS by ``app_current_shop_id()``).

- ``stock_history`` (``shopee_stock_history`` until migration 134, T5; the old name is a view for
  one release): one row per variation per Connector read of the product list (``item_snapshot``):
  ``sellable`` / ``available`` stock and the listing status at that read. Insert only; a repeated
  post of the same read is a no-op (unique on the read time). ``variation_id`` was ``model_id``
  (the Connector's wire field keeps that name); ``read_at`` is ``timestamptz`` (a naive value is
  UTC) and comes back aware UTC: the stock-alert code turns it into naive UTC at its boundary
  (``stock_basis.naive_utc``), as its own tables stay naive UTC.
- ``shopee_sku_tracking``: the "Theo dõi" switch per variation. ``set_by`` is ``default`` (Juli
  set it from eligibility) or the user id of the member who switched it; ``set_at`` when.
- ``shopee_stock_alert_unsubscribes``: a member who unsubscribed from this shop's stock e-mail.
- ``shopee_stock_alert_sends``: one row per shop per local day (unique): what was sent (``kind``
  ``alert`` | ``empty`` | ``no_read``), the rows and how many recipients. The idempotency key.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.models.shopee_profit import UTC_TIME
from juli_backend.orm_base import Base

SET_BY_DEFAULT = "default"
KIND_ALERT = "alert"
KIND_EMPTY = "empty"
KIND_NO_READ = "no_read"
SEND_KINDS = (KIND_ALERT, KIND_EMPTY, KIND_NO_READ)


class ShopeeStockHistory(Base):
    __tablename__ = "stock_history"
    __table_args__ = (
        UniqueConstraint(
            "shop_id", "item_id", "variation_id", "read_at", name="uq_stock_history_read"
        ),
        Index("ix_stock_history_read", "shop_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[str] = mapped_column(String(64))
    #: "" for a listing without variations (the item row is its only SKU)
    variation_id: Mapped[str] = mapped_column(String(64), default="", server_default="")
    read_at: Mapped[datetime] = mapped_column(UTC_TIME)
    sellable: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC_TIME, server_default=func.now())


class ShopeeSkuTracking(Base):
    __tablename__ = "shopee_sku_tracking"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    tracked: Mapped[bool] = mapped_column(Boolean)
    set_by: Mapped[str] = mapped_column(String(36))
    set_at: Mapped[datetime] = mapped_column()


class ShopeeStockAlertUnsubscribe(Base):
    __tablename__ = "shopee_stock_alert_unsubscribes"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    at: Mapped[datetime] = mapped_column()


class ShopeeStockAlertSend(Base):
    __tablename__ = "shopee_stock_alert_sends"
    __table_args__ = (
        UniqueConstraint("shop_id", "local_date", name="uq_shopee_stock_alert_sends_day"),
        CheckConstraint(
            "kind IN ('alert', 'empty', 'no_read')", name="ck_shopee_stock_alert_sends_kind"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    local_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(8))
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONBType, default=list)
    recipients: Mapped[int] = mapped_column(Integer, default=0)
    preview: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
