"""The Juli Connector's heartbeat and the command Juli can give it (migration 128).

Tenant-direct (``shop_id``, RLS by ``app_current_shop_id()``); ``juli_app`` may SELECT, INSERT and
UPDATE. ``shopee_connector_state``: one row per shop, written by the Connector's poll (and, since
migration 131, the last daily run's reader blocks, written by its run report).
``shopee_connector_commands``: "Đối chiếu ngay" (``reconcile``): ``pending`` -> ``sent`` (handed to
the Connector) -> ``acked`` (it ran it); at most one open command per shop and type.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

COMMAND_RECONCILE = "reconcile"
COMMAND_PENDING = "pending"
COMMAND_SENT = "sent"
COMMAND_ACKED = "acked"


class ShopeeConnectorState(Base):
    __tablename__ = "shopee_connector_state"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    #: None until the Connector says (it reports it with every poll).
    seller_centre_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    connector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Migration 131 (Connector 0.3.22): the last daily run's blocked Seller Centre sections,
    #: ``[{section, reason, readers}]`` (``[]`` = none); NULL until such a run reports.
    reader_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    reader_blocks_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ShopeeConnectorCommand(Base):
    __tablename__ = "shopee_connector_commands"
    __table_args__ = (
        CheckConstraint("type IN ('reconcile')", name="ck_shopee_connector_commands_type"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'acked')", name="ck_shopee_connector_commands_status"
        ),
        Index(
            "uq_shopee_connector_commands_open",
            "shop_id",
            "type",
            unique=True,
            postgresql_where=text("status IN ('pending', 'sent')"),
            sqlite_where=text("status IN ('pending', 'sent')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    type: Mapped[str] = mapped_column(String(16), default=COMMAND_RECONCILE)
    status: Mapped[str] = mapped_column(String(8), default=COMMAND_PENDING)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(nullable=True)
