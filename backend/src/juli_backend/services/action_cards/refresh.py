"""Manual refresh pipeline: optional poll → scoring → persist — ADR-021."""

from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop

logger = logging.getLogger(__name__)


async def maybe_poll_tiktok_data(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Run Fujiwa poll when app credentials are configured; otherwise skip."""
    app_key = os.getenv("TIKTOK_APP_KEY")
    app_secret = os.getenv("TIKTOK_APP_SECRET")
    if not app_key or not app_secret:
        logger.info(
            "action_card_refresh_poll_skipped",
            extra={"shop_id": str(shop_id), "reason": "missing_tiktok_app_credentials"},
        )
        return

    from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
    from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
    from juli_backend.services.etl.consumer import EtlConsumer
    from juli_backend.services.ingestion import make_etl_handoff
    from juli_backend.workers.services.polling import FujiwaPollConfig, run_fujiwa_poll_cycle

    async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
        logger.error(
            "action_card_refresh_etl_dlq",
            extra={
                "shop_id": str(shop_id),
                "channel": channel,
                "shop_key": shop_key,
                "payload_bytes": len(payload),
            },
        )

    consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
    handoff = make_etl_handoff(consumer)

    await run_fujiwa_poll_cycle(
        session=session,
        config=FujiwaPollConfig(app_key=app_key, app_secret=app_secret),
        oauth_service=TikTokOAuthService(session),
        rate_limiter=RateLimiter(max_requests=10, window_seconds=1),
        handoff_fn=handoff,
    )


async def run_action_card_refresh(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    poll: bool = True,
) -> list[ActionCard]:
    """Execute one manual refresh cycle for a shop."""
    if poll:
        await maybe_poll_tiktok_data(session, shop_id)

    result = await run_daily_scoring_for_shop(session, shop_id)
    return await persist_scoring_result(session, shop_id, result)
