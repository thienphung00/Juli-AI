"""Keep the stored Shopee recommendation cards equal to what the engine computes now.

A card stores numbers computed on the inputs of that moment. ``refresh_shop`` compares every open
card (and each of its versions) with the engine version and the inputs fingerprint
(``shopee_recommendations.freshness``), flags the stale ones and recomputes them
(``stale.rerun_stale`` with ``resend``: a card the shop had been sent comes back sent). It is
idempotent: a second run finds every card fresh and writes nothing.

Triggers: after each input write (``schedule_after_commit``, called from the shop-inputs hook once
the writing transaction has committed), once when the API starts after a deploy
(``run_refresh_all`` from the lifespan, in the background), and the daily beat. Each shop runs in
its own session; a failure is counted and logged (type only, never values) and stops no other shop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops.overview import list_shops
from juli_backend.services.shopee_recommendations import stale
from juli_backend.services.shopee_recommendations.loader import load_env

logger = logging.getLogger(__name__)

SHOPEE = "shopee"
ENV_AFTER_WRITE = "RECO_REFRESH_AFTER_WRITE"
ENV_ON_START = "RECO_REFRESH_ON_START"
SessionFactory = Callable[[], Any]
_TASKS: set[asyncio.Task[Any]] = set()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _on(name: str) -> bool:
    if os.environ.get(
        "PYTEST_CURRENT_TEST"
    ):  # tests call the refresh explicitly, never in the back
        return False
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "no", "off")


async def refresh_shop(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, int]:
    """Flag and recompute the stale open cards of one shop (the caller holds the shop scope and
    commits). Returns the counts; ``{}`` when the shop has no Shopee numbers."""
    moment = (now or _now()).replace(tzinfo=None)
    # imported rows the file marked done are executed at their own date (idempotent)
    from juli_backend.services.planned_changes import backfill_executed

    done = await backfill_executed(session, shop_id, now=moment)
    env = await load_env(session, shop_id, now=moment)
    if env is None:
        return {"backfilled": done["executed"]}
    marked = await stale.mark_stale_by_freshness(session, shop_id, env, now=moment)
    counts = await stale.rerun_stale(session, shop_id, now=moment, resend=True, env=env)
    return {**marked, **counts, "backfilled": done["executed"]}


@dataclass(frozen=True)
class RefreshSummary:
    shops: int = 0
    failed: int = 0
    stale: int = 0
    refreshed: int = 0


async def refresh_one(factory: SessionFactory, shop_id: uuid.UUID, reason: str) -> dict[str, int]:
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            counts = await refresh_shop(session, shop_id)
            await session.commit()
    logger.info(
        "shopee_reco_refresh_shop",
        extra={"shop_id": str(shop_id), "reason": reason, **counts},
    )
    return counts


async def run_refresh_all(factory: SessionFactory, reason: str) -> RefreshSummary:
    """Every Shopee shop, one session each. Idempotent."""
    async with factory() as session:
        shop_ids = [s.shop_id for s in await list_shops(session) if s.platform == SHOPEE]
    failed = stale_n = done = 0
    for shop_id in shop_ids:
        try:
            counts = await refresh_one(factory, shop_id, reason)
        except Exception as exc:  # type only: a message can carry client values
            failed += 1
            logger.error(
                "shopee_reco_refresh_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
            continue
        stale_n += counts.get("flagged", 0)
        done += counts.get("replaced", 0) + counts.get("revised", 0)
    summary = RefreshSummary(len(shop_ids), failed, stale_n, done)
    logger.info(
        "shopee_reco_refresh",
        extra={
            "reason": reason,
            "shops": summary.shops,
            "failed": summary.failed,
            "stale": summary.stale,
            "refreshed": summary.refreshed,
        },
    )
    return summary


def _spawn(coro: Any) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def schedule_on_start(factory: SessionFactory) -> None:
    """Once after a deploy: refresh every Shopee shop in the background (never blocks boot)."""
    if not _on(ENV_ON_START):
        return

    async def go() -> None:
        try:
            await run_refresh_all(factory, "api_start")
        except Exception as exc:
            logger.error(
                "shopee_reco_refresh_start_failed", extra={"error_type": type(exc).__name__}
            )

    _spawn(go())


def schedule_after_commit(session: AsyncSession, shop_id: uuid.UUID, reason: str) -> None:
    """After the writing transaction commits, refresh that shop's cards in the background."""
    if not _on(ENV_AFTER_WRITE):
        return
    from juli_backend.database import database as db

    factory = db._session_factory
    if factory is None:
        return

    def fire(_: Any) -> None:
        async def go() -> None:
            try:
                await refresh_one(factory, shop_id, reason)
            except Exception as exc:
                logger.error(
                    "shopee_reco_refresh_write_failed",
                    extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
                )

        try:
            _spawn(go())
        except RuntimeError:  # no running loop (a sync caller): the daily beat picks it up
            return

    event.listen(session.sync_session, "after_commit", fire, once=True)


__all__ = [
    "RefreshSummary",
    "refresh_one",
    "refresh_shop",
    "run_refresh_all",
    "schedule_after_commit",
    "schedule_on_start",
]
