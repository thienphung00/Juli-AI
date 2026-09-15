"""Fujiwa-only scheduled polling orchestration (#298).

Wires production-read credentials, token refresh, per-endpoint sync state,
and rate-limit backoff into the existing sync workers.

ADR-081 decision 4 / #1232: the two `oauth_service.refresh_merchant_tokens`
calls this module used to make (one per entrypoint) are deleted. `resolve()`
already returns the credential from `resolve_production_read_credential`
(or a caller-supplied override), and that resolver now runs the lazy refresh
layer itself (`core/security/credential_resolver.py`) -- so the credential
`resolve()` hands back is already warm. `oauth_service: TikTokOAuthService`
stays a required parameter on both entrypoints purely so
`services/action_cards/refresh.py::maybe_poll_tiktok_data` (out of this
slice's write-path lock) keeps working unmodified; neither entrypoint's body
calls it anymore.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.tenant_context import reapply_shop_scope
from juli_backend.integrations.tiktok import (
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    PRODUCTION_AUTH_ID,
    RETURN_SEARCH_PATH,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    RateLimiter,
    TikTokCapability,
)
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories.repos import TikTokSyncStateRepo
from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.workers.services.polling.sync import (
    SyncOutcome,
    sync_analytics,
    sync_inventory,
    sync_orders,
    sync_products,
    sync_returns,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_MAX_REQUESTS = 10

# Wall-clock budget for one poll cycle (#1969). A real cycle was still alive at
# 47:43 with no log activity in the previous ten minutes and had to be killed;
# under Celery beat that wedges a worker slot indefinitely, and -- because the
# cycle emitted nothing -- silently.
_DEFAULT_CYCLE_BUDGET_SECONDS = 1800.0
CYCLE_BUDGET_SECONDS_ENV = "TIKTOK_POLL_CYCLE_BUDGET_SECONDS"

_monotonic = time.monotonic


def cycle_budget_seconds() -> float:
    """Wall-clock budget for one poll cycle."""
    return float(os.getenv(CYCLE_BUDGET_SECONDS_ENV, str(_DEFAULT_CYCLE_BUDGET_SECONDS)))


class PollCycleTimeoutError(RuntimeError):
    """A poll cycle outran its wall-clock budget and was stopped."""

    def __init__(self, *, stage: str, budget_seconds: float, elapsed_seconds: float) -> None:
        self.stage = stage
        self.budget_seconds = budget_seconds
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"poll cycle exceeded its {budget_seconds:.0f}s budget at stage "
            f"{stage!r} after {elapsed_seconds:.1f}s"
        )


@dataclass
class _CycleDeadline:
    """How much wall clock the cycle has left, and what that can actually stop.

    CAN stop:
      - a stage that has not begun -- `check()` refuses to start it
      - a stage parked on a real `await`: an `asyncio.sleep` in the rate-limit
        backoff, DB I/O inside the ETL handoff, anything that yields to the loop.
        `asyncio.wait_for` cancels those.

    CANNOT stop:
      - a stage blocked inside a synchronous call. The vendor clients use
        `requests` and redis-py; neither yields to the event loop, so while one
        is in flight `wait_for`'s timer cannot even fire. Cancellation lands at
        the next await point, not during the call. Three other beat tasks share
        this shape.

    So this is a bound on *scheduling*, not a hard kill. What bounds blocking
    vendor I/O sits a layer down, in `integrations/tiktok/client.py`: the
    per-request socket timeout (15s by default) and the between-pages wall-clock
    budget in `pagination_scope`. Worst case after the budget is spent is one
    in-flight request plus the current page's handoff loop -- not zero, and the
    honest number to quote.
    """

    budget_seconds: float = field(default_factory=cycle_budget_seconds)
    clock: Callable[[], float] = _monotonic
    started_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.budget_seconds - self.elapsed())

    def check(self, *, stage: str) -> float:
        """Return the seconds left, or raise if the budget is already spent."""
        elapsed = self.elapsed()
        remaining = max(0.0, self.budget_seconds - elapsed)
        if remaining <= 0.0:
            logger.error(
                "poll_cycle_budget_exceeded",
                extra={
                    "stage": stage,
                    "budget_seconds": self.budget_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            raise PollCycleTimeoutError(
                stage=stage,
                budget_seconds=self.budget_seconds,
                elapsed_seconds=elapsed,
            )
        return remaining


async def _within_cycle_budget(
    start: Callable[[], Awaitable[Any]],
    *,
    deadline: _CycleDeadline,
    stage: str,
) -> Any:
    """Run one stage under the cycle budget.

    The `wait_for` is a backstop for hangs at genuine await points, not a hard
    kill -- see `_CycleDeadline`. It is still worth having: the two hangs this
    path can suffer that ARE awaits are the rate-limit backoff sleeping on a
    Redis TTL and the ETL handoff waiting on Postgres.

    Takes a factory rather than a coroutine so that a stage refused by the
    budget is never constructed at all. Passing the coroutine in would leave an
    un-awaited coroutine behind on the raising path -- a `RuntimeWarning` and a
    real leak.
    """
    remaining = deadline.check(stage=stage)
    try:
        return await asyncio.wait_for(start(), timeout=remaining)
    except TimeoutError as exc:
        logger.error(
            "poll_cycle_stage_timed_out",
            extra={
                "stage": stage,
                "budget_seconds": deadline.budget_seconds,
                "elapsed_seconds": round(deadline.elapsed(), 3),
            },
        )
        raise PollCycleTimeoutError(
            stage=stage,
            budget_seconds=deadline.budget_seconds,
            elapsed_seconds=deadline.elapsed(),
        ) from exc


ResolveCredentialFn = Callable[[AsyncSession], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], ProductionReadResources]
SleepFn = Callable[[float], Awaitable[None]]
# Every poll step returns its outcome triple (#1969/#1950); a step that returns
# `None` is a step that cannot be asked whether it dropped anything. Typed
# concretely rather than left as `Awaitable[None]` so mypy is the thing that
# catches a step regressing to a silent return -- including on the #1948 rebase,
# where `sync_inventory` has an early `return` on an empty product-id list.
SyncWorkerFn = Callable[..., Awaitable[SyncOutcome]]


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
    _PollStep(INVENTORY_SEARCH_PATH, "inventory", sync_inventory),
)


def _assert_fujiwa_credential(credential: TikTokCredential) -> None:
    if credential.merchant_authorization_id != PRODUCTION_AUTH_ID:
        raise ValueError(
            "Fujiwa polling requires production-read credentials; "
            f"got merchant {credential.merchant_authorization_id}"
        )
    if credential.capability != TikTokCapability.PRODUCTION_READ.value:
        raise ValueError(
            f"Fujiwa polling requires production_read capability; got {credential.capability}"
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
    deadline: _CycleDeadline,
) -> SyncOutcome:
    await _within_cycle_budget(
        lambda: _backoff_if_rate_limited(
            rate_limiter,
            app_id=app_id,
            shop_id=shop_key,
            endpoint=step.endpoint_path,
            sleep=sleep,
        ),
        deadline=deadline,
        stage=step.resource_attr,
    )
    return await _within_cycle_budget(
        lambda: step.sync_fn(
            resource=getattr(resources, step.resource_attr),
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            app_id=app_id,
            shop_id=shop_key,
            sync_state=sync_state,
        ),
        deadline=deadline,
        stage=step.resource_attr,
    )


async def run_fujiwa_material_resource_fetch(
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
    """Fetch orders/products/returns/inventory + incremental analytics for material precompute."""
    # Clock starts before `resolve`, which does DB work and may refresh a token
    # over HTTP -- that is part of the cycle the beat slot is holding.
    deadline = _CycleDeadline()

    resolve = resolve_credential or resolve_production_read_credential
    credential = await resolve(session)
    # `resolve_production_read_credential` -> `_lazy_refresh` -> `refresh_credential`
    # commits inside the caller's `with_shop_scope` (SET LOCAL), discarding
    # `app.current_shop_id` (#1880). Reapplied immediately so the sync-state
    # load and shop read just below still run under scope instead of a
    # silent-empty-read / NotFound-shaped `shop is None`.
    await reapply_shop_scope(session, credential.shop_id)
    _assert_fujiwa_credential(credential)

    client_factory = factory or ProductionReadClientFactory()
    build_resources = create_resources or client_factory.create_resources
    resources = build_resources(_factory_config(config, credential))

    repo = sync_state_repo or TikTokSyncStateRepo(session)
    sync_state = await repo.load(credential.shop_id)

    app_id = config.app_key
    shop = await session.get(Shop, credential.shop_id)
    if shop is None or not shop.tiktok_shop_id:
        raise ValueError(
            f"Fujiwa polling requires a shop with tiktok_shop_id; shop_id={credential.shop_id}"
        )
    shop_key = shop.tiktok_shop_id

    try:
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
                deadline=deadline,
            )

        await _within_cycle_budget(
            lambda: _backoff_if_rate_limited(
                rate_limiter,
                app_id=app_id,
                shop_id=shop_key,
                endpoint=ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
                sleep=sleep,
            ),
            deadline=deadline,
            stage="analytics",
        )
        await _within_cycle_budget(
            lambda: sync_analytics(
                resource=resources.analytics,
                promotion_resource=resources.promotion,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                app_id=app_id,
                shop_id=shop_key,
                sync_state=sync_state,
            ),
            deadline=deadline,
            stage="analytics",
        )
    except PollCycleTimeoutError:
        # Save what completed before re-raising. The steps that did finish
        # advanced their watermarks in `sync_state`, and throwing those away
        # would make the next cycle refetch rows that already landed.
        await repo.save(credential.shop_id, sync_state)
        raise

    await repo.save(credential.shop_id, sync_state)


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
    """Run one Fujiwa poll cycle for orders, products, returns, and inventory."""
    # Clock starts before `resolve`, which does DB work and may refresh a token
    # over HTTP -- that is part of the cycle the beat slot is holding.
    deadline = _CycleDeadline()

    resolve = resolve_credential or resolve_production_read_credential
    credential = await resolve(session)
    # See the matching comment in `run_fujiwa_material_resource_fetch` (#1880):
    # the resolver's own `refresh_credential` commit discards the caller's
    # shop scope, so it must be reapplied before any further tenant read.
    await reapply_shop_scope(session, credential.shop_id)
    _assert_fujiwa_credential(credential)

    client_factory = factory or ProductionReadClientFactory()
    build_resources = create_resources or client_factory.create_resources
    resources = build_resources(_factory_config(config, credential))

    repo = sync_state_repo or TikTokSyncStateRepo(session)
    sync_state = await repo.load(credential.shop_id)

    app_id = config.app_key
    shop = await session.get(Shop, credential.shop_id)
    if shop is None or not shop.tiktok_shop_id:
        raise ValueError(
            f"Fujiwa polling requires a shop with tiktok_shop_id; shop_id={credential.shop_id}"
        )
    shop_key = shop.tiktok_shop_id

    try:
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
                deadline=deadline,
            )

        # Analytics wire set (#424): A-25 + A-31–A-39. Manual refresh (ADR-021) shares
        # this entrypoint via maybe_poll_tiktok_data → run_fujiwa_poll_cycle.
        await _within_cycle_budget(
            lambda: _backoff_if_rate_limited(
                rate_limiter,
                app_id=app_id,
                shop_id=shop_key,
                endpoint=ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
                sleep=sleep,
            ),
            deadline=deadline,
            stage="analytics",
        )
        await _within_cycle_budget(
            lambda: sync_analytics(
                resource=resources.analytics,
                promotion_resource=resources.promotion,
                rate_limiter=rate_limiter,
                handoff_fn=handoff_fn,
                app_id=app_id,
                shop_id=shop_key,
                sync_state=sync_state,
            ),
            deadline=deadline,
            stage="analytics",
        )
    except PollCycleTimeoutError:
        # Save what completed before re-raising. The steps that did finish
        # advanced their watermarks in `sync_state`, and throwing those away
        # would make the next cycle refetch rows that already landed.
        await repo.save(credential.shop_id, sync_state)
        raise

    await repo.save(credential.shop_id, sync_state)
