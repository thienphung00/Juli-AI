"""Celery task entrypoint for manual action-card refresh (#303)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.services.action_cards.refresh import run_action_card_refresh
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _refresh_async(shop_id: uuid.UUID) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        await run_action_card_refresh(session, shop_id)
        await session.commit()


def refresh_action_cards_sync(shop_id: str) -> None:
    asyncio.run(_refresh_async(uuid.UUID(shop_id)))


@celery_app.task(name="juli_backend.refresh_action_cards")
def refresh_action_cards(shop_id: str) -> None:
    """Run poll → scoring → persist outside the HTTP request cycle."""
    refresh_action_cards_sync(shop_id)
