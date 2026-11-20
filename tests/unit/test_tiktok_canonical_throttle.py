"""P101 W2 B-3b: every Partner call for a shop reports a TikTok 429 (100005) to the limiter.

A fake client raising ``RateLimitError`` makes ``note_throttled`` run once, for that shop; the
next ``acquire`` for that shop is refused while another shop is unaffected. A call that returns
runs ``note_success``. Covered call sites: the poll steps (``polling.sync``), the analytics range
wrapper (``polling.analytics_range._list_call``), the order-cost pass
(``order_costs.sync._Pass.call``) and the canonical re-fetch (``order_details_fetcher``).
Redis is the in-memory fake of the B-3 limiter test; nothing reaches TikTok."""

from __future__ import annotations

from typing import Any

import pytest

from juli_backend.integrations.tiktok import RateLimiter, RateLimitError
from juli_backend.services.ingest import tiktok_canonical as tc
from juli_backend.services.ingest.tiktok_canonical_throttle import noted_call
from juli_backend.services.order_costs.sync import PassResult, _Pass
from juli_backend.workers.services.polling import analytics_range
from juli_backend.workers.services.polling.sync import sync_orders
from tests.unit.test_tiktok_rate_limit_backoff import FakeRedis

APP = "app"
SHOP = "tt-shop-a"
OTHER = "tt-shop-b"
PATH = "/order/202309/orders/search"


class _SpyLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__(FakeRedis(), jitter=lambda: 0.0)
        self.throttled: list[tuple[str, str]] = []
        self.successes: list[tuple[str, str]] = []

    def note_throttled(self, app_id: str, shop_id: str) -> int:
        self.throttled.append((app_id, shop_id))
        return super().note_throttled(app_id, shop_id)

    def note_success(self, app_id: str, shop_id: str) -> None:
        self.successes.append((app_id, shop_id))
        super().note_success(app_id, shop_id)


def _throttle(*_a: Any, **_k: Any) -> Any:
    raise RateLimitError(100005, "too many requests")


def _assert_only_that_shop_is_paused(limiter: _SpyLimiter) -> None:
    assert limiter.throttled == [(APP, SHOP)]
    assert limiter.acquire(APP, SHOP, PATH, 10, 60) is False
    assert limiter.acquire(APP, OTHER, PATH, 10, 60) is True


def test_noted_call_notes_a_throttle_and_re_raises_it_unchanged() -> None:
    limiter = _SpyLimiter()

    with pytest.raises(RateLimitError) as excinfo:
        noted_call(limiter, APP, SHOP, _throttle)

    assert excinfo.value.code == 100005
    _assert_only_that_shop_is_paused(limiter)
    assert noted_call(limiter, APP, OTHER, lambda x: x + 1, 1) == 2
    assert limiter.successes == [(APP, OTHER)]


def test_noted_call_leaves_a_limiter_without_backoff_alone() -> None:
    class Plain:
        pass

    with pytest.raises(RateLimitError) as excinfo:
        noted_call(Plain(), APP, SHOP, _throttle)
    assert excinfo.value.code == 100005


async def test_a_throttled_poll_step_pauses_that_shop() -> None:
    class Orders:
        def search_all(self, **_: Any) -> list[dict]:
            raise RateLimitError(100005, "too many requests")

    async def handoff(*_a: Any) -> None:
        return None

    limiter = _SpyLimiter()
    outcome = await sync_orders(
        resource=Orders(),
        rate_limiter=limiter,
        handoff_fn=handoff,
        app_id=APP,
        shop_id=SHOP,
        sync_state={"orders_last_update_time": 1},
    )

    assert outcome.ok is False
    _assert_only_that_shop_is_paused(limiter)


async def test_a_successful_poll_step_resets_the_strikes() -> None:
    class Orders:
        def search_all(self, **_: Any) -> list[dict]:
            return []

    async def handoff(*_a: Any) -> None:
        return None

    limiter = _SpyLimiter()
    await sync_orders(
        resource=Orders(),
        rate_limiter=limiter,
        handoff_fn=handoff,
        app_id=APP,
        shop_id=SHOP,
        sync_state={"orders_last_update_time": 1},
    )

    assert (limiter.successes, limiter.throttled) == ([(APP, SHOP)], [])


async def test_a_throttled_analytics_call_pauses_that_shop() -> None:
    limiter = _SpyLimiter()

    async def no_sleep(_s: float) -> None:
        return None

    response, error, refused = await analytics_range._list_call(
        _throttle,
        endpoint="/analytics/202405/shop/performance",
        label="shop_performance",
        rate_limiter=limiter,
        app_id=APP,
        shop_id=SHOP,
        sleep=no_sleep,
        wait_on_rate_limit=False,
        deadline=None,
        counters=analytics_range._Counters(),
    )

    assert (response, refused, isinstance(error, RateLimitError)) == (None, False, True)
    _assert_only_that_shop_is_paused(limiter)


async def test_a_throttled_order_cost_call_pauses_that_shop_and_ends_the_pass() -> None:
    limiter = _SpyLimiter()
    result = PassResult()
    one = _Pass(
        result=result,
        rate_limiter=limiter,
        app_id=APP,
        shop_key=SHOP,
        deadline=None,
        label="finance",
    )

    response, error = await one.call(
        "/finance/202501/orders/{order_id}/statement_transactions", _throttle
    )

    assert (response, error, result.rate_limited) == (None, None, True)
    _assert_only_that_shop_is_paused(limiter)


def test_a_throttled_canonical_refetch_pauses_that_shop_and_re_raises() -> None:
    class Detail:
        def get_details(self, _ids: list[str]) -> dict:
            raise RateLimitError(100005, "too many requests")

    limiter = _SpyLimiter()
    fetch = tc.order_details_fetcher(Detail(), rate_limiter=limiter, app_id=APP, shop_id=SHOP)

    with pytest.raises(RateLimitError) as excinfo:
        fetch(["1"])

    assert excinfo.value.code == 100005 and isinstance(excinfo.value, tc.ORDER_REFETCH_ERRORS)
    _assert_only_that_shop_is_paused(limiter)
