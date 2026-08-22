"""Unit coverage for `services.agent.abuse_limits` -- ADR-075 decision 4, #1223.

The gate module itself, independent of any HTTP route: config env vars,
fixed-window + burst semantics, concurrency acquire/release, cross-tenant
isolation at the key level, and fail-closed behavior on both an unbound gate
and a live Redis error. Route-level wiring (429 + Retry-After, the security
event, the cancel-survives-the-storm proof, and SSE disconnect release) is
`tests/unit/test_agent_abuse_limits_routes.py`.
"""

from __future__ import annotations

import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.services.agent.abuse_limits import (
    ABUSE_LIMIT_EXCEEDED_EVENT,
    InMemoryAbuseLimitGate,
    RedisAbuseLimitGate,
    UnavailableAbuseLimitGate,
    approve_rate_limit_burst_max_requests,
    approve_rate_limit_max_requests,
    approve_rate_limit_window_seconds,
    bind_agent_abuse_limit_gate,
    confirmation_rate_limit_max_requests,
    confirmation_rate_limit_window_seconds,
    get_agent_abuse_limit_gate,
    log_abuse_limit_exceeded,
    set_agent_abuse_limit_gate,
    sse_max_concurrent_streams,
)

# ---------------------------------------------------------------------------
# Config -- env-var driven, named defaults
# ---------------------------------------------------------------------------


def test_approve_rate_limit_defaults_match_adr_075_decision_4(monkeypatch):
    monkeypatch.delenv("AGENT_APPROVE_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("AGENT_APPROVE_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_APPROVE_RATE_LIMIT_BURST_MAX_REQUESTS", raising=False)
    assert approve_rate_limit_max_requests() == 5
    assert approve_rate_limit_window_seconds() == 3600
    assert approve_rate_limit_burst_max_requests() == 2


def test_confirmation_rate_limit_defaults_match_adr_075_decision_4(monkeypatch):
    monkeypatch.delenv("AGENT_CONFIRMATION_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("AGENT_CONFIRMATION_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    assert confirmation_rate_limit_max_requests() == 30
    assert confirmation_rate_limit_window_seconds() == 3600


def test_sse_max_concurrent_streams_default_matches_adr_075_decision_4(monkeypatch):
    monkeypatch.delenv("AGENT_SSE_MAX_CONCURRENT_STREAMS", raising=False)
    assert sse_max_concurrent_streams() == 10


def test_approve_rate_limit_max_requests_reads_env_var(monkeypatch):
    monkeypatch.setenv("AGENT_APPROVE_RATE_LIMIT_MAX_REQUESTS", "9")
    assert approve_rate_limit_max_requests() == 9


def test_approve_rate_limit_max_requests_ignores_garbage_value(monkeypatch):
    monkeypatch.setenv("AGENT_APPROVE_RATE_LIMIT_MAX_REQUESTS", "not-a-number")
    assert approve_rate_limit_max_requests() == 5


def test_approve_rate_limit_max_requests_ignores_non_positive_value(monkeypatch):
    monkeypatch.setenv("AGENT_APPROVE_RATE_LIMIT_MAX_REQUESTS", "0")
    assert approve_rate_limit_max_requests() == 5


# ---------------------------------------------------------------------------
# InMemoryAbuseLimitGate -- fixed window + burst semantics
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.mark.asyncio
async def test_approve_allows_up_to_burst_then_denies():
    gate = InMemoryAbuseLimitGate(
        approve_burst_max_requests=2, approve_burst_window_seconds=3600, approve_max_requests=100
    )
    first = await gate.try_acquire_approve("shop-a")
    second = await gate.try_acquire_approve("shop-a")
    third = await gate.try_acquire_approve("shop-a")

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_approve_sustained_window_denies_after_five_even_outside_burst_window():
    clock = _FakeClock()
    gate = InMemoryAbuseLimitGate(
        approve_max_requests=5,
        approve_window_seconds=3600,
        approve_burst_max_requests=100,
        approve_burst_window_seconds=1,
        clock=clock,
    )
    decisions = []
    for _ in range(6):
        decisions.append(await gate.try_acquire_approve("shop-a"))
        clock.advance(2)  # step past the 1s burst window each time

    assert [d.allowed for d in decisions] == [True, True, True, True, True, False]


@pytest.mark.asyncio
async def test_approve_resets_after_sustained_window_elapses():
    clock = _FakeClock()
    gate = InMemoryAbuseLimitGate(
        approve_max_requests=1,
        approve_window_seconds=60,
        approve_burst_max_requests=100,
        approve_burst_window_seconds=1,
        clock=clock,
    )
    first = await gate.try_acquire_approve("shop-a")
    clock.advance(0.5)
    denied = await gate.try_acquire_approve("shop-a")
    clock.advance(61)
    allowed_again = await gate.try_acquire_approve("shop-a")

    assert first.allowed is True
    assert denied.allowed is False
    assert allowed_again.allowed is True


@pytest.mark.asyncio
async def test_confirmation_allows_up_to_max_then_denies():
    gate = InMemoryAbuseLimitGate(confirmation_max_requests=2, confirmation_window_seconds=3600)
    results = [await gate.try_acquire_confirmation("shop-a") for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]


# ---------------------------------------------------------------------------
# Cross-tenant isolation -- one shop's bucket never affects another's
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_cross_tenant_isolation():
    gate = InMemoryAbuseLimitGate(approve_burst_max_requests=1, approve_burst_window_seconds=3600)
    shop_a_first = await gate.try_acquire_approve("shop-a")
    shop_a_second = await gate.try_acquire_approve("shop-a")  # exhausted
    shop_b_first = await gate.try_acquire_approve("shop-b")  # untouched by shop-a

    assert shop_a_first.allowed is True
    assert shop_a_second.allowed is False
    assert shop_b_first.allowed is True


@pytest.mark.asyncio
async def test_confirmation_cross_tenant_isolation():
    gate = InMemoryAbuseLimitGate(confirmation_max_requests=1)
    await gate.try_acquire_confirmation("shop-a")
    shop_a_denied = await gate.try_acquire_confirmation("shop-a")
    shop_b_allowed = await gate.try_acquire_confirmation("shop-b")

    assert shop_a_denied.allowed is False
    assert shop_b_allowed.allowed is True


@pytest.mark.asyncio
async def test_sse_cross_tenant_isolation():
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    shop_a = await gate.try_acquire_stream("shop-a")
    shop_a_denied = await gate.try_acquire_stream("shop-a")
    shop_b = await gate.try_acquire_stream("shop-b")

    assert shop_a.allowed is True
    assert shop_a_denied.allowed is False
    assert shop_b.allowed is True


# ---------------------------------------------------------------------------
# SSE concurrency -- acquire/release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_acquire_release_frees_a_slot():
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    first = await gate.try_acquire_stream("shop-a")
    denied = await gate.try_acquire_stream("shop-a")
    await gate.release_stream("shop-a")
    allowed_again = await gate.try_acquire_stream("shop-a")

    assert first.allowed is True
    assert denied.allowed is False
    assert allowed_again.allowed is True


@pytest.mark.asyncio
async def test_sse_release_below_zero_stays_floored_at_zero():
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    await gate.release_stream("shop-a")  # release with nothing acquired
    await gate.release_stream("shop-a")  # a double-release
    first = await gate.try_acquire_stream("shop-a")
    second = await gate.try_acquire_stream("shop-a")

    assert first.allowed is True
    assert second.allowed is False  # never manufactured extra capacity


# ---------------------------------------------------------------------------
# Fail-closed: unbound gate, unconfigured backend, live Redis error
# ---------------------------------------------------------------------------


def test_get_agent_abuse_limit_gate_raises_when_unbound():
    set_agent_abuse_limit_gate(None)
    with pytest.raises(RuntimeError, match="abuse-limit gate"):
        get_agent_abuse_limit_gate()


@pytest.mark.asyncio
async def test_unavailable_gate_denies_every_rate_limited_operation():
    gate = UnavailableAbuseLimitGate()

    approve_decision = await gate.try_acquire_approve("shop-a")
    confirmation_decision = await gate.try_acquire_confirmation("shop-a")
    sse_decision = await gate.try_acquire_stream("shop-a")

    assert approve_decision.allowed is False
    assert confirmation_decision.allowed is False
    assert sse_decision.allowed is False
    assert approve_decision.retry_after_seconds > 0
    assert confirmation_decision.retry_after_seconds > 0
    assert sse_decision.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_unavailable_gate_release_stream_is_a_harmless_noop():
    gate = UnavailableAbuseLimitGate()
    await gate.release_stream("shop-a")  # must not raise


def test_bind_with_no_redis_url_yields_unavailable_gate():
    bind_agent_abuse_limit_gate(redis_url="")
    gate = get_agent_abuse_limit_gate()
    assert isinstance(gate, UnavailableAbuseLimitGate)


def test_bind_with_redis_url_yields_redis_backed_gate():
    from juli_backend.services.analytics_kpi_cache import reset_shared_redis_client_for_tests

    reset_shared_redis_client_for_tests()
    try:
        bind_agent_abuse_limit_gate(redis_url="redis://127.0.0.1:6379/0")
        gate = get_agent_abuse_limit_gate()
        assert isinstance(gate, RedisAbuseLimitGate)
    finally:
        reset_shared_redis_client_for_tests()


def test_bind_reuses_the_analytics_kpi_cache_shared_client():
    """#927: one shared async client, not a second bespoke connection."""
    from juli_backend.services.analytics_kpi_cache import (
        get_shared_redis_client,
        reset_shared_redis_client_for_tests,
    )

    reset_shared_redis_client_for_tests()
    try:
        bind_agent_abuse_limit_gate(redis_url="redis://127.0.0.1:6379/0")
        gate = get_agent_abuse_limit_gate()
        assert isinstance(gate, RedisAbuseLimitGate)
        assert gate._redis is get_shared_redis_client("redis://127.0.0.1:6379/0")
    finally:
        reset_shared_redis_client_for_tests()


@pytest.mark.asyncio
async def test_redis_gate_approve_denies_on_redis_error_and_reports_window_as_retry_hint():
    from unittest.mock import AsyncMock

    broken_redis = AsyncMock()
    broken_redis.incr.side_effect = RedisConnectionError("boom")
    gate = RedisAbuseLimitGate(broken_redis)

    decision = await gate.try_acquire_approve("shop-a")

    assert decision.allowed is False
    assert decision.retry_after_seconds == 3600


@pytest.mark.asyncio
async def test_redis_gate_approve_allows_first_two_then_denies_burst():
    from unittest.mock import AsyncMock

    store: dict[str, int] = {}

    async def _incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    async def _expire(key, seconds):
        return True

    async def _ttl(key):
        return 10

    redis_client = AsyncMock()
    redis_client.incr.side_effect = _incr
    redis_client.expire.side_effect = _expire
    redis_client.ttl.side_effect = _ttl
    gate = RedisAbuseLimitGate(redis_client)

    first = await gate.try_acquire_approve("shop-a")
    second = await gate.try_acquire_approve("shop-a")
    third = await gate.try_acquire_approve("shop-a")

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False  # burst window (default max 2) exhausted


@pytest.mark.asyncio
async def test_redis_gate_sse_acquire_denies_over_max_and_decrements_back():
    from unittest.mock import AsyncMock

    store = {"juli:agent:abuse_limit:sse_concurrency:shop-a": 0}

    async def _incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    async def _decr(key):
        store[key] = store.get(key, 0) - 1
        return store[key]

    async def _expire(key, seconds):
        return True

    redis_client = AsyncMock()
    redis_client.incr.side_effect = _incr
    redis_client.decr.side_effect = _decr
    redis_client.expire.side_effect = _expire
    gate = RedisAbuseLimitGate(redis_client)

    import juli_backend.services.agent.abuse_limits as abuse_limits_module

    class _One:
        def __call__(self):
            return 1

    orig = abuse_limits_module.sse_max_concurrent_streams
    abuse_limits_module.sse_max_concurrent_streams = _One()
    try:
        first = await gate.try_acquire_stream("shop-a")
        second = await gate.try_acquire_stream("shop-a")
    finally:
        abuse_limits_module.sse_max_concurrent_streams = orig

    assert first.allowed is True
    assert second.allowed is False
    # the denied call must have decremented back -- the counter should read
    # 1 (only the successful acquire), not 2.
    assert store["juli:agent:abuse_limit:sse_concurrency:shop-a"] == 1


@pytest.mark.asyncio
async def test_redis_gate_sse_release_decrements():
    from unittest.mock import AsyncMock

    store = {"juli:agent:abuse_limit:sse_concurrency:shop-a": 1}

    async def _decr(key):
        store[key] = store.get(key, 0) - 1
        return store[key]

    redis_client = AsyncMock()
    redis_client.decr.side_effect = _decr
    gate = RedisAbuseLimitGate(redis_client)

    await gate.release_stream("shop-a")

    assert store["juli:agent:abuse_limit:sse_concurrency:shop-a"] == 0


@pytest.mark.asyncio
async def test_redis_gate_sse_release_floors_at_zero_on_double_release():
    from unittest.mock import AsyncMock

    store = {"juli:agent:abuse_limit:sse_concurrency:shop-a": 0}

    async def _decr(key):
        store[key] = store.get(key, 0) - 1
        return store[key]

    async def _set(key, value):
        store[key] = value
        return True

    redis_client = AsyncMock()
    redis_client.decr.side_effect = _decr
    redis_client.set.side_effect = _set
    gate = RedisAbuseLimitGate(redis_client)

    await gate.release_stream("shop-a")  # double release: goes to -1, floored back to 0

    assert store["juli:agent:abuse_limit:sse_concurrency:shop-a"] == 0


# ---------------------------------------------------------------------------
# Security event logging convention (#905)
# ---------------------------------------------------------------------------


def test_log_abuse_limit_exceeded_emits_structured_warning(caplog):
    route_logger = logging.getLogger("juli_backend.api.routes.some_test_route")
    with caplog.at_level(logging.WARNING, logger=route_logger.name):
        log_abuse_limit_exceeded(
            route_logger, shop_id="shop-a", operation="approve", retry_after_seconds=42
        )

    record = next(r for r in caplog.records if r.message == ABUSE_LIMIT_EXCEEDED_EVENT)
    assert getattr(record, "shop_id", None) == "shop-a"
    assert getattr(record, "operation", None) == "approve"
    assert getattr(record, "retry_after_seconds", None) == 42
