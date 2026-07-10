"""TikTok Shop webhook receiver — FastAPI application factory.

Validates HMAC-SHA256 signatures, parses the event, dispatches to stub handlers,
and hands the raw payload to the ingest pipeline (ETL) via an injected
``handoff_fn``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from juli_backend.services.tiktok import (
    TikTokWebhookDispatcher,
    TikTokWebhookService,
    TikTokWebhookSignatureVerifier,
)
from juli_backend.services.ingestion.handoff import HandoffFn

WEBHOOK_PATH = "/webhooks/tiktok"


def create_app(
    *,
    app_key: str,
    app_secret: str,
    handoff_fn: HandoffFn,
    lifespan: Any | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to the given ingest handoff function."""
    webhook_service = TikTokWebhookService(
        verifier=TikTokWebhookSignatureVerifier(
            app_key=app_key,
            app_secret=app_secret,
            path=WEBHOOK_PATH,
        ),
        dispatcher=TikTokWebhookDispatcher(),
        handoff_fn=handoff_fn,
    )

    app = FastAPI(lifespan=lifespan)

    @app.post(WEBHOOK_PATH)
    async def handle_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        result = await webhook_service.handle(
            body=body,
            signature=request.headers.get("Authorization"),
        )
        return JSONResponse(result.body, status_code=result.status_code)

    return app
