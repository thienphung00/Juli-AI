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
    verifier = TikTokWebhookSignatureVerifier(
        app_key=app_key,
        app_secret=app_secret,
        path=WEBHOOK_PATH,
    )

    def build_service(*, effects: WebhookSideEffects | None) -> TikTokWebhookService:
        return TikTokWebhookService(
            verifier=verifier,
            dispatcher=TikTokWebhookDispatcher(side_effects=effects),
            handoff_fn=handoff_fn,
        )

    default_service = build_service(effects=side_effects)

    app = FastAPI(lifespan=lifespan)

    @app.post(WEBHOOK_PATH)
    async def handle_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        signature = request.headers.get("Authorization")

        if session_factory is not None:
            async with session_factory() as session:
                service = build_service(effects=DatabaseWebhookSideEffects(session))
                result = await service.handle(body=body, signature=signature)
                await session.commit()
        else:
            result = await default_service.handle(body=body, signature=signature)

        return JSONResponse(result.body, status_code=result.status_code)

    return app
