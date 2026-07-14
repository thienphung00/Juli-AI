"""TikTok Shop webhook receiver — FastAPI application factory.

Validates HMAC-SHA256 signatures, parses the event, dispatches through the Phase 2
catalog, and hands validated payloads to the ingest pipeline (ETL) via an injected
``handoff_fn``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.services.tiktok import (
    TikTokWebhookDispatcher,
    TikTokWebhookService,
    TikTokWebhookSignatureVerifier,
)
from juli_backend.services.tiktok.webhook_handlers import (
    DatabaseWebhookSideEffects,
    WebhookSideEffects,
)

WEBHOOK_PATH = "/webhooks/tiktok"
SessionFactory = async_sessionmaker[AsyncSession]


def build_webhook_service(
    *,
    app_key: str,
    app_secret: str,
    handoff_fn: HandoffFn,
    side_effects: WebhookSideEffects | None = None,
) -> TikTokWebhookService:
    """Assemble the signature verifier, catalog dispatcher, and ETL handoff.

    Shared by the standalone webhook app (`create_app`) and any other ASGI
    application that mounts the same ``WEBHOOK_PATH`` route (see
    ``juli_backend.api.routes.webhook_tiktok``), so both entrypoints verify and
    dispatch identically without duplicating the assembly logic.
    """
    verifier = TikTokWebhookSignatureVerifier(
        app_key=app_key,
        app_secret=app_secret,
        path=WEBHOOK_PATH,
    )
    return TikTokWebhookService(
        verifier=verifier,
        dispatcher=TikTokWebhookDispatcher(side_effects=side_effects),
        handoff_fn=handoff_fn,
    )


def create_app(
    *,
    app_key: str,
    app_secret: str,
    handoff_fn: HandoffFn,
    lifespan: Any | None = None,
    session_factory: SessionFactory | None = None,
    side_effects: WebhookSideEffects | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to the given ingest handoff function."""
    default_service = build_webhook_service(
        app_key=app_key,
        app_secret=app_secret,
        handoff_fn=handoff_fn,
        side_effects=side_effects,
    )

    app = FastAPI(lifespan=lifespan)

    @app.post(WEBHOOK_PATH)
    async def handle_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        signature = request.headers.get("Authorization")

        if session_factory is not None:
            async with session_factory() as session:
                service = build_webhook_service(
                    app_key=app_key,
                    app_secret=app_secret,
                    handoff_fn=handoff_fn,
                    side_effects=DatabaseWebhookSideEffects(session),
                )
                result = await service.handle(body=body, signature=signature)
                await session.commit()
        else:
            result = await default_service.handle(body=body, signature=signature)

        return JSONResponse(result.body, status_code=result.status_code)

    return app
