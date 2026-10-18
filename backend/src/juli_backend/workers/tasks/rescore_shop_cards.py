"""Celery task: re-score one shop's pending Optimize Product cards now (Ops, P23 follow-up).

``juli_backend.rescore_shop_cards(shop_id)`` -- default queue. Reads only the
database (stored daily analytics, products, cards): **no TikTok call, no LLM**,
so Ops may run it any time without the refresh cooldown that guards the
poll-backed ``refresh_action_cards``. It

1. retires live cards whose product is a gift item (``gift_product``), and
2. re-scores pending pre-D29 cards in place with the D29 KPI, "Độ tin cậy" and
   GMV range (``optimize_product_cards.rescore_shop_cards``).

It emits no new card and moves no ``surfaced_at``: the daily diagnosis build
(once a day, after the analytics pass fetched a new day) stays the only writer
of new revisions. Owner runs it on the server, e.g.::

    celery -A juli_backend.workers.celery_app call juli_backend.rescore_shop_cards \\
        --args='["<shop uuid>"]'
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

RESCORE_TASK = "juli_backend.rescore_shop_cards"


async def rescore_shop_cards_async(
    shop_id: uuid.UUID, *, session_factory: Any, now: datetime | None = None
) -> dict[str, Any]:
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.action_cards import rescore_shop_cards

    moment = now or datetime.now(UTC)
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            result = await rescore_shop_cards(session, shop_id, now=moment)
            await session.commit()
    # The counts go in the message too: journald keeps the text, not the extras.
    logger.info(
        "rescore_shop_cards_done shop_id=%s status=%s as_of=%s gift_cards_retired=%s "
        "cards_rescored=%s",
        result.get("shop_id"),
        result.get("status"),
        result.get("as_of", "-"),
        result.get("gift_cards_retired", 0),
        result.get("cards_rescored", 0),
        extra=result,
    )
    return result


@celery_app.task(name=RESCORE_TASK)
def rescore_shop_cards_task(shop_id: str) -> dict[str, Any]:
    """Retire gift cards and re-score pending pre-D29 cards for one shop (DB only)."""
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    return asyncio.run(rescore_shop_cards_async(uuid.UUID(shop_id), session_factory=factory))


__all__ = ["RESCORE_TASK", "rescore_shop_cards_async", "rescore_shop_cards_task"]
