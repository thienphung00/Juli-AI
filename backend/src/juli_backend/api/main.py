"""Production ASGI entrypoint for the Juli REST API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from juli_backend.api.app import create_app
from juli_backend.core.config.runtime import async_database_url, cors_allow_origins, require_env
from juli_backend.core.observability import configure_logging
from juli_backend.database.database import (
    create_engine,
    create_session_factory,
    init_session_factory,
)
from juli_backend.workers.agent_runtime_boot import assert_agent_runtime_config

# Before anything else can emit. Until #902 the root logger had no handler, so Python's
# last-resort handler took over at WARNING-and-above with a message-only format — every
# logger.info audit call site in this codebase was discarded, and every extra={...}
# payload on the warnings that did print was built and thrown away.
configure_logging()

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

    # ADR-061 "Startup assertions (fail to boot)" / issue #926: a missing
    # SUPABASE_JWT_SECRET must fail the process at boot rather than let it
    # serve /health 200 and 500 on the first authenticated request. The
    # per-request check in core/security/dependencies.py:get_current_user
    # stays in place as defence in depth.
    require_env("SUPABASE_JWT_SECRET")

    # ADR-075 decision 3 / #1217: the consolidated six-check boot assertion.
    # Placed after the SUPABASE_JWT_SECRET check above rather than replacing
    # it -- that existing call keeps its own exact message/behaviour
    # (test_api_main.py pins it), and by the time this line runs the secret
    # is already guaranteed present, so this call's own check 5 is always a
    # trivial pass here; it still fires for real when this lifespan is the
    # only caller (e.g. a future refactor removes the line above). `app` is
    # passed so check 6 (zero unauthenticated agent-run routes in a
    # production-write-capable deployment) can walk the real route table;
    # `broker_url` is omitted so it falls back to reading CELERY_BROKER_URL
    # directly, since the API process never constructs a Celery app.
    assert_agent_runtime_config(app=app)

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
