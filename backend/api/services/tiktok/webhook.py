"""TikTok webhook request orchestration — verify, parse, dispatch, hand off."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from backend.api.services.tiktok.dispatcher import TikTokWebhookDispatcher
from backend.api.services.tiktok.schemas import TikTokWebhookPayload
from backend.api.services.tiktok.signature import TikTokWebhookSignatureVerifier
from backend.integrations.ordering.api.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)

EVENT_CATEGORY_ROUTES: dict[str, str] = {
    "LIVESTREAM": "livestream-events",
    "CREATOR": "creator-events",
    "AFFILIATE": "creator-events",
    "SETTLEMENT": "settlement-events",
}


def resolve_ingest_channel(event_type: str) -> str:
    """Route event to a category ingest channel by prefix, falling back to generic."""
    upper = event_type.upper()
    for prefix, channel in EVENT_CATEGORY_ROUTES.items():
        if upper.startswith(prefix):
            return channel
    return f"tiktok.{event_type.lower()}"


@dataclass
class WebhookProcessResult:
    status_code: int
    body: dict[str, Any]


class TikTokWebhookService:
    """Coordinates signature verification, dispatch, and ingest handoff."""

    def __init__(
        self,
        *,
        verifier: TikTokWebhookSignatureVerifier,
        dispatcher: TikTokWebhookDispatcher,
        handoff_fn: HandoffFn,
    ) -> None:
        self._verifier = verifier
        self._dispatcher = dispatcher
        self._handoff_fn = handoff_fn

    async def handle(
        self,
        *,
        body: bytes,
        signature: str | None,
    ) -> WebhookProcessResult:
        if not signature:
            return WebhookProcessResult(401, {"error": "Missing signature"})

        if not self._verifier.verify(body, signature):
            return WebhookProcessResult(401, {"error": "Invalid signature"})

        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return WebhookProcessResult(400, {"error": "Malformed JSON"})

        try:
            event = TikTokWebhookPayload.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return WebhookProcessResult(400, {"error": "Missing required fields"})

        handler_name = await self._dispatcher.dispatch(event)
        channel = resolve_ingest_channel(event.type)

        logger.info(
            "webhook_event_received",
            extra={
                "event_type": event.type,
                "shop_id": event.shop_id,
                "channel": channel,
                "handler": handler_name,
            },
        )

        await self._handoff_fn(channel, event.shop_id, body)
        return WebhookProcessResult(200, {"code": 0})
