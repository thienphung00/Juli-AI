"""Fail-safe raw TikTok webhook delivery recorder (#392).

Keeps DB imports out of ``TikTokWebhookService`` via an injected Protocol,
matching the ``handoff_fn`` / ``WebhookSideEffects`` assembly pattern.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import WebhookRawEventsRepo
from juli_backend.services.etl.event_id import extract_event_id
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_redaction import redact_webhook_body

logger = logging.getLogger(__name__)

PARSE_VERSION = 1
_HEADER_ALLOWLIST = frozenset({"content-type", "user-agent"})


class RawWebhookEventRecorder(Protocol):
    async def record(
        self,
        *,
        body: bytes,
        signature: str | None,
        http_status: int,
        processing_status: str,
        event: TikTokWebhookPayload | None,
        headers: Mapping[str, str] | None = None,
    ) -> None: ...


def _allowlisted_headers_json(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    selected = {
        key: value
        for key, value in headers.items()
        if key.lower() in _HEADER_ALLOWLIST
    }
    if not selected:
        return None
    return json.dumps(selected, sort_keys=True)


def _raw_type_and_shop(body: bytes) -> tuple[str | None, str | None]:
    """Extract delivered ``type`` / shop key before catalog normalization."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None, None
    if not isinstance(parsed, dict):
        return None, None

    event_type = parsed.get("type")
    raw_type = str(event_type)[:100] if event_type is not None else None

    shop = parsed.get("shop_id")
    if shop is None or not str(shop).strip():
        data = parsed.get("data")
        if isinstance(data, dict):
            shop = data.get("seller_id") or data.get("shop_id")
    tiktok_shop_id = str(shop)[:100] if shop is not None and str(shop).strip() else None
    return raw_type, tiktok_shop_id


def _event_id_for(
    *,
    body: bytes,
    event: TikTokWebhookPayload | None,
    event_type: str | None,
    tiktok_shop_id: str | None,
) -> str | None:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        if event is None:
            return None
        parsed = {
            "type": event.type,
            "shop_id": event.shop_id,
            "timestamp": event.timestamp,
            "data": event.data or {},
        }
    shop_key = tiktok_shop_id or (event.shop_id if event else "") or "unknown"
    channel = f"tiktok.raw_log.{event_type or 'unknown'}"
    try:
        return extract_event_id(channel=channel, shop_key=shop_key, payload=parsed)[
            :255
        ]
    except Exception:  # noqa: BLE001 — never block audit path
        return None


class DatabaseRawWebhookEventRecorder:
    """Persist a redacted raw delivery using a nested transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = WebhookRawEventsRepo(session)

    async def record(
        self,
        *,
        body: bytes,
        signature: str | None,
        http_status: int,
        processing_status: str,
        event: TikTokWebhookPayload | None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        raw_type, tiktok_shop_id = _raw_type_and_shop(body)
        if event is not None:
            tiktok_shop_id = tiktok_shop_id or event.shop_id
        raw_body = redact_webhook_body(body)
        event_id = _event_id_for(
            body=body,
            event=event,
            event_type=raw_type,
            tiktok_shop_id=tiktok_shop_id,
        )
        async with self._session.begin_nested():
            await self._repo.insert(
                tiktok_shop_id=tiktok_shop_id,
                event_type=raw_type,
                event_id=event_id,
                signature_header=signature,
                headers=_allowlisted_headers_json(headers),
                raw_body=raw_body,
                http_status=http_status,
                processing_status=processing_status[:50],
                parse_version=PARSE_VERSION,
            )
