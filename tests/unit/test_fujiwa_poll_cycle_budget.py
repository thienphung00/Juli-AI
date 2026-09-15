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
import time
from typing import Any

import pytest

from juli_backend.integrations.tiktok import ORDER_SEARCH_PATH, PRODUCT_SEARCH_PATH, RateLimiter
from juli_backend.workers.services.polling import orchestrate as orchestrate_module
from juli_backend.workers.services.polling.orchestrate import (
    PollCycleTimeoutError,
    _CycleDeadline,
    _PollStep,
    _run_poll_step,
)

SHOP_KEY = "7494001234567890123"


class _Resources:
    def __init__(self) -> None:
        self.orders = object()
        self.products = object()


class NeverExhaustedRateLimiter:
    """Signature-bound stand-in for the `RateLimiter` calls orchestrate.py makes."""

    def is_exhausted(
        self, app_id: str, shop_id: str, endpoint: str, *, max_requests: int = 10
    ) -> bool:
        return False

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


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
