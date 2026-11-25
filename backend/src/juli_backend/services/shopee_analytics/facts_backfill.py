"""The triggered backfill of the stored facts right after a deploy (owner decision #74, plan a).

A release that bumps the registry ``DERIVATION_VERSION`` / ``materialize.ROWS_VERSION`` (or adds a
grain) makes every stored day of every shop stale. Instead of waiting for the nightly job, the
worker runs :func:`run` as it starts (``worker_ready``) and on its beat: for each REAL Shopee
shop (never the reviewer sample shop, never TikTok), one shop at a time, it rebuilds the pending
days newest first in chunks (:data:`CHUNK_DAYS`), committing each chunk and refreshing the shop's
``shop_facts_status`` (so the newest 90 days are readable before the older ones are done).

Idempotent: a shop with nothing pending costs a status refresh. One run at a time: the whole run
holds a transaction-scoped advisory lock on its own session (:data:`ADVISORY_LOCK_KEY`), so a
second worker that starts meanwhile skips instead of doubling the work. No CLI: the worker task
``juli_backend.shopee_facts_backfill`` is the only way in. Logs counts only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Shop
from juli_backend.services.reviewer.config import reviewer_sample_shop_ids
from juli_backend.services.shopee_analytics import materialize

logger = logging.getLogger(__name__)

PLATFORM = "shopee"
#: days rebuilt per transaction (newest first): the first chunk makes a 90-day window ready
CHUNK_DAYS = 90
#: a run stops after this many chunks per shop; the next beat continues
MAX_CHUNKS_PER_SHOP = 20
#: ``pg_try_advisory_xact_lock`` key, fixed, used by nothing else (``"juli-fct"``)
ADVISORY_LOCK_KEY = 0x6A756C69666374
_LOCK = text("SELECT pg_try_advisory_xact_lock(:key)")

SessionFactory = Callable[[], Any]


@dataclass
class FactsBackfillResult:
    shops: int = 0
    shops_rebuilt: int = 0
    days: int = 0
    failed: int = 0
    #: why nothing ran: ``locked`` (another worker holds the run); None when it ran
    skipped: str | None = None

    def as_log(self) -> dict[str, Any]:
        return {
            "shops": self.shops,
            "shops_rebuilt": self.shops_rebuilt,
            "days": self.days,
            "failed": self.failed,
            "skipped": self.skipped,
        }


async def real_shopee_shops(session: AsyncSession) -> list[uuid.UUID]:
    """Every Shopee shop but the reviewer sample shop(s). TikTok shops are not Shopee shops."""
    sample = reviewer_sample_shop_ids()
    found = await session.execute(select(Shop.id).where(Shop.platform == PLATFORM))
    return sorted((i for i in found.scalars().all() if i not in sample), key=str)


async def _shop(factory: SessionFactory, shop_id: uuid.UUID) -> int:
    """Rebuild one shop's pending days, newest chunk first; returns the days rebuilt."""
    done = 0
    for _ in range(MAX_CHUNKS_PER_SHOP):
        async with factory() as session:
            async with with_shop_scope(session, shop_id):
                pending = await materialize.pending_days(session, shop_id)
                chunk = pending[-CHUNK_DAYS:]
                if chunk:
                    done += await materialize.rebuild_days(session, shop_id, chunk)
                await materialize.refresh_status(session, shop_id)
                await session.commit()
        if len(pending) <= CHUNK_DAYS:
            break
    return done


async def run(factory: SessionFactory) -> FactsBackfillResult:
    """One backfill pass over the real Shopee shops (see the module docstring)."""
    out = FactsBackfillResult()
    async with factory() as lock_session:
        locking = lock_session.get_bind().dialect.name == "postgresql"
        if locking:
            got = (await lock_session.execute(_LOCK, {"key": ADVISORY_LOCK_KEY})).scalar()
            if not got:
                out.skipped = "locked"
                logger.info("shopee_facts_backfill", extra=out.as_log())
                return out
        shops = await real_shopee_shops(lock_session)
        out.shops = len(shops)
        for shop_id in shops:
            try:
                days = await _shop(factory, shop_id)
            except Exception as exc:  # one shop never stops the others; the next beat retries
                out.failed += 1
                logger.error(
                    "shopee_facts_backfill_shop_failed",
                    extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
                )
                continue
            out.days += days
            out.shops_rebuilt += 1 if days else 0
        if locking:
            await lock_session.rollback()  # ends the transaction: releases the run lock
    logger.info("shopee_facts_backfill", extra=out.as_log())
    return out


__all__ = [
    "ADVISORY_LOCK_KEY",
    "CHUNK_DAYS",
    "FactsBackfillResult",
    "real_shopee_shops",
    "run",
]
