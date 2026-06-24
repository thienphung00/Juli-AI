"""Production ASGI entrypoint for the Juli REST API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.apps.api_gateway.api.app import create_app
from src.apps.runtime import async_database_url, cors_allow_origins, require_env
from src.shared.utils.data.database import (
    create_engine,
    create_session_factory,
    init_session_factory,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = async_database_url(require_env("DATABASE_URL"))
    engine = create_engine(database_url)
    init_session_factory(create_session_factory(engine))
    logger.info("api_startup_complete")
    try:
        yield
    finally:
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
