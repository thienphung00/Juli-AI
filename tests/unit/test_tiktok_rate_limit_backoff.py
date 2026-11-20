"""P101 W2 B-3: a TikTok 429 pauses ONE shop with jitter, and the walk resumes.

``RateLimiter`` is the point every poll / history / analytics call acquires
through, so a backoff recorded here holds all three. Redis is an in-memory fake
with a movable clock; nothing reaches TikTok or a broker.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from juli_backend.integrations.tiktok import RateLimiter
from juli_backend.integrations.tiktok.rate_limiter import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
)
from juli_backend.repositories import ShopIngestionStateRepo
from juli_backend.services.onboarding import history_days_available

APP = "app"
SHOP_A = "shop-a"
SHOP_B = "shop-b"
ENDPOINT = "/analytics/202405/shop/performance"


class FakeRedis:
    """Sync Redis subset with TTLs against ``clock`` (seconds)."""

    def __init__(self) -> None:
        self.clock = 0.0
        self.values: dict[str, int] = {}
        self.expires: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        if key in self.expires and self.expires[key] <= self.clock:
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return key in self.values

    def incr(self, key: str) -> int:
        self._alive(key)
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        if self._alive(key):
            self.expires[key] = self.clock + seconds

    def set(self, key: str, value: int, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expires[key] = self.clock + ex

    def get(self, key: str) -> int | None:
        return self.values[key] if self._alive(key) else None

    def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.expires.pop(key, None)

    def ttl(self, key: str) -> int:
        if not self._alive(key):
            return -2
        if key not in self.expires:
            return -1
        return int(self.expires[key] - self.clock)


def test_a_throttle_pauses_only_that_shop_and_every_endpoint():
    redis = FakeRedis()
    limiter = RateLimiter(redis, jitter=lambda: 0.0)
    assert limiter.acquire(APP, SHOP_A, ENDPOINT, 10, 60)

    delay = limiter.note_throttled(APP, SHOP_A)

    assert delay == BACKOFF_BASE_SECONDS
    assert not limiter.acquire(APP, SHOP_A, ENDPOINT, 10, 60)
    assert not limiter.acquire(APP, SHOP_A, "/order/202309/orders/search", 10, 60)
    assert limiter.time_until_reset(APP, SHOP_A, ENDPOINT) >= BACKOFF_BASE_SECONDS
    assert limiter.acquire(APP, SHOP_B, ENDPOINT, 10, 60)


def test_the_pause_ends_by_itself_and_a_blocked_acquire_does_not_burn_a_token():
    redis = FakeRedis()
    limiter = RateLimiter(redis, jitter=lambda: 0.0)
    limiter.note_throttled(APP, SHOP_A)
    for _ in range(5):
        assert not limiter.acquire(APP, SHOP_A, ENDPOINT, 1, 60)
    assert redis.get(f"ratelimit:{APP}:{SHOP_A}:{ENDPOINT}") is None

    redis.clock += BACKOFF_BASE_SECONDS + 1

    assert limiter.backoff_remaining(APP, SHOP_A) == 0
    assert limiter.acquire(APP, SHOP_A, ENDPOINT, 1, 60)


def test_back_to_back_throttles_double_the_pause_up_to_the_cap():
    limiter = RateLimiter(FakeRedis(), jitter=lambda: 0.0)
    delays = [limiter.note_throttled(APP, SHOP_A) for _ in range(8)]
    assert delays[:3] == [30, 60, 120]
    assert delays[-1] == BACKOFF_MAX_SECONDS
    assert delays == sorted(delays)


def test_jitter_spreads_the_wake_up_by_at_most_a_quarter():
    low = RateLimiter(FakeRedis(), jitter=lambda: 0.0).note_throttled(APP, SHOP_A)
    high = RateLimiter(FakeRedis(), jitter=lambda: 0.999).note_throttled(APP, SHOP_A)
    assert low == 30 and 30 < high <= 38


def test_a_success_resets_the_doubling():
    limiter = RateLimiter(FakeRedis(), jitter=lambda: 0.0)
    limiter.note_throttled(APP, SHOP_A)
    limiter.note_throttled(APP, SHOP_A)
    limiter.note_success(APP, SHOP_A)
    assert limiter.note_throttled(APP, SHOP_A) == BACKOFF_BASE_SECONDS


def test_a_redis_failure_never_turns_a_throttle_into_an_error():
    class Broken:
        def incr(self, key):
            raise ConnectionError("redis down")

    assert RateLimiter(Broken()).note_throttled(APP, SHOP_A) == 0


class _ThrottlingAt(RateLimiter):
    """Acts like a caller that caught a 429 on the n-th call (mid-chunk)."""

    def __init__(self, redis, *, at: int) -> None:
        super().__init__(redis, jitter=lambda: 0.0)
        self.at = at
        self.calls = 0

    def acquire(self, app_id, shop_id, endpoint, max_requests, window_seconds):
        self.calls += 1
        if self.calls == self.at:
            self.note_throttled(app_id, shop_id)
        return super().acquire(app_id, shop_id, endpoint, max_requests, window_seconds)


@pytest.mark.asyncio
async def test_a_429_mid_walk_then_a_restart_continues_from_the_cursor(session):
    from juli_backend.workers.services.polling.ingestion import run_history_chunks
    from tests.support.shop_ingestion_fakes import FakeAnalyticsResource, make_resources
    from tests.unit.test_shop_ingestion import (
        CONFIG,
        LATEST,
        Handoffs,
        _count_score,
        _fast,
        _make_shop,
        _no_sleep,
    )
    from tests.unit.test_shop_ingestion import NOW as INGEST_NOW

    shop = await _make_shop(session, label="b3resume")
    analytics = FakeAnalyticsResource(prefix="b3resume", earliest_data=LATEST - timedelta(days=400))
    await _fast(session, shop, analytics, score_fn=_count_score)
    repo = ShopIngestionStateRepo(session)
    redis = FakeRedis()

    async def walk(limiter):
        return await run_history_chunks(
            session=session,
            config=CONFIG,
            shop_id=shop.id,
            rate_limiter=limiter,
            handoff_fn=Handoffs(session),
            create_resources=lambda _cfg: make_resources(analytics),
            sleep=_no_sleep,
            now=INGEST_NOW,
            chunk_days=30,
            stop_at_days=120,
            max_chunks=12,
        )

    before = history_days_available(await repo.find(shop.id))
    await walk(_ThrottlingAt(redis, at=3))
    state = await repo.find(shop.id)
    await session.refresh(state)
    stopped_at = history_days_available(state)
    cursor = state.history_earliest_date
    # The throttle stopped the walk inside the chunk: the cursor never moved
    # past what was completely stored.
    assert stopped_at < 120

    fetched = {name: list(calls) for name, calls in analytics.calls.items()}

    # Restart inside the pause: a new limiter object on the same Redis, no calls.
    await walk(RateLimiter(redis, jitter=lambda: 0.0))
    assert {name: list(calls) for name, calls in analytics.calls.items()} == fetched
    state = await repo.find(shop.id)
    await session.refresh(state)
    assert state.history_earliest_date == cursor

    # The pause ends; the walk continues from the cursor to the connect window.
    redis.clock += BACKOFF_BASE_SECONDS + 1
    await walk(RateLimiter(redis, jitter=lambda: 0.0))
    state = await repo.find(shop.id)
    await session.refresh(state)
    assert history_days_available(state) >= 120 > before
    assert state.history_earliest_date <= cursor
    shop_calls = analytics.calls.get("get_shop_performance", [])
    assert len(shop_calls) == len(set(map(repr, shop_calls))), (
        "a completed window was fetched twice"
    )
