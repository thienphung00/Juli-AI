"""Enqueue action-card refresh to Celery — HTTP handlers must not run inline."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class RefreshDispatcher(Protocol):
    def enqueue(self, shop_id: str) -> str: ...


_refresh_dispatcher: RefreshDispatcher | None = None


def get_refresh_dispatcher() -> RefreshDispatcher:
    if _refresh_dispatcher is None:
        raise RuntimeError(
            "Action card refresh dispatcher is not bound; call bind_celery_dispatchers() at startup"
        )
    return _refresh_dispatcher


def set_refresh_dispatcher(dispatcher: RefreshDispatcher | None) -> None:
    global _refresh_dispatcher
    _refresh_dispatcher = dispatcher


async def enqueue_action_card_refresh(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
) -> str:
    """Enqueue refresh for *shop_id* and return the Celery task id."""
    del session  # refresh is fully async via worker; HTTP only enqueues
    return get_refresh_dispatcher().enqueue(str(shop_id))
