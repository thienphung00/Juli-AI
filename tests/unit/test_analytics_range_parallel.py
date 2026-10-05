"""Date-range analytics with bounded-parallel detail calls (fast track AC-1.7, SPEC §3.4–3.5).

The detail calls run in worker threads (the vendor client is synchronous
``requests``); the ETL handoff must stay on the event loop, and the rate
limiter and cycle budget must still gate every call.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest

from juli_backend.workers.services.polling.analytics_range import (
    DETAIL_CONCURRENCY_ENV,
    iter_windows,
    sync_analytics_range,
)
from juli_backend.workers.services.polling.orchestrate import PollCycleTimeoutError
from tests.support.shop_ingestion_fakes import FakeAnalyticsResource, FakeRateLimiter

LATEST = date(2026, 7, 15)
START = LATEST - timedelta(days=29)
END = LATEST + timedelta(days=1)


class _Handoff:
    def __init__(self) -> None:
        self.threads: set[int] = set()
        self.rows: list[tuple[str, str]] = []

    async def __call__(self, channel: str, shop_key: str, payload: bytes) -> None:
        self.threads.add(threading.get_ident())
        self.rows.append((channel, shop_key))


async def _no_sleep(_seconds: float) -> None:
    return None


async def _run(analytics, *, rate_limiter=None, handoff=None, **kwargs):
    return await sync_analytics_range(
        resource=analytics,
        rate_limiter=rate_limiter or FakeRateLimiter(),
        handoff_fn=handoff or _Handoff(),
        app_id="app",
        shop_id="tt-shop",
        start=kwargs.pop("start", START),
        end_exclusive=kwargs.pop("end_exclusive", END),
        sleep=kwargs.pop("sleep", _no_sleep),
        **kwargs,
    )


def _many(n: int) -> tuple[str, ...]:
    return tuple(f"p{i}" for i in range(n))


@pytest.mark.asyncio
async def test_detail_calls_run_concurrently_up_to_the_bound():
    analytics = FakeAnalyticsResource(products=_many(12), skus=(), detail_delay=0.05)
    handoff = _Handoff()
    main = threading.get_ident()

    result = await _run(analytics, handoff=handoff, concurrency=3)

    assert analytics.peak_in_flight == 3, "bounded, and actually parallel"
    assert result.detail_calls == 12
    detail_threads = {c["thread"] for c in analytics.calls["get_product_performance"]}
    assert main not in detail_threads, "vendor calls leave the event loop thread"
    assert handoff.threads == {main}, "every DB handoff stays on the event loop"
    # 12 products x 30 daily rows from ONE call each.
    assert sum(1 for c, _ in handoff.rows if c == "tiktok.analytics.product.raw") == 12 * 30
    assert len(result.days_with_rows) == 30
    assert result.complete


@pytest.mark.asyncio
async def test_the_pool_size_is_configurable(monkeypatch):
    monkeypatch.setenv(DETAIL_CONCURRENCY_ENV, "2")
    analytics = FakeAnalyticsResource(products=_many(8), skus=(), detail_delay=0.03)
    await _run(analytics)
    assert analytics.peak_in_flight == 2


@pytest.mark.asyncio
async def test_the_rate_limiter_gates_every_parallel_call_and_backs_off():
    limiter = FakeRateLimiter(global_detail_limit=4)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        limiter.reset()

    analytics = FakeAnalyticsResource(products=_many(10), skus=(), detail_delay=0.01)
    result = await _run(analytics, rate_limiter=limiter, sleep=sleep, concurrency=5)

    assert result.detail_calls == 10 and result.complete
    assert sleeps, "the exhausted window was waited out, not ignored"
    # Never more than the window allows between two resets.
    window = 0
    for kind, endpoint in limiter.events:
        if kind == "reset":
            window = 0
        elif kind == "acquired" and limiter._is_detail(endpoint):
            window += 1
            assert window <= 4
    assert len(analytics.calls["get_product_performance"]) == 10


@pytest.mark.asyncio
async def test_without_waiting_a_refused_window_stops_detail_calls_and_marks_incomplete():
    limiter = FakeRateLimiter(global_detail_limit=4)
    analytics = FakeAnalyticsResource(products=_many(10), skus=())
    result = await _run(analytics, rate_limiter=limiter, wait_on_rate_limit=False, concurrency=3)
    assert result.detail_calls == 4
    assert len(analytics.calls["get_product_performance"]) == 4
    assert result.rate_limited and not result.complete


class _Deadline:
    """Raises once `allowed` checks have passed -- a budget that runs out mid-pool."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.checks = 0

    def check(self, *, stage: str) -> float:
        self.checks += 1
        if self.checks > self.allowed:
            raise PollCycleTimeoutError(stage=stage, budget_seconds=1.0, elapsed_seconds=2.0)
        return 1.0


@pytest.mark.asyncio
async def test_the_cycle_budget_stops_new_detail_calls():
    analytics = FakeAnalyticsResource(products=_many(20), skus=(), detail_delay=0.01)
    # 1 check for the (empty-sku) list, 1 for the product list, then 5 details.
    deadline = _Deadline(allowed=7)
    with pytest.raises(PollCycleTimeoutError):
        await _run(analytics, deadline=deadline, concurrency=2)
    assert len(analytics.calls["get_product_performance"]) <= 5


@pytest.mark.asyncio
async def test_a_range_is_one_call_per_item_not_one_per_day():
    analytics = FakeAnalyticsResource(products=_many(3), skus=(("s1", "p0"),))
    result = await _run(analytics)
    assert len(analytics.calls["get_product_performance"]) == 3
    assert len(analytics.calls["get_sku_performance"]) == 1
    assert len(analytics.calls["get_shop_performance"]) == 1
    assert result.latest_available_date == LATEST


def test_a_long_range_is_split_into_bounded_windows(monkeypatch):
    monkeypatch.setenv("TIKTOK_ANALYTICS_MAX_RANGE_DAYS", "30")
    windows = iter_windows(date(2026, 1, 1), date(2026, 3, 2), 30)
    assert windows == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 1, 31), date(2026, 3, 2)),
    ]


@pytest.mark.asyncio
async def test_aggregate_intervals_are_never_stored_as_a_day():
    """If the vendor answered a range with ONE aggregate interval, writing it
    would put a 30-day total into a one-day row. Shop performance falls back to
    per-day calls; detail aggregates are dropped and counted."""
    analytics = FakeAnalyticsResource(products=("p1",), skus=())

    def aggregate_product(*, product_id, start_date_ge, end_date_lt):
        analytics._record("get_product_performance", id=product_id, start=start_date_ge)
        return {
            "latest_available_date": LATEST.isoformat(),
            "performance": {
                "intervals": [
                    {
                        "start_date": start_date_ge,
                        "end_date": end_date_lt,
                        "sales": {"gmv": {"amount": "1", "currency": "VND"}, "orders": 1},
                    }
                ]
            },
        }

    real_shop = analytics.get_shop_performance

    def aggregate_shop(*, start_date_ge, end_date_lt):
        if (date.fromisoformat(end_date_lt) - date.fromisoformat(start_date_ge)).days == 1:
            return real_shop(start_date_ge=start_date_ge, end_date_lt=end_date_lt)
        analytics._record("get_shop_performance", start=start_date_ge, end=end_date_lt)
        return {
            "latest_available_date": LATEST.isoformat(),
            "performance": {
                "intervals": [
                    {
                        "start_date": start_date_ge,
                        "end_date": end_date_lt,
                        "sales": {"gmv": {"overall": {"amount": "9", "currency": "VND"}}},
                    }
                ]
            },
        }

    analytics.get_product_performance = aggregate_product  # type: ignore[method-assign]
    analytics.get_shop_performance = aggregate_shop  # type: ignore[method-assign]
    handoff = _Handoff()
    result = await _run(analytics, handoff=handoff)

    assert result.non_daily_rows_dropped >= 1
    assert not any(c == "tiktok.analytics.product.raw" for c, _ in handoff.rows)
    shop_rows = [c for c, _ in handoff.rows if c == "tiktok.analytics.shop.raw"]
    assert len(shop_rows) == 30, "re-fetched one day at a time"


@pytest.mark.asyncio
async def test_the_product_list_row_merge_hook_runs_only_for_single_day_windows(monkeypatch):
    """P1-A's `merge_product_analytics_rows` (when present) receives the A-34
    list row only when the window is one day -- a multi-day list row is an
    aggregate and must not be merged into a daily row."""
    from juli_backend.integrations.tiktok import mapping

    seen: list[object] = []

    def merge(detail_rows, list_row):
        seen.append(list_row)
        return detail_rows

    monkeypatch.setattr(mapping, "merge_product_analytics_rows", merge, raising=False)
    analytics = FakeAnalyticsResource(products=("p1",), skus=())

    await _run(analytics)
    assert seen == [], "30-day window: no list-row merge"

    await _run(analytics, start=LATEST, end_exclusive=LATEST + timedelta(days=1))
    assert len(seen) == 1 and seen[0] is not None
