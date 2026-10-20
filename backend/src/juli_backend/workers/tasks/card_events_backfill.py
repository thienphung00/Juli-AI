"""Celery tasks: backfill past cards into ``card_events`` (fast track P60-1a, ADR-107 am. §5).

Manual only -- **not on the beat schedule**. Reads the database, no TikTok call,
no LLM; idempotent (a second run inserts nothing), so Ops may run it any time.

``juli_backend.card_events_backfill(shop_id)``
    ``services.card_events.backfill_shop`` for one shop under its scope
    (ADR-089), one commit. Returns the per-event counts.
``juli_backend.card_events_backfill_fanout()``
    One ``card_events_backfill`` per pollable shop (``enumerate_pollable_shops``).

Owner runs it on the server, e.g.::

    celery -A juli_backend.workers.celery_app call juli_backend.card_events_backfill \\
        --args='["<shop uuid>"]'
    celery -A juli_backend.workers.celery_app call juli_backend.card_events_backfill_fanout
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

BACKFILL_TASK = "juli_backend.card_events_backfill"
FANOUT_TASK = "juli_backend.card_events_backfill_fanout"
BACKFILL_TIMEOUT_SECONDS = 600.0


async def run_backfill(shop_id: uuid.UUID, *, session_factory: Any) -> dict[str, Any]:
    """Backfill one shop and commit; raises on a database error (re-run to resume)."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services import card_events

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            report = await card_events.backfill_shop(session, shop_id)
            await session.commit()
    body = report.as_dict()
    # The counts go in the message too: journald keeps the text, not the extras.
    logger.info(
        "card_events_backfill_done shop_id=%s inserted_total=%s inserted=%s",
        body["shop_id"],
        body["inserted_total"],
        body["inserted"],
        extra=body,
    )
    return body


async def run_fanout(
    session: Any,
    *,
    enqueue: Callable[[str], Any],
    enumerate_fn: Callable[[Any], Awaitable[list[Any]]] | None = None,
) -> int:
    """Enqueue one backfill per pollable shop. Returns the enqueued count."""
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    shops = await (enumerate_fn or enumerate_pollable_shops)(session)
    enqueued = 0
    for shop in shops:
        try:
            enqueue(str(shop.shop_id))
            enqueued += 1
        except Exception:
            logger.error(
                "card_events_backfill_enqueue_failed",
                extra={"shop_id": str(shop.shop_id)},
                exc_info=True,
            )
    logger.info("card_events_backfill_fanout", extra={"shops": len(shops), "enqueued": enqueued})
    return enqueued


def _factory() -> Any:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(get_async_database_url())


@celery_app.task(name=BACKFILL_TASK)
def card_events_backfill(shop_id: str) -> dict[str, Any]:
    """Backfill one shop's past cards into ``card_events`` (DB only, idempotent)."""

    async def go() -> dict[str, Any]:
        return await asyncio.wait_for(
            run_backfill(uuid.UUID(shop_id), session_factory=_factory()),
            timeout=BACKFILL_TIMEOUT_SECONDS,
        )

    return asyncio.run(go())


@celery_app.task(name=FANOUT_TASK)
def card_events_backfill_fanout() -> int:
    """One ``card_events_backfill`` per pollable shop."""

    async def go() -> int:
        async with _factory()() as session:
            return await run_fanout(session, enqueue=lambda sid: card_events_backfill.delay(sid))

    return asyncio.run(go())


__all__ = [
    "BACKFILL_TASK",
    "FANOUT_TASK",
    "card_events_backfill",
    "card_events_backfill_fanout",
    "run_backfill",
    "run_fanout",
]
