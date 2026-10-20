"""Execute TargetedFetchPlan via bounded cdp_speed sync → bronze handoff (#627)."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import NoReadCredentialForShop, resolve_read_credential_for_shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    SANDBOX_AUTH_ID,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    RateLimiter,
    is_read_capability,
)
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories.repos import TikTokSyncStateRepo
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.quota_guard import is_quota_guarded, quota_guard_reason
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import FetchResource, TargetedFetchPlan
from juli_backend.services.cdp_speed.targeted_fetch_sync import (
    sync_ctor_performance,
    sync_live_hours,
    sync_orders,
    sync_returns,
)
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)

# Medallion bronze foundation (#627, extended #880 for A-34 ctor / A-28
# live_hours) — other plan resources are fetch-deferred.
BRONZE_SUPPORTED_RESOURCE_ATTRS = frozenset({"orders", "returns", "ctor", "live_hours"})

SyncResourceFn = Callable[..., Awaitable[None]]


class TargetedFetchExecutor(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        shop_id: uuid.UUID,
        shop_key: str,
        fetch_plan: TargetedFetchPlan,
        idempotency_key: str,
    ) -> BronzeAppendTracker: ...


_SYNC_BY_RESOURCE_ATTR: dict[str, SyncResourceFn] = {
    "orders": sync_orders,
    "returns": sync_returns,
    "ctor": sync_ctor_performance,
    "live_hours": sync_live_hours,
}

# ctor/live_hours both read the shared ``ProductionReadResources.analytics``
# client (there is no per-domain analytics attribute) — this maps their
# resource_attr to the actual dataclass field name. Resource attrs absent
# here (orders/returns) resolve to themselves, unchanged from #627.
_RESOURCE_ATTR_ACCESSOR: dict[str, str] = {
    "ctor": "analytics",
    "live_hours": "analytics",
}


def _resources_field_name(resource_attr: str) -> str:
    return _RESOURCE_ATTR_ACCESSOR.get(resource_attr, resource_attr)


ResolveJobCredentialFn = Callable[[AsyncSession, uuid.UUID], Awaitable[TikTokCredential | None]]


@dataclass(frozen=True)
class PartnerFetchEnv:
    app_key: str
    app_secret: str
    redirect_uri: str
    redis_url: str


def partner_fetch_env_ready() -> PartnerFetchEnv | None:
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
        "redis_url": os.getenv("REDIS_URL", "").strip(),
    }
    if not all(values.values()):
        return None
    return PartnerFetchEnv(**values)


def credential_belongs_to_job(credential: TikTokCredential, shop_id: uuid.UUID) -> bool:
    """True when ``credential`` may serve this job's read: the job's own shop's (fast track P61-D).

    Was "the configured production merchant's credential" -- so the targeted fetch
    served one shop and skipped every other shop's job. Now any read-capable
    credential (``PRODUCTION_READ`` or a seller's ``SELLER_CONNECT``) OWNED BY THE
    JOB'S SHOP, carrying its own merchant id, and never the sandbox write merchant
    (refused again by ``ProductionReadClientFactory``).
    """
    capability = credential.capability
    merchant = credential.merchant_authorization_id
    return (
        credential.shop_id == shop_id
        and capability is not None
        and is_read_capability(capability)
        and bool(merchant)
        and bool(SANDBOX_AUTH_ID)
        and merchant != SANDBOX_AUTH_ID
    )


async def resolve_job_read_credential(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> TikTokCredential | None:
    """The job shop's own read credential (lazily refreshed), or ``None``.

    ``resolve_read_credential_for_shop`` considers only rows that shop owns and has
    no fallback to a configured merchant; its lazy refresh layer (ADR-081 d.1 row 2)
    hands back a warm token. Resolved under the job shop's scope (RLS).
    """
    try:
        async with with_shop_scope(session, shop_id):
            credential = await resolve_read_credential_for_shop(session, shop_id)
    except NoReadCredentialForShop:
        return None
    if not credential_belongs_to_job(credential, shop_id):
        return None
    return credential


async def _run_plan_resource(
    resource: FetchResource,
    *,
    resources: ProductionReadResources,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_key: str,
    sync_state: dict[str, Any],
    correlation_id: str,
) -> None:
    # Quota guard: skip resources that are guarded (A-38/A-39 bestselling, A-31/A-33 detail fanout)
    if is_quota_guarded(resource.name):
        logger.info(
            "targeted_fetch_skipped",
            extra={
                "resource": resource.name,
                "correlation_id": correlation_id,
                "reason": quota_guard_reason(resource.name),
            },
        )
        return

    if resource.resource_attr not in BRONZE_SUPPORTED_RESOURCE_ATTRS:
        logger.info(
            "targeted_fetch_bronze_deferred",
            extra={
                "resource": resource.name,
                "resource_attr": resource.resource_attr,
                "correlation_id": correlation_id,
                "reason": "bronze_table_not_available",
            },
        )
        return

    sync_fn = _SYNC_BY_RESOURCE_ATTR.get(resource.resource_attr)
    if sync_fn is None:
        logger.warning(
            "targeted_fetch_unknown_resource",
            extra={
                "resource": resource.name,
                "attr": resource.resource_attr,
                "correlation_id": correlation_id,
            },
        )
        return

    await sync_fn(
        resource=getattr(resources, _resources_field_name(resource.resource_attr)),
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        app_id=app_id,
        shop_key=shop_key,
        sync_state=sync_state,
        correlation_id=correlation_id,
    )


async def execute_targeted_fetch_to_bronze(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    shop_key: str,
    fetch_plan: TargetedFetchPlan,
    idempotency_key: str,
    env: PartnerFetchEnv | None = None,
    resolve_credential: ResolveJobCredentialFn | None = None,
) -> BronzeAppendTracker:
    """Production targeted fetch: bounded Partner sync → bronze append handoff."""
    tracker = BronzeAppendTracker()
    correlation_id = job_correlation_token(shop_id, idempotency_key)

    if fetch_plan.is_empty:
        return tracker

    resolved_env = env if env is not None else partner_fetch_env_ready()
    if resolved_env is None:
        logger.info(
            "targeted_fetch_skipped",
            extra={
                "correlation_id": correlation_id,
                "fetch_plan_size": len(fetch_plan.resources),
                "reason": "missing_tiktok_or_redis_env",
            },
        )
        return tracker

    # `shops` is readable under a shop scope only for the caller's own row
    # (migration 053). Unscoped this returns None as `juli_app`, and the
    # executor would log "skipped" and do nothing — the silent no-op #1518 found.
    async with with_shop_scope(session, shop_id):
        shop = await session.get(Shop, shop_id)
    if shop is None or shop.tiktok_shop_id != shop_key:
        logger.warning(
            "targeted_fetch_skipped",
            extra={"correlation_id": correlation_id, "reason": "shop_key_mismatch"},
        )
        return tracker

    resolve = resolve_credential or resolve_job_read_credential
    credential = await resolve(session, shop_id)
    if credential is None or not credential_belongs_to_job(credential, shop_id):
        logger.warning(
            "targeted_fetch_skipped",
            extra={"correlation_id": correlation_id, "reason": "credential_shop_mismatch"},
        )
        return tracker

    merchant = credential.merchant_authorization_id
    if not merchant:  # unreachable past credential_belongs_to_job; keeps the type honest
        return tracker

    import redis

    # Fast track P61-D (D71.4): sign with the job shop's OWN credential and merchant
    # id. This used to re-resolve the configured production merchant
    # (`resolve_production_read_credential` + `PRODUCTION_AUTH_ID`), so only that
    # one shop was ever fetched; `resolve_read_credential_for_shop` already runs
    # the lazy refresh, so the credential above is warm.
    client_factory = ProductionReadClientFactory()
    resources = client_factory.create_resources(
        ClientFactoryConfig(
            app_key=resolved_env.app_key,
            app_secret=resolved_env.app_secret,
            access_token=credential.access_token,
            merchant_auth_id=merchant,
            shop_cipher=credential.shop_cipher,
        )
    )

    sync_state_repo = TikTokSyncStateRepo(session)
    # Scoped for the same reason, with a different failure mode: a SELECT under
    # RLS with no scope returns ZERO ROWS rather than raising, so an unscoped
    # load would silently restart the sync from nothing instead of erroring.
    async with with_shop_scope(session, shop_id):
        sync_state = await sync_state_repo.load(shop_id)

    handoff_fn = make_targeted_fetch_bronze_handoff(
        session,
        shop_id=shop_id,
        job_token=correlation_id,
        tracker=tracker,
    )
    rate_limiter = RateLimiter(redis.from_url(resolved_env.redis_url))

    for plan_resource in fetch_plan.resources:
        await _run_plan_resource(
            plan_resource,
            resources=resources,
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            app_id=resolved_env.app_key,
            shop_key=shop_key,
            sync_state=sync_state,
            correlation_id=correlation_id,
        )

    # SCOPE ADJACENT TO THE WRITE, NOT AROUND THE FETCH.
    #
    # `tiktok_sync_state` is RLS'd with WITH CHECK (shop_id = app_current_shop_id()),
    # so this save is REFUSED — not filtered — when the connection carries no
    # `app.current_shop_id`. That is what mock_analytics_hourly_reconcile hit
    # after #1627 fixed the bronze append: the run got 23 minutes further and
    # then died here instead (#1631).
    #
    # The scope goes HERE rather than around the loop above on purpose. The
    # orchestrator already wraps the whole bronze stage, and that scope does not
    # survive the multi-minute vendor fetch — a scope set before the fetch is
    # precisely the thing that fails (#1630). Adjacency is the property that
    # works, so it is the property this relies on.
    async with with_shop_scope(session, shop_id):
        await sync_state_repo.save(shop_id, sync_state)
    return tracker
