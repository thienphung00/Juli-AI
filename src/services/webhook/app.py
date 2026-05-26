"""TikTok Shop webhook receiver — FastAPI application factory.

Validates HMAC-SHA256 signatures, parses the event, and publishes the
raw payload to a Kafka topic derived from the event type.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

PublishFn = Callable[[str, str, bytes], Awaitable[None]]

EVENT_CATEGORY_ROUTES: dict[str, str] = {
    "LIVESTREAM": "livestream-events",
    "CREATOR": "creator-events",
    "AFFILIATE": "creator-events",
    "SETTLEMENT": "settlement-events",
}


def _resolve_topic(event_type: str) -> str:
    """Route event to a category topic by prefix, falling back to generic."""
    upper = event_type.upper()
    for prefix, topic in EVENT_CATEGORY_ROUTES.items():
        if upper.startswith(prefix):
            return topic
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
    publish_fn: PublishFn,
) -> FastAPI:
    """Build a FastAPI app wired to the given Kafka publish function."""

    app = FastAPI()

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

        topic = _resolve_topic(event_type)

        logger.info(
            "webhook_event_received",
            extra={"event_type": event_type, "shop_id": shop_id, "topic": topic},
        )

        await publish_fn(topic, shop_id, body)

        return JSONResponse({"code": 0}, status_code=200)

    return app
