"""Replay stored raw webhook deliveries of the history types (D30.4, one-off).

Before P23, webhooks 15 / 16 / 18 / 63 were acknowledged (200) and only stored
in ``webhook_raw_events`` (redacted). ``replay_raw_events`` walks those rows
(oldest first) and sends each through the same side effect a live delivery
now takes (``DatabaseWebhookSideEffects``): the signal is recorded once per
notification and a first-time signal enqueues the product / activity re-read.
Running it twice enqueues nothing new.

The re-read sees TODAY's product: a change from a replayed event that a later
change overwrote is recorded as the difference between the latest snapshot and
today, dated by TikTok's ``update_time`` -- the event itself only says which
product to look at.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import WebhookRawEvent
from juli_backend.repositories.repos import ShopsRepo
from juli_backend.services.product_history.webhooks import RAW_EVENT_TYPES
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects

logger = logging.getLogger(__name__)


@dataclass
class ReplayResult:
    scanned: int = 0
    replayed: int = 0
    unparseable: int = 0
    unknown_shop: int = 0


async def replay_raw_events(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    limit: int = 5000,
    side_effects: Any | None = None,
) -> ReplayResult:
    """Replay up to ``limit`` stored 200-acknowledged deliveries of the history types."""
    effects = side_effects or DatabaseWebhookSideEffects(session)
    result = ReplayResult()
    stmt = (
        select(WebhookRawEvent)
        .where(
            WebhookRawEvent.event_type.in_(RAW_EVENT_TYPES),
            WebhookRawEvent.http_status == 200,
            WebhookRawEvent.raw_body.is_not(None),
        )
        .order_by(WebhookRawEvent.received_at, WebhookRawEvent.id)
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(WebhookRawEvent.received_at >= since)
    rows = list((await session.execute(stmt)).scalars())
    for row in rows:
        result.scanned += 1
        try:
            event = TikTokWebhookPayload.from_dict(json.loads(row.raw_body or ""))
        except (ValueError, KeyError, TypeError):
            result.unparseable += 1
            continue
        entry = resolve_catalog_entry(event.type)
        if entry is None:
            result.unparseable += 1
            continue
        # P69 (E12): the replay holds no tenant scope, so the shop is resolved across
        # tenants (migration 102's definer function, either TikTok identifier); an
        # unscoped `shops` read as `juli_app` would see no shop at all.
        shop_id = await ShopsRepo(session).resolve_id_by_tiktok_key(event.shop_id)
        if shop_id is None:
            logger.warning(
                "product_history_replay_unknown_shop",
                extra={"tiktok_shop_id": event.shop_id, "event_type": event.type},
            )
            result.unknown_shop += 1
            continue
        # The signal row is a tenant row: write it under the shop's scope.
        async with with_shop_scope(session, shop_id):
            await effects.on_catalog_event(entry=entry, event=event)
        result.replayed += 1
    logger.info("product_history_replay", extra=result.__dict__)
    return result


__all__ = ["ReplayResult", "replay_raw_events"]
