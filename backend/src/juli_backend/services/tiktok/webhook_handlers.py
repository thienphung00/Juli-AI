"""Side-effect handlers for Phase 2 webhook catalog dispatch."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope, with_tenant_scope
from juli_backend.models.models import Shop
from juli_backend.repositories.repos import ShopsRepo, WorkflowWebhookSignalsRepo
from juli_backend.services.etl.event_id import extract_event_id
from juli_backend.services.privacy.payload_allowlist import TIKTOK
from juli_backend.services.privacy.raw_payload import sanitize_raw_payload
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import HISTORY_CATALOG_IDS, CatalogEntry
from juli_backend.services.tiktok.webhook_redaction import webhook_endpoint

#: History types new in P23 whose signal is keyed on ``tts_notification_id`` (39
#: keeps its existing key so already-recorded signals stay deduplicated).
HISTORY_NOTIFICATION_KEYED_IDS: frozenset[int] = frozenset({15, 16, 18, 63})

logger = logging.getLogger(__name__)


class WebhookSideEffects(Protocol):
    async def on_catalog_event(
        self, *, entry: CatalogEntry, event: TikTokWebhookPayload
    ) -> None: ...


@dataclass
class NoopWebhookSideEffects:
    """Test/default side effects — no durable writes."""

    async def on_catalog_event(self, *, entry: CatalogEntry, event: TikTokWebhookPayload) -> None:
        return None


@dataclass
class DatabaseWebhookSideEffects:
    """Persist workflow signals and account lifecycle actions for catalog webhooks."""

    session: AsyncSession

    async def on_catalog_event(self, *, entry: CatalogEntry, event: TikTokWebhookPayload) -> None:
        """Resolve the event's shop across tenants, then act only under that shop's scope.

        P69 (E12): a webhook holds no tenant scope, and as ``juli_app`` an unscoped ``shops``
        read returns nothing, so every catalog event -- the deauthorization among them -- was
        a "shop not found". The shop is resolved by either TikTok identifier through
        migration 102's definer function (the E11 order path's shape), and every read and
        write after it runs under ``with_shop_scope``. An unknown shop is logged and dropped;
        there is no unscoped fallback.
        """
        shops = ShopsRepo(self.session)
        shop_id = await shops.resolve_id_by_tiktok_key(event.shop_id)
        if shop_id is None:
            logger.warning(
                "webhook_shop_not_found",
                extra={"tiktok_shop_id": event.shop_id, "catalog_id": entry.catalog_id},
            )
            return
        async with with_shop_scope(self.session, shop_id):
            await self._apply_for_shop(shops, shop_id, entry, event)

    async def _apply_for_shop(
        self,
        shops: ShopsRepo,
        shop_id: uuid.UUID,
        entry: CatalogEntry,
        event: TikTokWebhookPayload,
    ) -> None:
        if entry.catalog_id == 6:
            intent = "pause_automation"
        elif entry.catalog_id == 7:
            intent = "re_auth_required"
        else:
            intent = "workflow_gate"

        # D16 / ADR-116 §4: the signal keeps the delivery reduced to its kind's
        # allowlist (``webhook_redaction``), ``buyer_id`` as the shop's pseudonym --
        # never ``event.data`` as received. No reader parses ``payload`` back; the
        # dedup ``event_id`` is keyed on the same reduced payload, so its
        # whole-``data`` fallback cannot carry buyer fields into the column either.
        delivered = {
            "type": event.type,
            "shop_id": event.shop_id,
            "timestamp": event.timestamp,
            "data": event.data or {},
        }
        if event.notification_id:
            delivered["tts_notification_id"] = event.notification_id
        payload = await sanitize_raw_payload(
            self.session,
            shop_id,
            platform=TIKTOK,
            endpoint=webhook_endpoint(event.type),
            payload=delivered,
        )
        event_id = extract_event_id(
            channel=entry.etl_channel,
            shop_key=event.shop_id,
            payload=payload,
        )
        if entry.catalog_id in HISTORY_NOTIFICATION_KEYED_IDS and event.notification_id:
            # Fast track P23 (D30.4): idempotent by TikTok's notification id.
            event_id = f"ttsn:{event.notification_id}"
        signals = WorkflowWebhookSignalsRepo(self.session)
        stored = await signals.record_if_new(
            shop_id=shop_id,
            tiktok_shop_id=event.shop_id,
            catalog_id=entry.catalog_id,
            event_type=event.type,
            workflow_keys=list(entry.workflow_keys),
            intent=intent,
            event_id=event_id,
            payload_json=json.dumps(payload, sort_keys=True, default=str),
        )
        if entry.catalog_id == 6 and (stored or _unidentifiable(event)):
            # A deauthorization with neither a timestamp nor a notification id has no
            # identity of its own: a later, real deauthorization keys the same as the first,
            # so it still pauses (idempotent) rather than being taken for a redelivery.
            await self._pause_automation(shops, shop_id, event)
        if not stored:
            # P72: a redelivery (TikTok retry, or a concurrent copy) of an event already
            # recorded is a no-op -- no second history read, and (above) no second pause
            # for a deauthorization that carries its own identity.
            logger.info(
                "webhook_signal_duplicate",
                extra={"shop_id": str(shop_id), "catalog_id": entry.catalog_id},
            )
            return
        if entry.catalog_id in HISTORY_CATALOG_IDS:
            self._enqueue_history(shop_id, entry, event)

    async def _pause_automation(
        self, shops: ShopsRepo, shop_id: uuid.UUID, event: TikTokWebhookPayload
    ) -> None:
        """Pause the deauthorizing shop, under its owner's tenant scope (P69, E12).

        Called inside the shop's scope, where the shop can read its own row
        (``shops_shop_scope_select``, migration 053) but not update it: ``shops``' UPDATE
        policy is keyed on the USER (045). The owner is read from that one row, and the
        UPDATE runs under the (shop, owner) pair -- the same authority the seller's own
        request would carry, and nothing wider. If the row cannot be read the delivery
        fails loudly rather than reporting a pause that did not happen.
        """
        shop = await self.session.get(Shop, shop_id)
        if shop is None:
            logger.error(
                "webhook_deauthorization_shop_unreadable",
                extra={"shop_id": str(shop_id), "tiktok_shop_id": event.shop_id},
            )
            raise LookupError(f"shop {shop_id} unreadable under its own scope")
        async with with_tenant_scope(self.session, shop_id, shop.user_id):
            await shops.pause_automation(shop_id)
        logger.info(
            "webhook_deauthorization_paused",
            extra={"shop_id": str(shop_id), "tiktok_shop_id": event.shop_id},
        )

    @staticmethod
    def _enqueue_history(shop_id: object, entry: CatalogEntry, event: TikTokWebhookPayload) -> None:
        """Fast track P23 (D30.4): re-read the product / activity for the history tables."""
        from juli_backend.services.product_history.webhooks import enqueue_work, history_work_for

        work = history_work_for(entry.catalog_id, event.shop_id, event.data)
        if work is None:
            logger.info(
                "product_history_webhook_without_subject",
                extra={"catalog_id": entry.catalog_id, "tiktok_shop_id": event.shop_id},
            )
            return
        enqueue_work(str(shop_id), work)


def _unidentifiable(event: TikTokWebhookPayload) -> bool:
    """Whether the delivery carries nothing that tells one push of its kind from the next."""
    return event.timestamp is None and not event.notification_id
