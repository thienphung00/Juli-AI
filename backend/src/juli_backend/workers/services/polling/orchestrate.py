"""Fujiwa-only scheduled polling orchestration (#298).

Wires production-read credentials, token refresh, per-endpoint sync state,
and rate-limit backoff into the existing sync workers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.constants import (
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
)
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    TikTokCapability,
)
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokSyncStateRepo
from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.workers.services.polling.sync import (
    sync_orders,
    sync_products,
    sync_returns,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_MAX_REQUESTS = 10

ResolveCredentialFn = Callable[[AsyncSession], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], ProductionReadResources]
SleepFn = Callable[[float], Awaitable[None]]
SyncWorkerFn = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class FujiwaPollConfig:
    """TikTok app credentials for Fujiwa production-read polling."""

    app_key: str
    app_secret: str


@dataclass(frozen=True)
class _PollStep:
    endpoint_path: str
    resource_attr: str
    sync_fn: SyncWorkerFn


_FUJIWA_POLL_STEPS: tuple[_PollStep, ...] = (
    _PollStep(ORDER_SEARCH_PATH, "orders", sync_orders),
    _PollStep(PRODUCT_SEARCH_PATH, "products", sync_products),
    _PollStep(RETURN_SEARCH_PATH, "returns", sync_returns),
)


def _assert_fujiwa_credential(credential: TikTokCredential) -> None:
    if credential.merchant_authorization_id != PRODUCTION_AUTH_ID:
        raise ValueError(
            "Fujiwa polling requires production-read credentials; "
            f"got merchant {credential.merchant_authorization_id}"
        )
    if credential.capability != TikTokCapability.PRODUCTION_READ.value:
        raise ValueError(
            "Fujiwa polling requires production_read capability; "
            f"got {credential.capability}"
        )


def _factory_config(
    config: FujiwaPollConfig,
    credential: TikTokCredential,
) -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key=config.app_key,
        app_secret=config.app_secret,
        access_token=credential.access_token,
        merchant_auth_id=PRODUCTION_AUTH_ID,
        shop_cipher=credential.shop_cipher,
    )


async def _backoff_if_rate_limited(
    rate_limiter: RateLimiter,
    *,
    app_id: str,
    shop_id: str,
    endpoint: str,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """Wait for the rate-limit window to reset before calling the API."""
    while rate_limiter.is_exhausted(
        app_id,
        shop_id,
        endpoint,
        max_requests=_RATE_LIMIT_MAX_REQUESTS,
    ):
        ttl = rate_limiter.time_until_reset(app_id, shop_id, endpoint)
        if ttl <= 0:
            break
        logger.info(
            "rate_limit_backoff",
            extra={"shop_id": shop_id, "endpoint": endpoint, "seconds": ttl},
        )
        await sleep(float(ttl))


async def _run_poll_step(
    step: _PollStep,
    *,
    resources: ProductionReadResources,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    sleep: SleepFn,
) -> None:
    await _backoff_if_rate_limited(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_key,
        endpoint=step.endpoint_path,
        sleep=sleep,
    )
    await step.sync_fn(
        resource=getattr(resources, step.resource_attr),
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        app_id=app_id,
        shop_id=shop_key,
        sync_state=sync_state,
    )


async def run_fujiwa_poll_cycle(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    oauth_service: TikTokOAuthService,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """Run one Fujiwa poll cycle for orders, products, and returns."""
    resolve = resolve_credential or resolve_production_read_credential
    credential = await resolve(session)
    _assert_fujiwa_credential(credential)

    credential = await oauth_service.refresh_merchant_tokens(
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )

    client_factory = factory or ProductionReadClientFactory()
    build_resources = create_resources or client_factory.create_resources
    resources = build_resources(_factory_config(config, credential))

    repo = sync_state_repo or TikTokSyncStateRepo(session)
    sync_state = await repo.load(credential.shop_id)

    app_id = config.app_key
    shop_key = str(credential.shop_id)

    for step in _FUJIWA_POLL_STEPS:
        await _run_poll_step(
            step,
            resources=resources,
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            app_id=app_id,
            shop_key=shop_key,
            sync_state=sync_state,
            sleep=sleep,
        )

    await repo.save(credential.shop_id, sync_state)
