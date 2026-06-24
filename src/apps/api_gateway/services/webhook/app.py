"""TikTok Shop webhook receiver — FastAPI application factory.

Validates HMAC-SHA256 signatures, parses the event, and hands the raw payload
to the ingest pipeline (ETL) via an injected ``handoff_fn``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.modules.ordering.api.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)

# Deprecated alias — same contract as ``HandoffFn``.
PublishFn = Callable[[str, str, bytes], Awaitable[None]]

EVENT_CATEGORY_ROUTES: dict[str, str] = {
    "LIVESTREAM": "livestream-events",
    "CREATOR": "creator-events",
    "AFFILIATE": "creator-events",
    "SETTLEMENT": "settlement-events",
}


def _resolve_channel(event_type: str) -> str:
    """Route event to a category channel by prefix, falling back to generic."""
    upper = event_type.upper()
    for prefix, channel in EVENT_CATEGORY_ROUTES.items():
        if upper.startswith(prefix):
            return channel
    return f"tiktok.{event_type.lower()}"


def _verify_signature(
    app_key: str, app_secret: str, path: str, body: bytes, received_sig: str
) -> bool:
    sign_string = f"{app_key}{path}{body.decode()}"
    expected = hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)


def create_app(
    *,
    app_key: str,
    app_secret: str,
    handoff_fn: HandoffFn | None = None,
    publish_fn: HandoffFn | None = None,
    lifespan: Any | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to the given ingest handoff function."""
    resolved_handoff = handoff_fn or publish_fn
    if resolved_handoff is None:
        raise TypeError("create_app requires handoff_fn= or publish_fn=")

    app = FastAPI(lifespan=lifespan)

    @app.post("/webhooks/tiktok")
    async def handle_webhook(request: Request) -> JSONResponse:
        body = await request.body()

        signature = request.headers.get("Authorization")
        if not signature:
            return JSONResponse({"error": "Missing signature"}, status_code=401)

        if not _verify_signature(app_key, app_secret, "/webhooks/tiktok", body, signature):
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

        try:
            event = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "Malformed JSON"}, status_code=400)

        event_type = event.get("type")
        shop_id = event.get("shop_id")
        if not event_type or not shop_id:
            return JSONResponse({"error": "Missing required fields"}, status_code=400)

        channel = _resolve_channel(event_type)

        logger.info(
            "webhook_event_received",
            extra={"event_type": event_type, "shop_id": shop_id, "channel": channel},
        )

        await resolved_handoff(channel, shop_id, body)

        return JSONResponse({"code": 0}, status_code=200)

    return app
