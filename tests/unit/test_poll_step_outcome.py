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

from juli_backend.integrations.tiktok.client import TikTokPaginationTruncatedError
from juli_backend.integrations.tiktok.exceptions import TikTokSystemError
from juli_backend.workers.services.polling import sync as sync_module
from juli_backend.workers.services.polling.sync import (
    PollStepDroppedRowsError,
    SyncOutcome,
    sync_inventory,
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


# --------------------------------------------------------------------------
# Propagation coverage (#1969 review, mutation 5).
#
# Each step has an `except TikTokPaginationError: step.report(...); raise` arm.
# Replacing all four with a quiet return left 66 tests green: nothing catches
# that exception today, so the *type* claim held, but nothing stopped anyone
# reinstating the silence either — which is exactly the #1948 defect shape.
#
# A truncated cold-start backfill is the whole point of this issue. If it can be
# swallowed, a new seller's history is cut short and the cycle reports success.
# --------------------------------------------------------------------------


class _TruncatingResource:
    """Raises what a cold-start backfill raises when it outruns its page budget."""

    def __init__(self) -> None:
        self.error = TikTokPaginationTruncatedError(
            path="/order/202309/orders/search",
            pages=400,
            items=20_000,
            max_pages=400,
            total_count=100_000,
        )

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        raise self.error

    def search_returns_all(
        self,
        *,
        return_status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        raise self.error

    def search(self, *, product_ids: list[str] | None = None) -> dict:
        raise self.error


async def _one_product_id() -> list[str]:
    """Signature-bound stand-in for `ProductIdsFn` (#1948).

    Non-empty on purpose: an empty list is the ordinary cold-start state and
    returns before the fetch, which would make the propagation test below pass
    for the wrong reason.
    """
    return ["p-1"]


def _extra_kwargs_for(sync_fn) -> dict:
    return {"list_product_ids": _one_product_id} if sync_fn is sync_inventory else {}


class TestATruncatedBackfillEscapesEveryStep:
    """Kills mutation 5: a quiet return in any of the four arms fails here."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("sync_fn", "resource_name"),
        [
            (sync_orders, "orders"),
            (sync_products, "products"),
            (sync_returns, "returns"),
            (sync_inventory, "inventory"),
        ],
    )
    async def test_pagination_failure_propagates_out_of_the_step(
        self, sync_fn, resource_name, rate_limiter, caplog
    ):
        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(TikTokPaginationTruncatedError):
                await sync_fn(
                    resource=_TruncatingResource(),
                    rate_limiter=rate_limiter,
                    handoff_fn=RecordingHandoff(),
                    app_id="app1",
                    shop_id=SHOP_ID,
                    sync_state={},
                    **_extra_kwargs_for(sync_fn),
                )

        # Reported on the way out, not only raised: the operator sees a verdict
        # for the step even though the caller only gets a traceback.
        (record,) = _outcome_records(caplog)
        assert record.resource == resource_name
        assert record.ok is False
        assert record.backfill is True

    @pytest.mark.asyncio
    async def test_a_vendor_error_is_still_reported_rather_than_raised(self, rate_limiter, caplog):
        """The two arms are deliberately different, so pin the contrast.

        A `TikTokAPIError` on the fetch is reported and returned — that swallow
        predates this branch and #1948 left it in place for orders on purpose.
        A `TikTokPaginationError` is reported and re-raised. Without this test a
        future edit could collapse the two arms into one and only one direction
        would be caught.
        """
        resource = FakeOrdersResource(error=TikTokSystemError(code=100006, message="System error"))

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={},
            )

        assert outcome.ok is False
        assert outcome.error is not None


class TestAnOutcomeIsEmittedOnEveryExitPath:
    """`_StepRun.__exit__` reports when no arm did (#1969 review).

    A step used to emit `poll_step_started` and then nothing at all if an
    exception escaped that no arm anticipated — a malformed row blowing up a
    normalizer, say. From outside that is indistinguishable from a wedged poll,
    which is the very thing defect 2 is about.
    """

    @pytest.mark.asyncio
    async def test_an_unanticipated_exception_still_emits_an_outcome(
        self, rate_limiter, caplog, monkeypatch
    ):
        def _explode(_order: dict) -> dict:
            raise KeyError("malformed order payload")

        monkeypatch.setattr(sync_module, "normalize_order", _explode)
        resource = FakeOrdersResource([{"order_id": "o1", "update_time": 1700000100}])

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(KeyError):
                await sync_orders(
                    resource=resource,
                    rate_limiter=rate_limiter,
                    handoff_fn=RecordingHandoff(),
                    app_id="app1",
                    shop_id=SHOP_ID,
                    sync_state={},
                )

        (record,) = _outcome_records(caplog)
        assert record.resource == "orders"
        assert record.ok is False
        assert record.fetched == 1
        assert record.persisted == 0

    @pytest.mark.asyncio
    async def test_a_normal_step_still_emits_exactly_one_outcome(self, rate_limiter, caplog):
        """`report` is idempotent — `__exit__` must not double-log."""
        resource = FakeOrdersResource(
            [{"order_id": "o1", "update_time": 1700000100, "line_items": []}]
        )

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={},
            )

        assert len(_outcome_records(caplog)) == 1


class TestErrorDetailIsBounded:
    @pytest.mark.asyncio
    async def test_a_huge_vendor_error_does_not_land_whole_in_the_record(
        self, rate_limiter, caplog
    ):
        """`repr` of a vendor error can carry an entire response body."""
        resource = FakeOrdersResource(error=TikTokSystemError(code=100006, message="x" * 5_000))

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_orders(
                resource=resource,
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={},
            )

        assert outcome.error is not None
        assert len(outcome.error) <= sync_module._ERROR_DETAIL_LIMIT


class TestInventoryRaisesWhereTheOthersReport:
    """The #1948 / #1969 merge decision, pinned (#1969 review).

    #1948 made a vendor failure in this step propagate; #1969 gave every step an
    outcome triple. A textual merge cannot hold both, and the resolution is that
    inventory reports the triple AND raises. Without these tests the next merge
    would quietly pick one.
    """

    @pytest.mark.asyncio
    async def test_a_vendor_error_propagates_and_is_reported_first(self, rate_limiter, caplog):
        class FailingInventoryResource:
            def search(self, *, product_ids: list[str] | None = None) -> dict:
                raise TikTokSystemError(code=100006, message="System error")

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(TikTokSystemError):
                await sync_inventory(
                    resource=FailingInventoryResource(),
                    rate_limiter=rate_limiter,
                    handoff_fn=RecordingHandoff(),
                    app_id="app1",
                    shop_id=SHOP_ID,
                    sync_state={},
                    list_product_ids=_one_product_id,
                )

        # #1969's half of the bargain: the verdict is logged on the way out.
        (record,) = _outcome_records(caplog)
        assert record.resource == "inventory"
        assert record.ok is False
        assert record.error

    @pytest.mark.asyncio
    async def test_a_non_dict_response_propagates_too(self, rate_limiter, caplog):
        class WrongShapeInventoryResource:
            def search(self, *, product_ids: list[str] | None = None) -> list:
                return ["not", "a", "dict"]

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(ValueError, match="non-dict"):
                await sync_inventory(
                    resource=WrongShapeInventoryResource(),
                    rate_limiter=rate_limiter,
                    handoff_fn=RecordingHandoff(),
                    app_id="app1",
                    shop_id=SHOP_ID,
                    sync_state={},
                    list_product_ids=_one_product_id,
                )

        (record,) = _outcome_records(caplog)
        assert record.ok is False

    @pytest.mark.asyncio
    async def test_no_products_yet_is_a_clean_zero_not_a_failure(self, rate_limiter, caplog):
        """The ordinary cold-start state: nothing has synced yet, so nothing to ask for."""

        async def _no_products() -> list[str]:
            return []

        class UnusedInventoryResource:
            def search(self, *, product_ids: list[str] | None = None) -> dict:
                raise AssertionError("must not call the vendor with no product ids")

        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            outcome = await sync_inventory(
                resource=UnusedInventoryResource(),
                rate_limiter=rate_limiter,
                handoff_fn=RecordingHandoff(),
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state={},
                list_product_ids=_no_products,
            )

        assert outcome.ok is True
        assert outcome.fetched == 0
        assert len(_outcome_records(caplog)) == 1

    @pytest.mark.asyncio
    async def test_the_watermark_only_moves_when_rows_persisted(self, rate_limiter):
        class OneRowInventoryResource:
            def search(self, *, product_ids: list[str] | None = None) -> dict:
                return {
                    "inventory": [
                        {
                            "product_id": "p-1",
                            "skus": [
                                {
                                    "id": "sku-1",
                                    "total_available_quantity": 5,
                                    "warehouse_inventory": [{"warehouse_id": "wh-1"}],
                                }
                            ],
                        }
                    ]
                }

        sync_state: dict = {}
        outcome = await sync_inventory(
            resource=OneRowInventoryResource(),
            rate_limiter=rate_limiter,
            handoff_fn=RecordingHandoff(),
            app_id="app1",
            shop_id=SHOP_ID,
            sync_state=sync_state,
            list_product_ids=_one_product_id,
        )

        assert outcome.persisted > 0
        assert "inventory_last_sync_at" in sync_state
