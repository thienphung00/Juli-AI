"""Production ASGI entrypoint for the Juli REST API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from juli_backend.api.app import create_app
from juli_backend.core.config.runtime import async_database_url, cors_allow_origins, require_env
from juli_backend.database.database import (
    create_engine,
    create_session_factory,
    init_session_factory,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from juli_backend.services.action_cards import bind_action_card_refresh_cooldown_gate
    from juli_backend.services.analytics_kpi_cache import (
        close_shared_redis_client,
        get_shared_redis_client,
    )
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    bind_celery_dispatchers()
    # ADR-061 §2b: the per-shop refresh cooldown fails closed when REDIS_URL
    # is unset — unlike the cache warm below, it must not go fail-open.
    bind_action_card_refresh_cooldown_gate()

    database_url = async_database_url(require_env("DATABASE_URL"))
    engine = create_engine(database_url)
    init_session_factory(create_session_factory(engine))
    # Warm shared Redis client when REDIS_URL is set (fail-open if unset).
    get_shared_redis_client()
    logger.info("api_startup_complete")
    try:
        yield
    finally:
        await close_shared_redis_client()
        await engine.dispose()
        logger.info("api_shutdown_complete")


app = create_app(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
