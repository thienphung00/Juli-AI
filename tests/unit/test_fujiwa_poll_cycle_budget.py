"""A wall-clock budget on the poll cycle, and an honest account of its reach (#1969).

Defect 3: a cycle was still alive at 47:43 with no log activity in the previous
ten minutes and had to be killed. Under Celery beat that wedges a worker slot
indefinitely, and silently.

The tests below pin BOTH halves of the guarantee, because half of it is a
limitation and a limitation nobody wrote a test for is a limitation somebody
later claims they do not have:

- what the budget CAN stop: a step parked on an `await`, and any step that has
  not started yet
- what it CANNOT stop: a step blocked inside a synchronous `requests` or
  redis-py call, which never yields to the event loop, so `asyncio.wait_for`'s
  timer cannot even fire until the call returns

Doubles are bound to the real `SyncWorkerFn` keyword signature that
`_run_poll_step` calls, so a signature change breaks these instead of sliding
past a `**kwargs` stand-in.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import (
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RateLimiter,
    current_pagination_scope,
    pagination_scope,
)
from juli_backend.integrations.tiktok import client as client_module
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter as RealRateLimiter
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.workers.services.polling import orchestrate as orchestrate_module
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    PollCycleTimeoutError,
    _CycleDeadline,
    _PollStep,
    _run_poll_step,
    run_fujiwa_material_resource_fetch,
    run_fujiwa_poll_cycle,
)

SHOP_KEY = "7494001234567890123"


class _Resources:
    def __init__(self) -> None:
        self.orders = object()
        self.products = object()


class NeverExhaustedRateLimiter:
    """Stand-in bound to the real `RateLimiter` signatures.

    Keyword-only parameters here would have been a fake contract: the real
    methods take these positionally-or-by-keyword, so a caller switching to
    positional arguments would break production and not these tests.
    `test_rate_limiter_double_matches_the_real_signatures` pins that.
    """

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        return True

    def is_exhausted(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
    ) -> bool:
        return False

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


def test_rate_limiter_double_matches_the_real_signatures():
    """The double is only evidence if it cannot drift from what it stands in for."""
    for name in ("acquire", "is_exhausted", "time_until_reset"):
        real = inspect.signature(getattr(RealRateLimiter, name))
        double = inspect.signature(getattr(NeverExhaustedRateLimiter, name))
        assert list(real.parameters) == list(double.parameters), name
        assert [p.kind for p in real.parameters.values()] == [
            p.kind for p in double.parameters.values()
        ], name


async def _never_sleeps(seconds: float) -> None:
    raise AssertionError("the cycle should not have needed to back off")


async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
    return None


def _fixed_clock(ticks: list[float]):
    def clock() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    return clock


def _step(name: str, path: str, sync_fn) -> _PollStep:
    return _PollStep(path, name, sync_fn)


async def _run(step: _PollStep, deadline: _CycleDeadline) -> None:
    await _run_poll_step(
        step,
        resources=_Resources(),
        rate_limiter=NeverExhaustedRateLimiter(),
        handoff_fn=_handoff,
        app_id="app1",
        shop_key=SHOP_KEY,
        sync_state={},
        sleep=_never_sleeps,
        deadline=deadline,
    )


class TestDeadlineStopsWorkNotYetStarted:
    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("error::RuntimeWarning")
    async def test_a_spent_budget_refuses_the_next_step(self):
        ran: list[str] = []

        async def sync_products(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            ran.append("products")

        # started at 0, checked at 5000 -- well past a 1800s budget.
        deadline = _CycleDeadline(budget_seconds=1800.0, clock=_fixed_clock([0.0, 5000.0]))

        with pytest.raises(PollCycleTimeoutError) as excinfo:
            await _run(_step("products", PRODUCT_SEARCH_PATH, sync_products), deadline)

        assert ran == []
        assert excinfo.value.stage == "products"
        assert excinfo.value.budget_seconds == 1800.0
        # `filterwarnings` above turns an un-awaited coroutine into a failure:
        # a refused stage must never be constructed in the first place.

    @pytest.mark.asyncio
    async def test_a_budget_with_room_left_runs_the_step(self):
        ran: list[str] = []

        async def sync_orders(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            ran.append("orders")

        deadline = _CycleDeadline(budget_seconds=1800.0, clock=_fixed_clock([0.0, 10.0]))

        await _run(_step("orders", ORDER_SEARCH_PATH, sync_orders), deadline)

        assert ran == ["orders"]


class TestDeadlineInterruptsAnAwaitingStep:
    @pytest.mark.asyncio
    async def test_a_step_parked_on_an_await_is_cancelled(self):
        finished: list[str] = []

        async def sync_orders(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            await asyncio.sleep(30)
            finished.append("orders")

        # The clock is frozen, so every budget CHECK passes and the only thing
        # under test is whether `wait_for` cancels a parked coroutine. Nothing
        # here asserts on real elapsed time.
        deadline = _CycleDeadline(budget_seconds=0.05, clock=lambda: 0.0)

        with pytest.raises(PollCycleTimeoutError):
            await _run(_step("orders", ORDER_SEARCH_PATH, sync_orders), deadline)

        # Cancelled, not merely reported: the coroutine never reached its end.
        assert finished == []


class TestDeadlineCannotInterruptBlockingVendorIo:
    @pytest.mark.asyncio
    async def test_a_synchronous_call_runs_to_completion_despite_the_budget(self):
        """The documented limit, pinned so it cannot be quietly overclaimed.

        `requests` and redis-py are synchronous. While one is in flight the
        event loop is not running, so `asyncio.wait_for`'s timer cannot fire
        and the step completes regardless of the budget. The bound that does
        apply to blocking vendor I/O lives a layer down: the per-request socket
        timeout, and the between-pages budget in `pagination_scope`.
        """
        finished: list[str] = []

        async def sync_orders(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            time.sleep(0.15)  # stands in for a blocking requests call
            finished.append("orders")

        # Same frozen clock: the checks pass, `wait_for` gets a 20ms timeout,
        # and the step blocks the thread for 150ms -- 7.5x the margin. It still
        # finishes, because a blocked thread cannot run the loop's timer.
        deadline = _CycleDeadline(budget_seconds=0.02, clock=lambda: 0.0)

        await _run(_step("orders", ORDER_SEARCH_PATH, sync_orders), deadline)

        assert finished == ["orders"]


class TestBudgetConfiguration:
    def test_the_cycle_budget_is_env_configurable(self, monkeypatch):
        monkeypatch.setenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", "42")
        assert orchestrate_module.cycle_budget_seconds() == 42.0

    def test_the_cycle_budget_has_a_default(self, monkeypatch):
        monkeypatch.delenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", raising=False)
        assert orchestrate_module.cycle_budget_seconds() > 0

    def test_remaining_never_goes_negative(self):
        deadline = _CycleDeadline(budget_seconds=10.0, clock=_fixed_clock([0.0, 99.0]))
        assert deadline.remaining() == 0.0


class TestTheStageRunsUnderTheRemainingCycleBudget:
    """#1969 review, finding F3: the min-composition line was a mutation survivor.

    `TestNestedScopesComposeByMinimum` in `test_tiktok_pagination_budget.py`
    proves `pagination_scope` composes by `min` in ISOLATION. Nothing proved the
    orchestrator ever publishes the cycle's remaining wall clock INTO that
    scope -- so deleting `with pagination_scope(budget_seconds=remaining):`
    from `_within_cycle_budget` left the entire unit suite green while removing
    the whole fix for the defect this issue is named for: a 1800s cycle could
    still start a 600s fetch at 1799s, a ~40-minute composed worst case.

    These two tests are the seam. The first pins that a scope is published at
    all and carries no more than `deadline.remaining()`. The second pins the
    composition a real step actually performs: `sync_orders` and friends open
    their own `pagination_scope`, and that inner scope must be capped by what
    is left of the cycle even when it asks for the generous default.
    """

    @pytest.mark.asyncio
    async def test_the_step_body_sees_a_scope_carrying_what_is_left_of_the_cycle(self):
        seen: list[Any] = []

        async def sync_orders(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            seen.append(current_pagination_scope())

        # 1800s budget, 1700s already burnt: 100s left, well inside the 600s
        # default a fetch would otherwise help itself to.
        deadline = _CycleDeadline(budget_seconds=1800.0, clock=_fixed_clock([0.0, 1700.0]))

        await _run(_step("orders", ORDER_SEARCH_PATH, sync_orders), deadline)

        assert len(seen) == 1
        scope = seen[0]
        assert scope is not None, "the orchestrator published no pagination scope at all"
        assert scope.budget_seconds is not None
        assert scope.budget_seconds <= deadline.remaining() == 100.0
        assert scope.budget_seconds < client_module.default_fetch_budget_seconds()

    @pytest.mark.asyncio
    async def test_a_fetch_asking_for_the_default_budget_is_capped_by_the_cycle(self):
        inner_budgets: list[float | None] = []

        async def sync_orders(
            *,
            resource: Any,
            rate_limiter: RateLimiter,
            handoff_fn: Any,
            app_id: str,
            shop_id: str,
            sync_state: dict[str, Any],
        ) -> None:
            # Exactly what every real `sync_*` does before calling the client.
            with pagination_scope() as inner:
                inner_budgets.append(inner.budget_seconds)

        deadline = _CycleDeadline(budget_seconds=1800.0, clock=_fixed_clock([0.0, 1700.0]))

        await _run(_step("orders", ORDER_SEARCH_PATH, sync_orders), deadline)

        assert inner_budgets == [100.0]
        # Without the outer scope this is the 600s default, and the two budgets
        # compose by addition instead of by `min`.
        assert inner_budgets[0] < client_module.default_fetch_budget_seconds()


# --------------------------------------------------------------------------
# Entrypoint-level coverage (#1969 review, mutation 7).
#
# Everything above exercises `_CycleDeadline` and `_run_poll_step` directly.
# That left the budget's only two real callers untested: setting
# `_CycleDeadline(budget_seconds=inf)` inside `run_fujiwa_poll_cycle` and
# `run_fujiwa_material_resource_fetch` disabled the entire wall-clock budget --
# all of defect 3 -- with every test still green.
#
# These tests reach the deadline the only way a caller can, through
# `TIKTOK_POLL_CYCLE_BUDGET_SECONDS`, so a hardcoded budget at either entrypoint
# fails them.
# --------------------------------------------------------------------------

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"

# Long enough that a cancelled await is unambiguous, short enough that a run
# with the budget mutated away fails in seconds rather than minutes.
_HANDOFF_HANG_SECONDS = 10.0
_CYCLE_BUDGET_SECONDS = "1"


async def _stub_binding_verifier(session, *, capability, access_token) -> str:
    return "ROW_stub_cipher"


@pytest_asyncio.fixture
async def budget_shop(session, user_id):
    session.add(User(id=user_id, phone="+84901234599"))
    await session.flush()
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Budget Test Shop",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add(shop)
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def budget_credential(session, budget_shop):
    return await TikTokCredentialRepo(session).create(
        shop_id=budget_shop.id,
        access_token="fujiwa_access",
        refresh_token="fujiwa_refresh",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher="ROW_test_cipher",
    )


@pytest.fixture
def hanging_handoff():
    """A handoff that parks on a real await — what the budget CAN interrupt."""

    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        await asyncio.sleep(_HANDOFF_HANG_SECONDS)

    return _handoff


@pytest.fixture
def one_row_resources():
    resources = MagicMock()
    resources.orders.search_all.return_value = [{"id": "o1", "update_time": 1700000100}]
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"inventory": []}
    resources.analytics.list_sku_performance_all.return_value = []
    resources.analytics.list_product_performance_all.return_value = []
    resources.analytics.get_shop_performance.return_value = {}
    resources.analytics.get_shop_performance_per_hour.return_value = {}
    resources.analytics.get_bestselling_products.return_value = {}
    resources.analytics.get_bestselling_videos.return_value = {}
    resources.promotion.get_activity.return_value = {}
    return resources


@pytest.fixture
def oauth_service_for_budget(session):
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            base_url="https://open-api.tiktokglobalshop.com",
        ),
        session=session,
        redirect_uri="https://example.com/callback",
        app_secret=APP_SECRET,
        binding_verifier=_stub_binding_verifier,
    )


class TestBothEntrypointsRunUnderTheCycleBudget:
    """Kills mutation 7: a hardcoded budget at either entrypoint fails here."""

    @pytest.mark.asyncio
    async def test_run_fujiwa_poll_cycle_honours_the_configured_budget(
        self,
        monkeypatch,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
        hanging_handoff,
    ):
        monkeypatch.setenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", _CYCLE_BUDGET_SECONDS)

        with pytest.raises(PollCycleTimeoutError) as excinfo:
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=oauth_service_for_budget,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=hanging_handoff,
                resolve_credential=AsyncMock(return_value=budget_credential),
                create_resources=lambda _cfg: one_row_resources,
            )

        assert excinfo.value.budget_seconds == float(_CYCLE_BUDGET_SECONDS)

    @pytest.mark.asyncio
    async def test_run_fujiwa_material_resource_fetch_honours_the_configured_budget(
        self,
        monkeypatch,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
        hanging_handoff,
    ):
        monkeypatch.setenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", _CYCLE_BUDGET_SECONDS)

        with pytest.raises(PollCycleTimeoutError) as excinfo:
            await run_fujiwa_material_resource_fetch(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=oauth_service_for_budget,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=hanging_handoff,
                resolve_credential=AsyncMock(return_value=budget_credential),
                create_resources=lambda _cfg: one_row_resources,
            )

        assert excinfo.value.budget_seconds == float(_CYCLE_BUDGET_SECONDS)

    @pytest.mark.asyncio
    async def test_a_generous_budget_lets_the_same_cycle_complete(
        self,
        monkeypatch,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
    ):
        """The budget is the reason the two tests above raise — not the fixtures."""
        monkeypatch.setenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", "600")
        handed_off: list[str] = []

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            handed_off.append(channel)

        await run_fujiwa_poll_cycle(
            session=session,
            config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            oauth_service=oauth_service_for_budget,
            rate_limiter=NeverExhaustedRateLimiter(),
            handoff_fn=_handoff,
            resolve_credential=AsyncMock(return_value=budget_credential),
            create_resources=lambda _cfg: one_row_resources,
        )

        assert "tiktok.orders.raw" in handed_off


class TestPartialStateSurvivesAMidCycleFailure:
    """#1969 review: widened from `PollCycleTimeoutError` to any failure.

    A step that dies partway leaves earlier steps' watermarks in `sync_state`.
    Discarding them makes the next cycle refetch a larger delta under the
    INCREMENTAL 20-page cap, where over-running truncates with only a warning —
    so a loud failure would silently enlarge the next read.
    """

    @pytest.mark.asyncio
    async def test_a_failing_step_still_persists_earlier_watermarks(
        self,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
    ):
        saved: list[dict] = []

        class RecordingSyncStateRepo:
            async def load(self, shop_id) -> dict:
                return {}

            async def save(self, shop_id, state: dict) -> None:
                saved.append(dict(state))

            # Declared because `_record_cycle` calls it inside a guarded `try`
            # (#1950). A double missing it would let this test pass while
            # production logged `poll_cycle_outcome_record_failed` every cycle.
            async def record_outcomes(self, shop_id, outcomes) -> None:
                return None

        # Orders succeed; products blow up the way a malformed payload would.
        one_row_resources.products.search_all.side_effect = RuntimeError("vendor payload is junk")

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            return None

        with pytest.raises(RuntimeError):
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=oauth_service_for_budget,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=_handoff,
                resolve_credential=AsyncMock(return_value=budget_credential),
                create_resources=lambda _cfg: one_row_resources,
                sync_state_repo=RecordingSyncStateRepo(),
            )

        assert saved, "a mid-cycle failure must still persist what completed"
        assert saved[-1]["orders_last_update_time"] == 1700000100

    @pytest.mark.asyncio
    async def test_a_failing_save_does_not_mask_the_original_failure(
        self,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
    ):
        class PoisonedSyncStateRepo:
            async def load(self, shop_id) -> dict:
                return {}

            async def save(self, shop_id, state: dict) -> None:
                raise RuntimeError("session is poisoned")

            async def record_outcomes(self, shop_id, outcomes) -> None:
                raise RuntimeError("session is poisoned")

        one_row_resources.products.search_all.side_effect = ValueError("the real failure")

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            return None

        # ValueError, not the save's RuntimeError: trading a diagnosable failure
        # for an undiagnosable one is exactly what the guarded save prevents.
        with pytest.raises(ValueError, match="the real failure"):
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=oauth_service_for_budget,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=_handoff,
                resolve_credential=AsyncMock(return_value=budget_credential),
                create_resources=lambda _cfg: one_row_resources,
                sync_state_repo=PoisonedSyncStateRepo(),
            )


class TestTheClockCoversTheCredentialResolve:
    """The deadline starts BEFORE `resolve`, and that is easy to lose.

    #1967 collapsed both entrypoints into one `_poll()` that receives an
    already-resolved credential. Building the deadline inside `_poll` compiles,
    passes every other test, and silently narrows what the budget measures:
    `resolve_production_read_credential` does DB work and can refresh a token
    over HTTP, and that time is held by the beat slot just the same.

    So this test makes the resolve itself the slow thing. It fails if the
    deadline is constructed anywhere after the resolve.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "entrypoint", [run_fujiwa_poll_cycle, run_fujiwa_material_resource_fetch]
    )
    async def test_a_slow_resolve_alone_can_exhaust_the_budget(
        self,
        entrypoint,
        monkeypatch,
        session,
        budget_credential,
        oauth_service_for_budget,
        one_row_resources,
    ):
        monkeypatch.setenv("TIKTOK_POLL_CYCLE_BUDGET_SECONDS", "0.5")

        # Two parameters since #1995: `ResolveCredentialFn` carries the shop.
        async def _slow_resolve(_session, _shop_id):
            await asyncio.sleep(2.0)
            return budget_credential

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            return None

        # Every vendor call below is instant; the only expensive thing in the
        # cycle is the resolve. If the clock did not cover it, nothing here
        # would come close to a 0.5s budget.
        with pytest.raises(PollCycleTimeoutError) as excinfo:
            await entrypoint(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=oauth_service_for_budget,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=_handoff,
                resolve_credential=_slow_resolve,
                create_resources=lambda _cfg: one_row_resources,
            )

        assert excinfo.value.elapsed_seconds >= 2.0
