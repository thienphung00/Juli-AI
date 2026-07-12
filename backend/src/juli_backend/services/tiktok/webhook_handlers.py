"""Side-effect handlers for Phase 2 webhook catalog dispatch."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ShopsRepo, WorkflowWebhookSignalsRepo
from juli_backend.services.etl.event_id import extract_event_id
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import CatalogEntry

logger = logging.getLogger(__name__)


class WebhookSideEffects(Protocol):
    async def on_catalog_event(
        self, *, entry: CatalogEntry, event: TikTokWebhookPayload
    ) -> None: ...


@dataclass
class NoopWebhookSideEffects:
    """Test/default side effects — no durable writes."""

    async def on_catalog_event(
        self, *, entry: CatalogEntry, event: TikTokWebhookPayload
    ) -> None:
        return None


@dataclass
class DatabaseWebhookSideEffects:
    """Persist workflow signals and account lifecycle actions for catalog webhooks."""

    session: AsyncSession

    async def on_catalog_event(
        self, *, entry: CatalogEntry, event: TikTokWebhookPayload
    ) -> None:
        shops = ShopsRepo(self.session)
        shop = await shops.get_by_tiktok_id(event.shop_id)
        if shop is None:
            logger.warning(
                "webhook_shop_not_found",
                extra={"tiktok_shop_id": event.shop_id, "catalog_id": entry.catalog_id},
            )
            return

        if entry.catalog_id == 6:
            await shops.pause_automation(shop.id)
            intent = "pause_automation"
        elif entry.catalog_id == 7:
            intent = "re_auth_required"
        else:
            intent = "workflow_gate"

        payload = {
            "type": event.type,
            "shop_id": event.shop_id,
            "timestamp": event.timestamp,
            "data": event.data or {},
        }
        event_id = extract_event_id(
            channel=entry.etl_channel,
            shop_key=event.shop_id,
            payload=payload,
        )
        signals = WorkflowWebhookSignalsRepo(self.session)
        await signals.record_if_new(
            shop_id=shop.id,
            tiktok_shop_id=event.shop_id,
            catalog_id=entry.catalog_id,
            event_type=event.type,
            workflow_keys=list(entry.workflow_keys),
            intent=intent,
            event_id=event_id,
            payload_json=json.dumps(payload, sort_keys=True, default=str),
        )
