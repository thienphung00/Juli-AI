"""Scheduled and manual polling orchestration (#298).

Wires read-capable credentials, token refresh, per-endpoint sync state,
and rate-limit backoff into the existing sync workers.

#1995: no longer Fujiwa-only. Both entrypoints take an optional `shop_id`; when
given, the credential is resolved by `resolve_read_credential_for_shop` (#1365)
and must be a read capability owned by that shop. `_assert_pollable_read_credential`
replaced `_assert_fujiwa_credential`, and `_factory_config` signs with the
credential's own `merchant_authorization_id` rather than the configured
`PRODUCTION_AUTH_ID` constant -- the two guards that, between them, meant a
connecting seller's correctly-resolved credential was refused one layer down and
only Juli's configured merchant could be polled at all. `shop_id=None` keeps the
fleet-wide beat behaviour unchanged.

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

#1967: the cycle holds a STICKY shop scope, not a single `reapply_shop_scope`.

`reapply_shop_scope` was right for the one commit this module could see -- the
resolver's (#1880) -- and wrong for the ones it cannot. `handoff_fn` is
`make_etl_handoff(consumer)`, and `EtlConsumer.ingest` commits per record so
partial ingestion is durable; each of those commits discards `SET LOCAL
app.current_shop_id`. The cycle's final write, `TikTokSyncStateRepo.save`, then
met `app_current_shop_id() IS NULL` and Postgres refused it:

    asyncpg.exceptions.InsufficientPrivilegeError:
      new row violates row-level security policy for table "tiktok_sync_state"

Observed against Fujiwa: `order_items` at 250 rows, `orders` at 0, and the
watermark untouched -- rows landed while the bookkeeping that records them did
not, so the next cycle would refetch from the same place forever. The poll had
never completed a cycle.

`with_sticky_shop_scope` (#1883) is the answer rather than more reapplies: the
commits happen in a loop that lives in another module, so "immediately after
the callee returns" is not a place this file can name. Authority is unchanged
(ADR-089) -- one shop id, the same policies, the user GUC withheld, and still
`SET LOCAL`, so a pooled connection cannot carry a shop id into its next
checkout.

The scope opens AFTER `resolve()`, because the shop id it requires is only
knowable from the credential resolve returns. The resolver's own commit is
therefore still outside it, and harmless: the scope is established after it,
not discarded by it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
    resolve_read_credential_for_shop,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.tenant_context import with_sticky_shop_scope
from juli_backend.integrations.tiktok import (
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    SANDBOX_AUTH_ID,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    RateLimiter,
    is_read_capability,
    pagination_scope,
)
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories.repos import ProductsRepo, TikTokSyncStateRepo
from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.workers.services.polling.sync import (
    PollStepDroppedRowsError,
    ProductIdsFn,
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
    # The cycle budget and the per-fetch pagination budget used to compose by
    # ADDITION: a 1800s cycle could still start a 600s fetch at 1799s, for a
    # ~40-minute worst case -- the duration this issue was filed for. Publishing
    # the remaining cycle budget as the enclosing pagination scope caps every
    # fetch inside this stage at what is left, so the two compose by `min`.
    with pagination_scope(budget_seconds=remaining):
        return await _await_stage(start(), deadline=deadline, stage=stage)


async def _await_stage(
    awaitable: Awaitable[Any],
    *,
    deadline: _CycleDeadline,
    stage: str,
) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=deadline.remaining())
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


# WIDENED by #1995 to carry the shop, rather than binding it in a closure at
# each call site. The poll IS per-shop: every other parameter of a cycle
# (`sync_state`, the sticky scope, the `Shop` row read for `tiktok_shop_id`) is
# already keyed on one shop, and the credential resolve was the last step that
# pretended otherwise. A closure would have worked and would have left the
# alias claiming the resolve needs nothing but a session -- which is exactly
# the claim `resolve_read_credential_for_shop` disproves.
#
# `None` means "the fleet-wide entry named no shop": `workers/tasks/
# fujiwa_poll_beat.py` polls whichever shop owns the configured merchant's
# credential and cannot name it before resolving it.
ResolveCredentialFn = Callable[[AsyncSession, uuid.UUID | None], Awaitable[TikTokCredential]]
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
    wants_product_ids: bool = False


_FUJIWA_POLL_STEPS: tuple[_PollStep, ...] = (
    _PollStep(ORDER_SEARCH_PATH, "orders", sync_orders),
    _PollStep(PRODUCT_SEARCH_PATH, "products", sync_products),
    _PollStep(RETURN_SEARCH_PATH, "returns", sync_returns),
    _PollStep(INVENTORY_SEARCH_PATH, "inventory", sync_inventory, wants_product_ids=True),
)


def _assert_pollable_read_credential(
    credential: TikTokCredential,
    *,
    shop_id: uuid.UUID | None,
) -> None:
    """Refuse any credential that may not serve this poll (#1995).

    This used to be `_assert_fujiwa_credential`, and it asked one question:
    "is this the single configured production merchant?" That made the whole
    poll path structurally single-tenant -- #1365's resolver would hand back a
    connecting seller's own `SELLER_CONNECT` credential and this guard threw it
    away, so only Juli's own merchant could ever be polled.

    The question it asks now is the one that actually decides access, and it is
    two questions, not one:

    1. **Is the capability read-capable?** `is_read_capability` is the single
       place that answers this (`integrations/tiktok/merchant.py`), so
       `SANDBOX_WRITE` -- and a row carrying no capability at all -- is refused
       here for the same reason it is refused in the resolver. Capability is the
       authority; a missing capability is not permission.
    2. **Does the shop being polled own it?** When the caller named a shop, the
       credential's `shop_id` must BE that shop. This is the check that makes
       one shop polling under another shop's token impossible, and it is why
       the caller's `shop_id` is threaded down here rather than inferred from
       `credential.shop_id` (inferring it would make the guard tautological).

    `shop_id=None` is the fleet-wide entry (`workers/tasks/fujiwa_poll_beat.py`),
    which names no shop and polls whichever shop owns the configured merchant's
    credential. There the ownership question has no second party to compare
    against, so only the capability half applies -- stated plainly rather than
    dressed up as a check.

    The sandbox merchant id is refused by *identity* as well as by capability.
    Belt and braces on purpose: capability is a stored column, and a mislabelled
    row must not be able to reach the sandbox write merchant through a read.
    """
    capability = credential.capability
    if capability is None or not is_read_capability(capability):
        raise ValueError(
            f"polling requires a read-capable credential; got capability {capability!r}"
        )
    merchant = credential.merchant_authorization_id
    if not merchant:
        raise ValueError("polling requires a credential carrying a merchant authorization id")
    # FAIL CLOSED -- see the identical note in
    # `integrations/tiktok/factories.py`. `if SANDBOX_AUTH_ID and ...` would
    # turn an empty `TIKTOK_SANDBOX_MERCHANT_ID` into permission to skip the
    # exclusion, which is the inverse of what a guard is for. A constant this
    # check cannot read is a deployment fault, and the poll refuses.
    if not SANDBOX_AUTH_ID:
        raise ValueError(
            "polling cannot enforce the SANDBOX_VN exclusion: SANDBOX_AUTH_ID is empty "
            "(TIKTOK_SANDBOX_MERCHANT_ID is set to an empty value). Refusing to poll "
            "rather than admitting a merchant this guard can no longer exclude."
        )
    if merchant == SANDBOX_AUTH_ID:
        raise ValueError(
            "polling refuses the SANDBOX_VN write-validation merchant "
            f"({SANDBOX_AUTH_ID}); it is not read-capable"
        )
    if shop_id is not None and credential.shop_id != shop_id:
        raise ValueError(
            "polling requires a credential owned by the shop being polled; "
            f"shop {shop_id} resolved a credential owned by {credential.shop_id}"
        )


def _factory_config(
    config: FujiwaPollConfig,
    credential: TikTokCredential,
) -> ClientFactoryConfig:
    """Build the vendor client config from the credential's OWN merchant.

    Was `merchant_auth_id=PRODUCTION_AUTH_ID` -- a constant, so every poll
    signed as the configured merchant no matter whose credential it held. The
    merchant id travels with the token now, which is the only way two shops can
    each call the vendor under their own authorization.
    """
    merchant_auth_id = credential.merchant_authorization_id
    if not merchant_auth_id:
        # Unreachable through either entrypoint: `_assert_pollable_read_credential`
        # refuses a credential with no merchant id before the tenant scope is
        # entered. Restated here rather than silenced with a `cast` so the type
        # is narrowed by a real check, and so a future caller that reaches this
        # helper without the guard fails loudly instead of signing as "None".
        raise ValueError("polling requires a credential carrying a merchant authorization id")
    return ClientFactoryConfig(
        app_key=config.app_key,
        app_secret=config.app_secret,
        access_token=credential.access_token,
        merchant_auth_id=merchant_auth_id,
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


def _synced_product_ids_fn(session: AsyncSession, shop_id: uuid.UUID) -> ProductIdsFn:
    """Build the product-id source `sync_inventory` needs (#1948).

    Search Inventory has no unscoped listing and hard-requires `product_ids`
    in the request body -- `sync_inventory` cannot discover them on its own.
    This cycle already holds a session scoped to `shop_id` (`with_sticky_shop_scope`
    wraps the whole cycle -- #1967), so the source reads through it
    directly rather than opening a second, unscoped one: a fresh session here
    could not see this transaction's own writes, could not be exercised by
    the orchestration test fixtures, and a construction failure would have to
    swallow to `[]` to stay non-fatal -- the exact shape of silent failure
    this issue exists to remove, just moved one layer down.
    """

    async def list_product_ids() -> list[str]:
        repo = ProductsRepo(session)
        product_ids: list[str] = []
        cursor: uuid.UUID | None = None
        page_limit = 200
        while True:
            page = await repo.list(shop_id, limit=page_limit, after=cursor)
            if not page:
                break
            product_ids.extend(
                product.tiktok_product_id for product in page if product.tiktok_product_id
            )
            if len(page) < page_limit:
                break
            cursor = page[-1].id
        return product_ids

    return list_product_ids


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
    list_product_ids: ProductIdsFn | None = None,
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
    # #1948: Search Inventory hard-requires `product_ids`, and only the caller
    # holding a shop-scoped session can source them. Raising on a missing
    # source rather than defaulting to "no ids" is deliberate -- a default
    # would reintroduce exactly the silent empty fetch #1948 removed.
    extra_kwargs: dict[str, Any] = {}
    if step.wants_product_ids:
        if list_product_ids is None:
            raise ValueError(f"{step.endpoint_path} step requires list_product_ids")
        extra_kwargs["list_product_ids"] = list_product_ids
    return await _within_cycle_budget(
        lambda: step.sync_fn(
            resource=getattr(resources, step.resource_attr),
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            app_id=app_id,
            shop_id=shop_key,
            sync_state=sync_state,
            **extra_kwargs,
        ),
        deadline=deadline,
        stage=step.resource_attr,
    )


class PollCycleFailedError(RuntimeError):
    """A poll cycle ran to the end and at least one of its steps did not succeed.

    The missing half of #1950's second criterion. `PollStepDroppedRowsError`
    already fails a step that fetched rows and landed none -- but three of the
    five steps still catch `TikTokAPIError` on the FETCH and return an
    `ok=False` outcome instead of raising (`polling/sync.py`, the
    `except TikTokAPIError as exc: return step.report(error=exc)` arms), which
    #2009 recorded as a residual gap belonging to this issue. Under that shape
    a cycle in which every endpoint's vendor call failed completed normally: the
    Celery task exited zero, nothing retried, and the only trace was a log line
    whose numbers the worker's formatter drops (#1978).

    Raised AFTER the sync state and the outcome records are written, so the
    evidence of what failed survives the failure -- the same order `_poll`'s
    partial-save arm uses and for the same reason.
    """

    def __init__(self, failures: list[SyncOutcome], *, shop_id: uuid.UUID) -> None:
        self.failures = failures
        self.shop_id = shop_id
        detail = ", ".join(
            f"{outcome.resource}(fetched={outcome.fetched}, persisted={outcome.persisted}, "
            f"failed={outcome.failed}, error={outcome.error})"
            for outcome in failures
        )
        super().__init__(f"poll cycle for shop {shop_id} had failing steps: {detail}")


async def _record_cycle(
    repo: TikTokSyncStateRepo,
    shop_id: uuid.UUID,
    *,
    sync_state: dict[str, Any],
    outcomes: list[SyncOutcome],
) -> None:
    """Persist the cycle's watermarks and its per-endpoint verdicts.

    Guarded, and never raises. It is called on the failing path too, where an
    exception escaping from here would replace a diagnosable failure with an
    undiagnosable one -- the reason the pre-existing partial-state save was
    already written this way.

    The outcome write is what makes #1950's fourth criterion answerable in SQL
    rather than inferred from a missing row, and it is the only half of this
    issue's observability that survives the Celery worker: every field
    `poll_step_outcome` carries travels in `logger.extra`, and
    `workers/celery_app.py` never calls `configure_logging`, so the worker
    renders the event name and drops the numbers (#1978). A column does not go
    through a formatter.
    """
    try:
        await repo.save(shop_id, sync_state)
    except Exception:
        logger.error(
            "poll_cycle_partial_state_save_failed",
            extra={"shop_id": str(shop_id)},
            exc_info=True,
        )
    try:
        await repo.record_outcomes(shop_id, outcomes)
    except Exception:
        logger.error(
            "poll_cycle_outcome_record_failed",
            extra={"shop_id": str(shop_id)},
            exc_info=True,
        )


def _assert_cycle_succeeded(outcomes: list[SyncOutcome], *, shop_id: uuid.UUID) -> None:
    """Log the cycle's verdict, and refuse to call a cycle with a failed step a success."""
    failures = [outcome for outcome in outcomes if not outcome.ok]
    logger.info(
        "poll_cycle_outcome",
        extra={
            "shop_id": str(shop_id),
            "steps": len(outcomes),
            "failed_steps": len(failures),
            "fetched": sum(outcome.fetched for outcome in outcomes),
            "persisted": sum(outcome.persisted for outcome in outcomes),
            "ok": not failures,
        },
    )
    if failures:
        raise PollCycleFailedError(failures, shop_id=shop_id)


async def _poll(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    credential: TikTokCredential,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    factory: ProductionReadClientFactory | None,
    create_resources: CreateResourcesFn | None,
    sync_state_repo: TikTokSyncStateRepo | None,
    sleep: SleepFn,
    deadline: _CycleDeadline,
) -> None:
    """One poll cycle: the four search endpoints, then analytics, then the watermark.

    Runs entirely inside the caller's `with_sticky_shop_scope` and takes an
    already-resolved credential, because the shop id that scope needs is only
    knowable after the resolve. Both entrypoints share this body — the analytics
    wire set (#424: A-25 + A-31–A-39) is reached identically by scheduled
    polling and by manual refresh (ADR-021), which arrives here via
    `maybe_poll_tiktok_data` → `run_fujiwa_poll_cycle`.

    `deadline` is a PARAMETER, not built here (#1969 + #1967 merge). The clock
    has to start before `resolve`, which does DB work and may refresh a token
    over HTTP -- work the beat slot is holding and the budget must cover. This
    function is only reachable with the credential already resolved, so a
    deadline constructed here would silently exclude the resolve and the
    budget would measure something narrower than it claims.

    Takes no `shop_id`: `_assert_pollable_read_credential` runs in
    `_resolve_and_poll` BEFORE `with_sticky_shop_scope` is entered, because a
    scope built from an unverified credential would already have handed the
    cycle another shop's authority by the time this body could object. By here,
    `credential.shop_id` IS the shop being polled -- checked, not assumed.
    """
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
    list_product_ids = _synced_product_ids_fn(session, credential.shop_id)

    outcomes: list[SyncOutcome] = []
    try:
        for step in _FUJIWA_POLL_STEPS:
            outcomes.append(
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
                    list_product_ids=list_product_ids,
                )
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
        outcomes.append(
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
        )
    except PollStepDroppedRowsError as exc:
        # The step that raised never returned its outcome, so it is missing from
        # `outcomes` -- and it is the one the operator most needs recorded.
        outcomes.append(exc.outcome)
        await _record_cycle(
            repo,
            credential.shop_id,
            sync_state=sync_state,
            outcomes=outcomes,
        )
        raise
    except Exception:
        # Save what completed before re-raising. The steps that did finish
        # advanced their watermarks in `sync_state`, and throwing those away
        # would make the next cycle refetch rows that already landed -- under
        # the INCREMENTAL 20-page cap, where over-running truncates with only a
        # warning. A loud failure that silently enlarges the next read is a bad
        # trade.
        #
        # Widened from `PollCycleTimeoutError` (#1969 review): a timeout is not
        # the only way a cycle dies partway. A `PollStepDroppedRowsError` or a
        # truncated backfill from step 2 of 4 discards step 1's watermark just
        # as thoroughly.
        #
        # The save is guarded and the re-raise is bare, so a failing save can
        # never mask the failure that caused it -- losing the original exception
        # here would be trading a diagnosable failure for an undiagnosable one.
        await _record_cycle(
            repo,
            credential.shop_id,
            sync_state=sync_state,
            outcomes=outcomes,
        )
        raise

    await _record_cycle(
        repo,
        credential.shop_id,
        sync_state=sync_state,
        outcomes=outcomes,
    )
    _assert_cycle_succeeded(outcomes, shop_id=credential.shop_id)


async def _default_resolve_credential(
    session: AsyncSession,
    shop_id: uuid.UUID | None,
) -> TikTokCredential:
    """Which resolver a cycle uses when the caller injected none (#1995).

    Two resolvers, because there are genuinely two callers and they ask
    different questions:

    - a caller that NAMES a shop asks `resolve_read_credential_for_shop`,
      which considers only rows that shop owns and raises
      `NoReadCredentialForShop` when it owns nothing read-capable. There is no
      fallback to the configured merchant -- that fallback is the defect #1365
      exists to remove, and re-adding it here would restore it.
    - the fleet-wide beat names no shop and keeps
      `resolve_production_read_credential`, unchanged.
    """
    if shop_id is None:
        return await resolve_production_read_credential(session)
    return await resolve_read_credential_for_shop(session, shop_id)


async def _resolve_and_poll(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    shop_id: uuid.UUID | None,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    resolve_credential: ResolveCredentialFn | None,
    factory: ProductionReadClientFactory | None,
    create_resources: CreateResourcesFn | None,
    sync_state_repo: TikTokSyncStateRepo | None,
    sleep: SleepFn,
) -> None:
    """Resolve, verify, scope, poll -- the body both entrypoints share.

    One body rather than two identical ones (#1995) so the ownership guard
    cannot be added to one entrypoint and forgotten on the other. The order of
    the three lines below is the safety property:

        resolve -> ASSERT -> enter scope

    `with_sticky_shop_scope(credential.shop_id)` grants the cycle that shop's
    read/write authority for its whole duration. Asserting after entering it
    would mean the authority was already handed over before anything checked
    whose credential it came from.
    """
    # Before `resolve`, deliberately: the resolve does DB work and may refresh a
    # token over HTTP, and that time is part of the cycle this beat slot holds.
    # `_poll` takes the deadline rather than building one, because by the time
    # it runs the resolve has already happened (#1967 collapsed both entrypoints
    # into it) and a deadline built there would not cover it.
    deadline = _CycleDeadline()

    resolve = resolve_credential or _default_resolve_credential
    credential = await resolve(session, shop_id)
    _assert_pollable_read_credential(credential, shop_id=shop_id)
    async with with_sticky_shop_scope(session, credential.shop_id):
        await _poll(
            session=session,
            config=config,
            credential=credential,
            rate_limiter=rate_limiter,
            handoff_fn=handoff_fn,
            factory=factory,
            create_resources=create_resources,
            sync_state_repo=sync_state_repo,
            sleep=sleep,
            deadline=deadline,
        )


async def run_fujiwa_material_resource_fetch(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    oauth_service: TikTokOAuthService,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    shop_id: uuid.UUID | None = None,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """Fetch orders/products/returns/inventory + incremental analytics for material precompute.

    `shop_id` names the shop being fetched for (#1995). Omitting it keeps the
    pre-#1995 fleet-wide behaviour: resolve the configured production-read
    merchant and fetch for whichever shop owns it.
    """
    await _resolve_and_poll(
        session=session,
        config=config,
        shop_id=shop_id,
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        resolve_credential=resolve_credential,
        factory=factory,
        create_resources=create_resources,
        sync_state_repo=sync_state_repo,
        sleep=sleep,
    )


async def run_fujiwa_poll_cycle(
    *,
    session: AsyncSession,
    config: FujiwaPollConfig,
    oauth_service: TikTokOAuthService,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    shop_id: uuid.UUID | None = None,
    resolve_credential: ResolveCredentialFn | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
    sync_state_repo: TikTokSyncStateRepo | None = None,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """Run one poll cycle for orders, products, returns, and inventory.

    `shop_id` names the shop being polled (#1995). When given, the credential
    is resolved through `resolve_read_credential_for_shop` and must be owned by
    that shop -- which is what lets a connecting seller be polled under their
    own token instead of being refused for not being Juli's merchant. Omitting
    it keeps the fleet-wide behaviour the Celery beat relies on.
    """
    await _resolve_and_poll(
        session=session,
        config=config,
        shop_id=shop_id,
        rate_limiter=rate_limiter,
        handoff_fn=handoff_fn,
        resolve_credential=resolve_credential,
        factory=factory,
        create_resources=create_resources,
        sync_state_repo=sync_state_repo,
        sleep=sleep,
    )
