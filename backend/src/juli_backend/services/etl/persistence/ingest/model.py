"""ProcessedEvent ORM model — ETL ingest idempotency ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: Epoch every ledger row written before #1968 belongs to. A shop/channel with
#: no :class:`IngestDedupEpoch` row resolves here, so the ledger keeps behaving
#: exactly as it did before the column existed.
INITIAL_EPOCH = 0


class ProcessedEvent(Base):
    """Idempotency ledger for ETL ingest consumers (#32).

    The dedup key is ``(event_id, epoch)``, not ``event_id`` alone (#1968).
    Without the epoch the ledger outlived the data it protected: when the
    destination table lost its rows the ledger still claimed those events were
    processed, so they could never be re-ingested and the loss was permanent.
    Advancing the epoch for a channel expresses "ingest this history again"
    additively — no row is ever deleted, so the record of what was ingested,
    and when, survives the recovery.
    """

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    epoch: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        nullable=False,
        default=INITIAL_EPOCH,
        server_default=text(str(INITIAL_EPOCH)),
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_processed_events_shop", "shop_id"),)


class IngestDedupEpoch(Base):
    """Current dedup epoch for one ``(shop, channel)`` pair (#1968).

    A missing row means :data:`INITIAL_EPOCH`, which is why migration 060 can
    create this table empty: applying the migration, importing this module and
    starting a worker all leave every channel exactly where it was. The epoch
    moves only through :meth:`IngestDedupEpochsRepo.advance`, which refuses to
    run without an operator and a reason and records both here.
    """

    __tablename__ = "ingest_dedup_epochs"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(100), primary_key=True)
    epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text(str(INITIAL_EPOCH))
    )
    advanced_at: Mapped[datetime] = mapped_column(server_default=func.now())
    advanced_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_ingest_dedup_epochs_shop", "shop_id"),)
