"""TikTok webhook event dispatcher — routes Phase 2 catalog events to handlers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import (
    CatalogEntry,
    is_deferred_webhook_type,
    resolve_catalog_entry,
)
from juli_backend.services.tiktok.webhook_handlers import (
    NoopWebhookSideEffects,
    WebhookSideEffects,
)

logger = logging.getLogger(__name__)

EventHandler = Callable[[TikTokWebhookPayload, CatalogEntry], Awaitable[None]]


async def _handle_catalog_event(
    event: TikTokWebhookPayload,
    entry: CatalogEntry,
    *,
    side_effects: WebhookSideEffects,
) -> None:
    logger.info(
        "tiktok_webhook_catalog_event",
        extra={
            "catalog_id": entry.catalog_id,
            "handler": entry.handler_name,
            "shop_id": event.shop_id,
            "event_type": event.type,
            "workflows": list(entry.workflow_keys),
        },
    )
    await side_effects.on_catalog_event(entry=entry, event=event)


async def _handle_deferred_event(event: TikTokWebhookPayload) -> None:
    logger.info(
        "tiktok_webhook_deferred_out_of_scope",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


async def _handle_unknown_event(event: TikTokWebhookPayload) -> None:
    logger.info(
        "tiktok_webhook_unknown_event",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


class TikTokWebhookDispatcher:
    """Dispatch parsed webhook events to Phase 2 catalog handlers."""

    def __init__(self, *, side_effects: WebhookSideEffects | None = None) -> None:
        self._side_effects = side_effects or NoopWebhookSideEffects()

    async def dispatch(self, event: TikTokWebhookPayload) -> str:
        """Route *event* to a handler and return the handler name."""
        if is_deferred_webhook_type(event.type):
            await _handle_deferred_event(event)
            return "deferred_out_of_scope"

        entry = resolve_catalog_entry(event.type)
        if entry is not None:
            await _handle_catalog_event(event, entry, side_effects=self._side_effects)
            return entry.handler_name

        await _handle_unknown_event(event)
        return "unknown_event"

    def register_handler(self, name: str, handler: EventHandler) -> None:
        """Extension point retained for future catalog types."""
        _ = (name, handler)
