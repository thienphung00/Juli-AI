"""TikTok webhook request orchestration — verify, parse, dispatch, hand off."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.signature import TikTokWebhookSignatureVerifier
from juli_backend.services.tiktok.webhook_raw_log import RawWebhookEventRecorder

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
        raw_event_recorder: RawWebhookEventRecorder | None = None,
    ) -> None:
        self._verifier = verifier
        self._dispatcher = dispatcher
        self._handoff_fn = handoff_fn
        self._raw_event_recorder = raw_event_recorder

    async def _safe_record(
        self,
        *,
        body: bytes,
        signature: str | None,
        http_status: int,
        processing_status: str,
        event: TikTokWebhookPayload | None,
        headers: Mapping[str, str] | None,
    ) -> None:
        if self._raw_event_recorder is None:
            return
        try:
            await self._raw_event_recorder.record(
                body=body,
                signature=signature,
                http_status=http_status,
                processing_status=processing_status,
                event=event,
                headers=headers,
            )
        except Exception:
            logger.exception(
                "webhook_raw_log_failed",
                extra={
                    "http_status": http_status,
                    "processing_status": processing_status,
                },
            )

    async def handle(
        self,
        *,
        body: bytes,
        signature: str | None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookProcessResult:
        if not signature:
            result = WebhookProcessResult(401, {"error": "Missing signature"})
            await self._safe_record(
                body=body,
                signature=signature,
                http_status=result.status_code,
                processing_status="missing_signature",
                event=None,
                headers=headers,
            )
            return result

        if not self._verifier.verify(body, signature):
            result = WebhookProcessResult(401, {"error": "Invalid signature"})
            await self._safe_record(
                body=body,
                signature=signature,
                http_status=result.status_code,
                processing_status="invalid_signature",
                event=None,
                headers=headers,
            )
            return result

        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            result = WebhookProcessResult(400, {"error": "Malformed JSON"})
            await self._safe_record(
                body=body,
                signature=signature,
                http_status=result.status_code,
                processing_status="malformed_json",
                event=None,
                headers=headers,
            )
            return result

        try:
            event = TikTokWebhookPayload.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            result = WebhookProcessResult(400, {"error": "Missing required fields"})
            await self._safe_record(
                body=body,
                signature=signature,
                http_status=result.status_code,
                processing_status="missing_fields",
                event=None,
                headers=headers,
            )
            return result

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

        result = WebhookProcessResult(200, {"code": 0})
        await self._safe_record(
            body=body,
            signature=signature,
            http_status=result.status_code,
            processing_status=handler_name,
            event=event,
            headers=headers,
        )
        return result
