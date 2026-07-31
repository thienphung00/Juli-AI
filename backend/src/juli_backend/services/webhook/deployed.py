"""Production HTTP wiring for TikTok webhook ingress on the main API."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.tiktok.webhook import WebhookProcessResult
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from juli_backend.services.tiktok.webhook_raw_log import DatabaseRawWebhookEventRecorder
from juli_backend.services.webhook.app import build_webhook_service
from juli_backend.services.webhook.material_handoff import make_material_etl_handoff

logger = logging.getLogger(__name__)


async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
    logger.error(
        "webhook_etl_dlq",
        extra={"channel": channel, "shop_key": shop_key, "payload_bytes": len(payload)},
    )


async def handle_tiktok_webhook_delivery(
    *,
    session: AsyncSession,
    app_key: str,
    app_secret: str,
    body: bytes,
    signature: str | None,
    headers: Mapping[str, str],
) -> WebhookProcessResult:
    """Verify, dispatch, and hand off a TikTok webhook using the request-scoped session."""
    consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
    service = build_webhook_service(
        app_key=app_key,
        app_secret=app_secret,
        handoff_fn=make_material_etl_handoff(consumer),
        side_effects=DatabaseWebhookSideEffects(session),
        raw_event_recorder=DatabaseRawWebhookEventRecorder(session),
    )
    result = await service.handle(
        body=body,
        signature=signature,
        headers=headers,
    )
    await session.commit()
    return result
