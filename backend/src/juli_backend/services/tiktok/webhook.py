"""TikTok webhook request orchestration — verify, parse, dispatch, hand off."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.signature import TikTokWebhookSignatureVerifier

logger = logging.getLogger(__name__)

EVENT_CATEGORY_ROUTES: dict[str, str] = {
    "LIVESTREAM": "livestream-events",
    "CREATOR": "creator-events",
    "AFFILIATE": "creator-events",
    "SETTLEMENT": "settlement-events",
}

ACCOUNT_LIFECYCLE_CHANNEL = "tiktok.account.lifecycle"


def should_handoff_to_etl(event_type: str, channel: str) -> bool:
    """Account/platform and deferred events skip ETL ingest."""
    if channel == ACCOUNT_LIFECYCLE_CHANNEL:
        return False
    from juli_backend.services.tiktok.webhook_catalog import is_deferred_webhook_type

    return not is_deferred_webhook_type(event_type)


def resolve_ingest_channel(event_type: str) -> str:
    """Route event to a Phase 2 catalog or legacy category ingest channel."""
    from juli_backend.services.tiktok.webhook_catalog import ingest_channel_for_event

    return ingest_channel_for_event(event_type)


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

        if should_handoff_to_etl(event.type, channel):
            await self._handoff_fn(channel, event.shop_id, body)
        return WebhookProcessResult(200, {"code": 0})
