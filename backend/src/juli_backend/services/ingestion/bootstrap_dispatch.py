"""Enqueue a shop's bootstrap after it connects (fast track SPEC §3.1, AC-1.1).

A port, like ``services/action_cards/dispatch.py``: the OAuth callback lives in
``services`` and may not import ``workers``, so the Celery adapter is bound at
startup by ``workers/dispatch_binding.py``.

``enqueue_shop_bootstrap`` NEVER RAISES. It runs after the callback's commit,
when the shop and its credential are already durable; failing the callback now
would show the seller an error for a connect that succeeded. A shop whose
enqueue failed is not lost either -- the per-shop fan-out beat enqueues
``bootstrap_shop`` for every shop without a completed fast phase.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

logger = logging.getLogger(__name__)


class BootstrapDispatcher(Protocol):
    def enqueue(
        self,
        shop_id: str,
        *,
        connect_committed_at: str | None,
        enqueued_at: str | None,
    ) -> str: ...


_bootstrap_dispatcher: BootstrapDispatcher | None = None


def set_bootstrap_dispatcher(dispatcher: BootstrapDispatcher | None) -> None:
    global _bootstrap_dispatcher
    _bootstrap_dispatcher = dispatcher


def get_bootstrap_dispatcher() -> BootstrapDispatcher | None:
    return _bootstrap_dispatcher


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def enqueue_shop_bootstrap(
    shop_id: uuid.UUID,
    *,
    connect_committed_at: datetime | None = None,
) -> str | None:
    """Enqueue ``bootstrap_shop(shop_id)``; return the task id, or ``None`` on failure."""
    enqueued_at = _now_naive()
    dispatcher = _bootstrap_dispatcher
    if dispatcher is None:
        logger.error(
            "shop_bootstrap_enqueue_failed",
            extra={"shop_id": str(shop_id), "reason": "dispatcher_not_bound"},
        )
        return None
    try:
        task_id = dispatcher.enqueue(
            str(shop_id),
            connect_committed_at=(
                connect_committed_at.isoformat() if connect_committed_at is not None else None
            ),
            enqueued_at=enqueued_at.isoformat(),
        )
    except Exception as exc:
        logger.error(
            "shop_bootstrap_enqueue_failed",
            extra={
                "shop_id": str(shop_id),
                "reason": "enqueue_raised",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
            },
            exc_info=True,
        )
        return None
    seconds = (
        round((enqueued_at - connect_committed_at).total_seconds(), 3)
        if connect_committed_at is not None
        else None
    )
    logger.info(
        "shop_bootstrap_enqueued",
        extra={
            "shop_id": str(shop_id),
            "task_id": task_id,
            "at": enqueued_at.isoformat(),
            "seconds_since_connect": seconds,
        },
    )
    return task_id


__all__ = [
    "BootstrapDispatcher",
    "enqueue_shop_bootstrap",
    "get_bootstrap_dispatcher",
    "set_bootstrap_dispatcher",
]
