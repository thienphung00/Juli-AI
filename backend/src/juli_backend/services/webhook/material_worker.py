"""Material webhook worker: fetch poll resources then Analytics KPI precompute."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ShopsRepo
from juli_backend.services.analytics_kpi_cache import create_redis_client
from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis
from juli_backend.services.webhook.material_gate import MaterialEnqueueGate

logger = logging.getLogger(__name__)


def _poll_env_ready() -> dict[str, str] | None:
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


async def maybe_fetch_material_resources(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> None:
    """Run Fujiwa poll-step fetches + incremental analytics when env is configured."""
    env = _poll_env_ready()
    if env is None:
        logger.info(
            "material_analytics_fetch_skipped",
            extra={"shop_id": str(shop_id), "reason": "missing_tiktok_or_redis_env"},
        )
        return

    import redis

    from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
    from juli_backend.integrations.tiktok.auth import TikTokAuth
    from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
    from juli_backend.services.etl.consumer import EtlConsumer
    from juli_backend.services.ingestion import make_etl_handoff
    from juli_backend.workers.services.polling import (
        FujiwaPollConfig,
        run_fujiwa_material_resource_fetch,
    )

    async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
        logger.error(
            "material_analytics_etl_dlq",
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

    await run_fujiwa_material_resource_fetch(
        session=session,
        config=FujiwaPollConfig(app_key=env["app_key"], app_secret=env["app_secret"]),
        oauth_service=oauth_service,
        rate_limiter=rate_limiter,
        handoff_fn=handoff,
    )


async def run_material_analytics_compute(
    session: AsyncSession,
    *,
    shop_key: str,
    gate: MaterialEnqueueGate | None = None,
    fetch_hook: Any | None = None,
    redis_client: Any | None = None,
) -> None:
    """Fetch (when configured) then precompute Analytics KPIs for a TikTok shop key."""
    shop = await ShopsRepo(session).get_by_tiktok_id(shop_key)
    if shop is None:
        logger.warning(
            "material_analytics_unknown_shop",
            extra={"shop_key": shop_key},
        )
        return

    try:
        runner = fetch_hook or maybe_fetch_material_resources
        await runner(session, shop.id)

        client = redis_client if redis_client is not None else create_redis_client()
        await precompute_shop_analytics_kpis(session, shop.id, redis_client=client)
        await session.commit()
    finally:
        if gate is not None:
            gate.release(shop_key)
