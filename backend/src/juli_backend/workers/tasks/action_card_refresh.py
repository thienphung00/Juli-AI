"""Celery task entrypoint for manual action-card refresh (#303)."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import init_session_factory
from juli_backend.services.action_cards.refresh import run_action_card_refresh
from juli_backend.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import create_session_factory

    engine = create_async_engine(_database_url())
    factory = create_session_factory(engine)
    init_session_factory(factory)
    return factory


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
