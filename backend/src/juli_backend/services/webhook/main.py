"""Production ASGI entrypoint for the TikTok webhook receiver."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.core.config.runtime import async_database_url, require_env
from juli_backend.database.database import (
    create_engine,
    create_session_factory,
    init_session_factory,
)
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.webhook.app import create_app

logger = logging.getLogger(__name__)

_session_factory: async_sessionmaker[AsyncSession] | None = None


async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
    logger.error(
        "webhook_etl_dlq",
        extra={
            "channel": channel,
            "shop_key": shop_key,
            "payload_bytes": len(payload),
        },
    )


async def _handoff(channel: str, shop_key: str, payload: bytes) -> None:
    if _session_factory is None:
        raise RuntimeError("Webhook session factory is not configured")

    async with _session_factory() as session:
        consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
        await consumer.ingest(
            IngestRecord(channel=channel, shop_key=shop_key, value=payload)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session_factory

    database_url = async_database_url(require_env("DATABASE_URL"))
    require_env("TIKTOK_APP_KEY")
    require_env("TIKTOK_APP_SECRET")

    engine = create_engine(database_url)
    _session_factory = create_session_factory(engine)
    init_session_factory(_session_factory)
    logger.info("webhook_startup_complete")
    try:
        yield
    finally:
        _session_factory = None
        await engine.dispose()
        logger.info("webhook_shutdown_complete")


app = create_app(
    app_key=os.environ.get("TIKTOK_APP_KEY", ""),
    app_secret=os.environ.get("TIKTOK_APP_SECRET", ""),
    handoff_fn=_handoff,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
