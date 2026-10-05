"""Per-shop ingestion bootstrap state (fast track P1-B, SPEC §3.1 / §3.7).

One row per shop. It answers three questions the poll path could not answer
before:

- has this shop finished its fast phase (so the scheduler polls it normally
  rather than bootstrapping it again)?
- how far back has the history phase reached, so a re-run resumes instead of
  refetching completed chunks?
- how long did "connect -> first card" take, from data rather than from logs?

Kept in its own module (not ``models.py``) so it can land beside concurrent
changes to the analytics model classes without touching them. It is registered
on ``Base.metadata`` through ``juli_backend.models.__init__``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: Bootstrap lifecycle. A plain varchar checked in application code, mirroring
#: ``tiktok_credentials.status`` -- no native enum.
BOOTSTRAP_NOT_STARTED = "not_started"
BOOTSTRAP_FAST_RUNNING = "fast_running"
BOOTSTRAP_FAST_DONE = "fast_done"
BOOTSTRAP_HISTORY_RUNNING = "history_running"
BOOTSTRAP_HISTORY_DONE = "history_done"
BOOTSTRAP_FAILED = "failed"

BOOTSTRAP_STATUSES: tuple[str, ...] = (
    BOOTSTRAP_NOT_STARTED,
    BOOTSTRAP_FAST_RUNNING,
    BOOTSTRAP_FAST_DONE,
    BOOTSTRAP_HISTORY_RUNNING,
    BOOTSTRAP_HISTORY_DONE,
    BOOTSTRAP_FAILED,
)


class ShopIngestionState(Base):
    """Bootstrap phase, latency timestamps and analytics cursors for one shop.

    Timestamps are naive UTC (``TIMESTAMP WITHOUT TIME ZONE``), as everywhere
    else in this schema (#1138).
    """

    __tablename__ = "shop_ingestion_state"

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BOOTSTRAP_NOT_STARTED)
    #: Which phase failed when ``status == 'failed'`` (``fast`` | ``history``).
    failed_phase: Mapped[str | None] = mapped_column(String(10))
    last_error: Mapped[str | None] = mapped_column(String(500))

    # Latency instrumentation (SPEC §3.7). Each is written once, the first time
    # the transition happens, so a re-run never moves the measurement.
    connect_committed_at: Mapped[datetime | None] = mapped_column()
    bootstrap_enqueued_at: Mapped[datetime | None] = mapped_column()
    fast_started_at: Mapped[datetime | None] = mapped_column()
    fast_done_at: Mapped[datetime | None] = mapped_column()
    first_card_at: Mapped[datetime | None] = mapped_column()
    history_started_at: Mapped[datetime | None] = mapped_column()
    history_done_at: Mapped[datetime | None] = mapped_column()
    failed_at: Mapped[datetime | None] = mapped_column()

    # History phase progress. Chunks are contiguous and walk backwards, so the
    # earliest date reached IS the resume point: the next chunk ends there.
    history_earliest_date: Mapped[date | None] = mapped_column(Date)
    history_chunks_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    history_empty_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Daily analytics cadence (SPEC §3.3). ``analytics_through_date`` is the
    # last day whose analytics were fetched completely (inclusive);
    # ``analytics_last_run_on`` is the UTC date of the last pass that fetched
    # new days -- the "at most once a day" gate.
    analytics_through_date: Mapped[date | None] = mapped_column(Date)
    analytics_last_run_on: Mapped[date | None] = mapped_column(Date)
    latest_available_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


__all__ = [
    "BOOTSTRAP_FAILED",
    "BOOTSTRAP_FAST_DONE",
    "BOOTSTRAP_FAST_RUNNING",
    "BOOTSTRAP_HISTORY_DONE",
    "BOOTSTRAP_HISTORY_RUNNING",
    "BOOTSTRAP_NOT_STARTED",
    "BOOTSTRAP_STATUSES",
    "ShopIngestionState",
]
