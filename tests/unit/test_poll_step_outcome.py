"""Every poll step reports a verdict, not silence (#1969, #1950).

Defect 2 of #1969: a cycle ran 47 minutes and emitted nothing between start
and a pagination warning, so a working poll and a wedged one looked identical
from outside. Defect shared with #1950: a step that fetched rows and persisted
none was indistinguishable from a step that had nothing to do.

Doubles here are bound to the real signatures -- `OrdersResource.search_all`,
`ReturnsResource.search_returns_all`, `HandoffFn` -- so a contract change
breaks these tests instead of sliding past a `**kwargs` stand-in.
"""

from __future__ import annotations

import logging

import pytest

from juli_backend.integrations.tiktok.exceptions import TikTokSystemError
from juli_backend.workers.services.polling import sync as sync_module
from juli_backend.workers.services.polling.sync import (
    PollStepDroppedRowsError,
    SyncOutcome,
    sync_orders,
    sync_products,
    sync_returns,
)

SHOP_ID = "7494001234567890123"


class FakeOrdersResource:
    """Signature-bound stand-in for `OrdersResource.search_all`."""

    def __init__(self, orders: list[dict] | None = None, error: Exception | None = None) -> None:
        self._orders = orders or []
        self._error = error
        self.calls: list[dict] = []

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        self.calls.append({"update_time_from": update_time_from})
        if self._error is not None:
            raise self._error
        return list(self._orders)


class FakeProductsResource:
    """Signature-bound stand-in for `ProductsResource.search_all`."""

    def __init__(self, products: list[dict] | None = None) -> None:
        self._products = products or []

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        return list(self._products)


class FakeReturnsResource:
    """Signature-bound stand-in for `ReturnsResource.search_returns_all`."""

    def __init__(self, returns: list[dict] | None = None) -> None:
        self._returns = returns or []

    def search_returns_all(
        self,
        *,
        return_status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        return list(self._returns)


class AllowingRateLimiter:
    """Signature-bound stand-in for the `RateLimiter` calls sync.py makes."""

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        *,
        max_requests: int = 10,
        window_seconds: int = 60,
    ) -> bool:
        return True

    def is_exhausted(
        self, app_id: str, shop_id: str, endpoint: str, *, max_requests: int = 10
    ) -> bool:
        return False

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


class DenyingRateLimiter(AllowingRateLimiter):
    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        *,
        max_requests: int = 10,
        window_seconds: int = 60,
    ) -> bool:
        return False


class RecordingHandoff:
    """Bound to `HandoffFn = Callable[[str, str, bytes], Awaitable[None]]`."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[tuple[str, str, bytes]] = []
        self._fail_after = fail_after

    async def __call__(self, channel: str, shop_key: str, value: bytes) -> None:
        if self._fail_after is not None and len(self.calls) >= self._fail_after:
            raise RuntimeError("etl refused the row")
        self.calls.append((channel, shop_key, value))


def _outcome_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.message == "poll_step_outcome"]


@pytest.fixture
def rate_limiter() -> AllowingRateLimiter:
    return AllowingRateLimiter()


class TestOutcomeTriple:
    @pytest.mark.asyncio
    async def test_a_successful_step_returns_and_logs_the_triple(self, rate_limiter, caplog):
        resource = FakeOrdersResource(
            [
                {"order_id": "o1", "update_time": 1700000100, "line_items": []},
                {"order_id": "o2", "update_time": 1700000200, "line_items": []},
            ]
        )
        handoff = RecordingHandoff()

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=handoff,
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={"orders_last_update_time": 1699999999},
            )

        assert isinstance(outcome, SyncOutcome)
        assert outcome.resource == "orders"
        assert outcome.fetched == 2
        assert outcome.persisted == 2
        assert outcome.failed == 0
        assert outcome.error is None
        assert outcome.ok is True

        (record,) = _outcome_records(caplog)
        assert record.fetched == 2
        assert record.persisted == 2
        assert record.failed == 0
        assert record.ok is True

    @pytest.mark.asyncio
    async def test_a_step_that_fetched_rows_and_persisted_none_is_a_failure(
        self, rate_limiter, caplog
    ):
        resource = FakeOrdersResource(
            [{"order_id": "o1", "update_time": 1700000100, "line_items": []}]
        )
        handoff = RecordingHandoff(fail_after=0)
        sync_state = {"orders_last_update_time": 1699999999}

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(PollStepDroppedRowsError) as excinfo:
                await sync_orders(
                    resource=resource,
                    rate_limiter=rate_limiter,
                    handoff_fn=handoff,
                    app_id="app1",
                    shop_id=SHOP_ID,
                    sync_state=sync_state,
                )

        outcome = excinfo.value.outcome
        assert outcome.fetched == 1
        assert outcome.persisted == 0
        assert outcome.failed == 1
        assert outcome.ok is False

        # The verdict is logged before it is raised, so the triple survives
        # even when the caller only sees the traceback.
        (record,) = _outcome_records(caplog)
        assert record.persisted == 0
        assert record.ok is False

        # And the watermark must not move over rows that never landed.
        assert sync_state["orders_last_update_time"] == 1699999999

    @pytest.mark.asyncio
    async def test_a_partial_persist_counts_both_sides_and_does_not_raise(
        self, rate_limiter, caplog
    ):
        resource = FakeOrdersResource(
            [
                {"order_id": "o1", "update_time": 1700000100, "line_items": []},
                {"order_id": "o2", "update_time": 1700000200, "line_items": []},
            ]
        )
        handoff = RecordingHandoff(fail_after=1)

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=handoff,
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={"orders_last_update_time": 1699999999},
            )

        assert outcome.fetched == 2
        assert outcome.persisted == 1
        assert outcome.failed == 1
        assert outcome.ok is False

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_read_is_not_a_failure(self, rate_limiter, caplog):
        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_products(
                resource=FakeProductsResource([]),
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={"products_last_update_time": 1699999999},
            )

        assert outcome.fetched == 0
        assert outcome.persisted == 0
        assert outcome.ok is True

    @pytest.mark.asyncio
    async def test_a_fetch_error_is_reported_as_a_failed_step_not_a_quiet_return(
        self, rate_limiter, caplog
    ):
        resource = FakeOrdersResource(error=TikTokSystemError(code=100006, message="System error"))

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={"orders_last_update_time": 1699999999},
            )

        assert outcome.error is not None
        assert outcome.ok is False
        (record,) = _outcome_records(caplog)
        assert record.ok is False
        assert record.error

    @pytest.mark.asyncio
    async def test_a_rate_limited_step_still_emits_an_outcome(self, caplog):
        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_returns(
                resource=FakeReturnsResource([{"return_id": "r1", "update_time": 1}]),
                rate_limiter=DenyingRateLimiter(),
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={},
            )

        assert outcome.resource == "returns"
        assert outcome.skipped is True
        (record,) = _outcome_records(caplog)
        assert record.skipped is True


class TestColdStartUsesTheBackfillBudget:
    @pytest.mark.asyncio
    async def test_a_shop_with_no_watermark_fetches_under_a_backfill_scope(self, rate_limiter):
        seen: list[bool] = []

        class ScopeSniffingResource(FakeOrdersResource):
            def search_all(self, **kwargs) -> list[dict]:
                from juli_backend.integrations.tiktok.client import current_pagination_scope

                scope = current_pagination_scope()
                seen.append(scope is not None and scope.backfill)
                return super().search_all(**kwargs)

        await sync_orders(
            resource=ScopeSniffingResource([]),
            rate_limiter=rate_limiter,
            handoff_fn=RecordingHandoff(),
            app_id="app1",
            shop_id=SHOP_ID,
            sync_state={},
        )

        assert seen == [True]

    @pytest.mark.asyncio
    async def test_a_shop_with_a_watermark_fetches_under_an_incremental_scope(self, rate_limiter):
        seen: list[bool] = []

        class ScopeSniffingResource(FakeOrdersResource):
            def search_all(self, **kwargs) -> list[dict]:
                from juli_backend.integrations.tiktok.client import current_pagination_scope

                scope = current_pagination_scope()
                seen.append(scope is not None and scope.backfill)
                return super().search_all(**kwargs)

        await sync_orders(
            resource=ScopeSniffingResource([]),
            rate_limiter=rate_limiter,
            handoff_fn=RecordingHandoff(),
            app_id="app1",
            shop_id=SHOP_ID,
            sync_state={"orders_last_update_time": 1699999999},
        )

        assert seen == [False]

    @pytest.mark.asyncio
    async def test_the_outcome_carries_pages_fetched_and_the_backfill_flag(self, rate_limiter):
        outcome = await sync_orders(
            resource=FakeOrdersResource([]),
            rate_limiter=rate_limiter,
            handoff_fn=RecordingHandoff(),
            app_id="app1",
            shop_id=SHOP_ID,
            sync_state={},
        )

        assert outcome.backfill is True
        assert outcome.pages == 0  # the fake never went through the paginator
