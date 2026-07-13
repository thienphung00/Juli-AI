"""Manual refresh pipeline: optional poll → scoring → persist — ADR-021."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop

logger = logging.getLogger(__name__)


def _poll_env_ready() -> dict[str, str] | None:
    """Return poll env vars when Fujiwa poll prerequisites are configured."""
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


async def maybe_poll_tiktok_data(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Run Fujiwa poll when TikTok + Redis credentials are configured; otherwise skip."""
    env = _poll_env_ready()
    if env is None:
        logger.info(
            "action_card_refresh_poll_skipped",
            extra={
                "shop_id": str(shop_id),
                "reason": "missing_tiktok_or_redis_env",
            },
        )
        return

    import redis

    from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
    from juli_backend.integrations.tiktok.auth import TikTokAuth
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
    tiktok_auth = TikTokAuth(
        app_key=env["app_key"],
        app_secret=env["app_secret"],
        base_url=os.getenv(
            "TIKTOK_API_BASE_URL",
            "https://open-api.tiktokglobalshop.com",
        ),
    )
    oauth_service = TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=env["redirect_uri"],
        app_secret=env["app_secret"],
    )
    rate_limiter = RateLimiter(redis.from_url(env["redis_url"]))

    await run_fujiwa_poll_cycle(
        session=session,
        config=FujiwaPollConfig(app_key=env["app_key"], app_secret=env["app_secret"]),
        oauth_service=oauth_service,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
    )


async def run_action_card_refresh(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    poll: bool = True,
    poll_hook: Any | None = None,
) -> list[ActionCard]:
    """Execute one manual refresh cycle for a shop."""
    if poll:
        runner = poll_hook or maybe_poll_tiktok_data
        await runner(session, shop_id)

    result = await run_daily_scoring_for_shop(session, shop_id)
    return await persist_scoring_result(session, shop_id, result)
