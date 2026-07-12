"""Celery task entrypoint for approved tool execution (#305)."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import init_session_factory
from juli_backend.services.execution.worker import run_approved_tool
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


async def _execute_async(execution_id: uuid.UUID) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        await run_approved_tool(session, execution_id)


def execute_approved_tool_sync(execution_id: str) -> None:
    asyncio.run(_execute_async(uuid.UUID(execution_id)))


@celery_app.task(name="juli_backend.execute_approved_tool")
def execute_approved_tool(execution_id: str) -> None:
    """Run an approved tool call outside the HTTP request cycle."""
    execute_approved_tool_sync(execution_id)
