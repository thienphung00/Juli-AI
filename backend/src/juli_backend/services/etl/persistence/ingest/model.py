"""ProcessedEvent ORM model — ETL ingest idempotency ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base


class ProcessedEvent(Base):
    """Idempotency ledger for ETL ingest consumers (#32)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_processed_events_shop", "shop_id"),)
