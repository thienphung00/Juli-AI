"""``processed_events`` retention (fast track P62-B, D72.2).

The ledger only has to outlive the window in which the same ``(event_id, epoch)`` can be
presented to ``EtlConsumer`` again. From the code:

- poll overlap / Celery retries / a resumed bootstrap re-send records within hours;
- the history walk ends ``SHOP_HISTORY_CONNECT_DAYS`` (60) after connect plus
  ``nightly_chunks x nightly_chunk_days`` per night: 60 -> 180 days in **4 nights**
  (``services/onboarding/history.py``), so a record the live poll ingested and the walk
  re-fetches is re-presented within days of connect;
- webhook redelivery: TikTok's retry horizon is unconfirmed
  (``docs/product/data-platform/P0_TIKTOK_WEBHOOKS.md``); retries are commonly bounded
  by a few days;
- ``product_history/replay.py`` (D30.4) replays ``webhook_raw_events`` through the
  webhook side effects, not through this ledger, so it adds no horizon here;
- an epoch advance (#1968) makes every older-epoch row dead weight at once (claims look
  up the CURRENT epoch only).

:data:`PROCESSED_EVENTS_RETENTION_DAYS` = 30 is several times the longest of those. Past
it, a re-presented event is harmless anyway: every silver upsert refuses an
``update_time`` at or before the stored one (``ShopScopedRepo._apply_if_newer``).

The delete runs as the table owner through ``purge_processed_events`` (migration 098,
SECURITY DEFINER, floor ``MIN_RETENTION_DAYS`` = 14 in SQL), one batch per call, one
commit per batch, at most :data:`PROCESSED_EVENTS_MAX_BATCHES_PER_RUN` batches a night;
a backlog drains over the following nights.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

#: Days a ledger row is kept after it was written (see the module docstring).
PROCESSED_EVENTS_RETENTION_DAYS = 30
#: Rows deleted per statement / commit: short locks, small WAL bursts.
PROCESSED_EVENTS_PURGE_BATCH = 5_000
#: Batches per nightly run (200k rows); the rest waits for the next night.
PROCESSED_EVENTS_MAX_BATCHES_PER_RUN = 40

_PURGE_SQL = text("SELECT public.purge_processed_events(:days, :batch)")


@dataclass(frozen=True)
class RetentionResult:
    deleted: int
    batches: int
    exhausted: bool  # True when the last batch was short: nothing expired is left


async def purge_processed_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int = PROCESSED_EVENTS_RETENTION_DAYS,
    batch_size: int = PROCESSED_EVENTS_PURGE_BATCH,
    max_batches: int = PROCESSED_EVENTS_MAX_BATCHES_PER_RUN,
) -> RetentionResult:
    """Delete expired ledger rows in committed batches; returns the totals."""
    deleted = batches = 0
    exhausted = False
    while batches < max_batches:
        async with session_factory() as session:
            count = int(
                (
                    await session.execute(_PURGE_SQL, {"days": retention_days, "batch": batch_size})
                ).scalar_one()
            )
            await session.commit()
        batches += 1
        deleted += count
        if count < batch_size:
            exhausted = True
            break
    logger.info(
        "processed_events_retention",
        extra={
            "deleted": deleted,
            "batches": batches,
            "exhausted": exhausted,
            "retention_days": retention_days,
        },
    )
    return RetentionResult(deleted=deleted, batches=batches, exhausted=exhausted)


__all__ = [
    "PROCESSED_EVENTS_MAX_BATCHES_PER_RUN",
    "PROCESSED_EVENTS_PURGE_BATCH",
    "PROCESSED_EVENTS_RETENTION_DAYS",
    "RetentionResult",
    "purge_processed_events",
]
