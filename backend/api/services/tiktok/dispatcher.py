"""TikTok webhook event dispatcher — routes events to stub handlers by type.

Handlers are infrastructure placeholders; business logic (order sync, refunds,
etc.) will be implemented in follow-up issues. Duplicate deliveries should be
deduplicated downstream (ETL ``event_id``); add an idempotency key check here
when webhook event ids are confirmed in official docs.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from backend.api.services.tiktok.schemas import TikTokWebhookPayload

logger = logging.getLogger(__name__)

EventHandler = Callable[[TikTokWebhookPayload], Awaitable[None]]


def _resolve_handler_name(event_type: str) -> str:
    """Map TikTok event type strings to internal handler names."""
    upper = event_type.upper()
    if "ORDER_CREATED" in upper or upper in {"ORDER_CREATE", "ORDER_CREATION"}:
        return "order_created"
    if "ORDER_PAID" in upper or ("PAID" in upper and "ORDER" in upper):
        return "order_paid"
    if "ORDER_CANCEL" in upper or ("CANCEL" in upper and "ORDER" in upper):
        return "order_cancelled"
    if "REFUND" in upper:
        return "refund_created"
    return "unknown_event"


async def _handle_order_created(event: TikTokWebhookPayload) -> None:
    # TODO: implement order_created business logic
    logger.info(
        "tiktok_webhook_order_created",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


async def _handle_order_paid(event: TikTokWebhookPayload) -> None:
    # TODO: implement order_paid business logic
    logger.info(
        "tiktok_webhook_order_paid",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


async def _handle_order_cancelled(event: TikTokWebhookPayload) -> None:
    # TODO: implement order_cancelled business logic
    logger.info(
        "tiktok_webhook_order_cancelled",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


async def _handle_refund_created(event: TikTokWebhookPayload) -> None:
    # TODO: implement refund_created business logic
    logger.info(
        "tiktok_webhook_refund_created",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


async def _handle_unknown_event(event: TikTokWebhookPayload) -> None:
    logger.info(
        "tiktok_webhook_unknown_event",
        extra={"shop_id": event.shop_id, "event_type": event.type},
    )


_HANDLERS: dict[str, EventHandler] = {
    "order_created": _handle_order_created,
    "order_paid": _handle_order_paid,
    "order_cancelled": _handle_order_cancelled,
    "refund_created": _handle_refund_created,
    "unknown_event": _handle_unknown_event,
}


class TikTokWebhookDispatcher:
    """Dispatch parsed webhook events to typed stub handlers."""

    async def dispatch(self, event: TikTokWebhookPayload) -> str:
        """Route *event* to a handler and return the handler name."""
        handler_name = _resolve_handler_name(event.type)
        handler = _HANDLERS[handler_name]
        await handler(event)
        return handler_name

    def register_handler(self, name: str, handler: EventHandler) -> None:
        """Register or override a handler (extension point for new event types)."""
        _HANDLERS[name] = handler
