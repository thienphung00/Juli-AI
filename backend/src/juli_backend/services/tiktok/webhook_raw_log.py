"""Fail-safe raw TikTok webhook delivery recorder (#392).

Keeps DB imports out of ``TikTokWebhookService`` via an injected Protocol,
matching the ``handoff_fn`` / ``WebhookSideEffects`` assembly pattern.

What is stored is the delivery reduced to its kind's field allowlist (owner
decision D16, ADR-116 §4; ``webhook_redaction``), never the body as received:
no buyer name, contact, address, message or free text reaches ``raw_body``, and
the ``event_id`` is keyed on the same reduced payload. A ``buyer_id`` is stored
as the shop's pseudonym when the delivery authenticated (``http_status`` 200)
and its shop resolves; otherwise it is dropped.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.repositories.repos import ShopsRepo, WebhookRawEventsRepo
from juli_backend.services.etl.event_id import extract_event_id
from juli_backend.services.privacy.pseudonym import pseudonymize_buyer_ids
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_redaction import (
    allowlist_webhook,
    drop_buyer_ids,
    has_buyer_id,
    parse_webhook_body,
    serialize_stored_body,
)

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
    selected = {key: value for key, value in headers.items() if key.lower() in _HEADER_ALLOWLIST}
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
    kept: dict[str, Any] | None,
    event: TikTokWebhookPayload | None,
    event_type: str | None,
    tiktok_shop_id: str | None,
) -> str | None:
    """The delivery's idempotency key, from the ALLOWLISTED payload only.

    ``extract_event_id`` falls back to the whole ``data`` object when no known id is
    present; keyed on the reduced payload, that fallback cannot copy buyer data into
    the stored ``event_id``.
    """
    parsed = kept
    if parsed is None:
        if event is None:
            return None
        parsed = allowlist_webhook(
            {
                "type": event.type,
                "shop_id": event.shop_id,
                "timestamp": event.timestamp,
                "data": event.data or {},
            }
        )
    shop_key = tiktok_shop_id or (event.shop_id if event else "") or "unknown"
    channel = f"tiktok.raw_log.{event_type or 'unknown'}"
    try:
        return extract_event_id(channel=channel, shop_key=shop_key, payload=drop_buyer_ids(parsed))[
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
        parsed = parse_webhook_body(body)
        kept = allowlist_webhook(parsed) if parsed is not None else None
        event_id = _event_id_for(
            kept=kept,
            event=event,
            event_type=raw_type,
            tiktok_shop_id=tiktok_shop_id,
        )
        raw_body = None
        if kept is not None:
            kept = await self._keyed_buyer_ids(
                kept, tiktok_shop_id, authenticated=http_status == 200
            )
            raw_body = serialize_stored_body(kept)
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

    async def _keyed_buyer_ids(
        self, kept: dict[str, Any], tiktok_shop_id: str | None, *, authenticated: bool
    ) -> dict[str, Any]:
        """``buyer_id`` as the shop's pseudonym, or dropped when the shop is not known.

        Only an authenticated delivery may resolve a shop (an unsigned body must not
        create a pseudonym key); any failure drops the id -- the audit path never
        blocks and never stores the platform id.
        """
        if not has_buyer_id(kept):
            return kept
        if not authenticated or not tiktok_shop_id:
            return drop_buyer_ids(kept)
        try:
            shop_id = await ShopsRepo(self._session).resolve_id_by_tiktok_key(tiktok_shop_id)
            if shop_id is None:
                return drop_buyer_ids(kept)
            async with self._session.begin_nested():
                async with with_shop_scope(self._session, shop_id):
                    return await pseudonymize_buyer_ids(self._session, shop_id, kept)
        except Exception:  # noqa: BLE001 — never block audit path
            logger.warning("webhook_raw_buyer_id_dropped", extra={"tiktok_shop_id": tiktok_shop_id})
            return drop_buyer_ids(kept)
