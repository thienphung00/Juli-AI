"""Per-shop cooldown on POST /v1/action-cards/refresh — Issue #899, ADR-061 §2b.

The manual refresh endpoint enqueues a real TikTok poll + full scoring pipeline
Celery job on every call. It is authenticated and shop-scoped, so Nginx (which
throttles by network origin — issue #898) cannot express a useful limit here.
This is the one application-level rate limit in the epic, keyed on shop
identity.

Exit gate (agent-runtime/artifacts/release-evidence-plan-issue-899.json):
AC1 → two rapid calls for one shop produce one enqueue and one rejection
AC2 → two rapid calls for two different shops produce two enqueues
AC3 → the call succeeds again after the cooldown window elapses
AC4 → an unavailable backing store does not degrade into unlimited enqueuing
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.models.models import Shop, User
from juli_backend.services.action_cards.refresh_cooldown import (
    InMemoryRefreshCooldownGate,
    RedisRefreshCooldownGate,
    UnavailableRefreshCooldownGate,
    bind_action_card_refresh_cooldown_gate,
    get_refresh_cooldown_gate,
    refresh_cooldown_seconds,
    set_refresh_cooldown_gate,
)


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(session, user_id):
    u = User(id=user_id, phone="+849305008990")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop_a(session, user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Cooldown Shop A",
        tiktok_shop_id="tiktok_shop_899a",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def shop_b(session, user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Cooldown Shop B",
        tiktok_shop_id="tiktok_shop_899b",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def client(app, user):
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _act_as(app, shop: Shop) -> None:
    from juli_backend.api.dependencies import get_active_shop

    app.dependency_overrides[get_active_shop] = lambda: shop


@pytest.fixture
def mock_refresh_dispatcher(monkeypatch):
    dispatcher = MagicMock()
    dispatcher.enqueue.return_value = "celery-task-id-899"
    monkeypatch.setattr(
        "juli_backend.services.action_cards.dispatch.get_refresh_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


@pytest.fixture(autouse=True)
def reset_cooldown_gate():
    yield
    set_refresh_cooldown_gate(None)


class _FakeClock:
    """Deterministic, manually-advanced clock for the InMemory gate."""

    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# --- AC1: two rapid calls, one shop -> one enqueue, one rejection -----------


@pytest.mark.asyncio
async def test_second_refresh_within_cooldown_is_rejected_without_enqueuing(
    app, client, shop_a, mock_refresh_dispatcher
):
    set_refresh_cooldown_gate(InMemoryRefreshCooldownGate(cooldown_seconds=60))
    _act_as(app, shop_a)

    first = await client.post("/v1/action-cards/refresh")
    second = await client.post("/v1/action-cards/refresh")

    assert first.status_code == 202
    assert second.status_code == 429
    assert mock_refresh_dispatcher.enqueue.call_count == 1

    # AC: rejection is distinguishable and hints at retry timing.
    body = second.json()
    assert "retry" in body["detail"].lower() or "cooldown" in body["detail"].lower()
    assert "Retry-After" in second.headers
    assert int(second.headers["Retry-After"]) > 0


# --- AC2: two shops -> two enqueues, unaffected by each other ---------------


@pytest.mark.asyncio
async def test_different_shops_are_not_throttled_by_each_others_cooldown(
    app, client, shop_a, shop_b, mock_refresh_dispatcher
):
    set_refresh_cooldown_gate(InMemoryRefreshCooldownGate(cooldown_seconds=60))

    _act_as(app, shop_a)
    resp_a = await client.post("/v1/action-cards/refresh")

    _act_as(app, shop_b)
    resp_b = await client.post("/v1/action-cards/refresh")

    assert resp_a.status_code == 202
    assert resp_b.status_code == 202
    assert mock_refresh_dispatcher.enqueue.call_count == 2
    mock_refresh_dispatcher.enqueue.assert_any_call(str(shop_a.id))
    mock_refresh_dispatcher.enqueue.assert_any_call(str(shop_b.id))


# --- AC3: accepted again once the window elapses ----------------------------


@pytest.mark.asyncio
async def test_refresh_accepted_again_after_cooldown_window_elapses(
    app, client, shop_a, mock_refresh_dispatcher
):
    clock = _FakeClock()
    set_refresh_cooldown_gate(InMemoryRefreshCooldownGate(cooldown_seconds=30, clock=clock))
    _act_as(app, shop_a)

    first = await client.post("/v1/action-cards/refresh")
    throttled = await client.post("/v1/action-cards/refresh")

    clock.advance(31)
    third = await client.post("/v1/action-cards/refresh")

    assert first.status_code == 202
    assert throttled.status_code == 429
    assert third.status_code == 202
    assert mock_refresh_dispatcher.enqueue.call_count == 2


# --- AC4: unavailable backing store fails closed, never unlimited ----------


@pytest.mark.asyncio
async def test_unconfigured_backing_store_fails_closed(
    app, client, shop_a, mock_refresh_dispatcher
):
    """No REDIS_URL bound => every request denied, not unlimited (ADR-061 §2b)."""
    set_refresh_cooldown_gate(UnavailableRefreshCooldownGate())
    _act_as(app, shop_a)

    first = await client.post("/v1/action-cards/refresh")
    second = await client.post("/v1/action-cards/refresh")

    assert first.status_code == 429
    assert second.status_code == 429
    assert mock_refresh_dispatcher.enqueue.call_count == 0


@pytest.mark.asyncio
async def test_redis_store_unreachable_fails_closed_not_unlimited(
    app, client, shop_a, mock_refresh_dispatcher
):
    """A live but failing Redis client denies rather than silently allowing."""
    broken_redis = AsyncMock()
    broken_redis.set.side_effect = RedisConnectionError("connection refused")
    set_refresh_cooldown_gate(RedisRefreshCooldownGate(broken_redis, cooldown_seconds=60))
    _act_as(app, shop_a)

    responses = [await client.post("/v1/action-cards/refresh") for _ in range(3)]

    assert all(r.status_code == 429 for r in responses)
    assert mock_refresh_dispatcher.enqueue.call_count == 0


@pytest.mark.asyncio
async def test_unbound_cooldown_gate_does_not_enqueue(app, client, shop_a, mock_refresh_dispatcher):
    """No gate bound at all (startup wiring skipped) must not enqueue either.

    Unbound is a startup-wiring bug, not a runtime store outage — it is
    correct for it to surface as a hard failure rather than a 4xx, but the
    important invariant is the same as the other fail-closed tests: the
    refresh must never reach the dispatcher.
    """
    set_refresh_cooldown_gate(None)
    _act_as(app, shop_a)

    with pytest.raises(RuntimeError, match="cooldown gate"):
        await client.post("/v1/action-cards/refresh")

    assert mock_refresh_dispatcher.enqueue.call_count == 0


# --- Exit gate (#927): a SLOW backing store must not stall the event loop --
#
# The #899 tests above only ever simulate failure with a mock that raises
# instantly (`side_effect=RedisConnectionError(...)`), which proves the
# fail-closed path but can never reveal a *stall* — the failure mode that
# matters when the production gate uses a synchronous Redis client with no
# `await`/`asyncio.to_thread` on an async route, on a single-worker uvicorn
# process (infra/systemd/juli-api.service `--workers 1`). This test stands
# up a real TCP listener that accepts the connection and holds it open —
# never replying — so the "Redis" call is genuinely slow, not instantly
# erroring, and drives the gate through the *real* startup binding path
# (`bind_action_card_refresh_cooldown_gate()`), not an injected fake gate.


@contextmanager
def _slow_backing_store(hold_seconds: float):
    """A raw TCP listener standing in for a hung Redis (#927 exit gate).

    Accepts exactly one connection and holds it open — sending nothing back —
    for ``hold_seconds`` real wall-clock seconds on a dedicated OS thread
    (independent of whatever asyncio loop the caller is on, including one
    that is itself blocked), then closes the socket so the client's blocked
    read finally unblocks with a connection-closed error.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def _accept_and_hold() -> None:
        server.settimeout(hold_seconds + 10)
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            time.sleep(hold_seconds)
        finally:
            conn.close()

    thread = threading.Thread(target=_accept_and_hold, daemon=True)
    thread.start()
    try:
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        server.close()
        thread.join(timeout=hold_seconds + 10)


@pytest.mark.asyncio
async def test_slow_backing_store_does_not_stall_the_event_loop(
    app, client, shop_a, mock_refresh_dispatcher, monkeypatch
):
    """A hung Redis must not block the sole uvicorn worker's event loop.

    Exit gate (release-evidence-plan-issue-927.json,
    "slow-redis-does-not-stall-the-worker"): while a refresh call is stuck
    waiting on a slow backing store, a concurrent request to an unrelated
    endpoint (``/health``) must still complete quickly.
    """
    hold_seconds = 1.0

    # api/main.py mounts /health outside create_app(); this test exercises
    # create_app() directly (like every other test in this module), so a
    # trivial unrelated route stands in for it here.
    app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"])

    with _slow_backing_store(hold_seconds) as redis_url:
        monkeypatch.setenv("REDIS_URL", redis_url)
        bind_action_card_refresh_cooldown_gate()  # real startup binding, not a fake
        _act_as(app, shop_a)

        # Timer wraps kickoff-through-response so a stall anywhere in between
        # is captured, not just the health coroutine's own latency.
        started = time.monotonic()
        refresh_task = asyncio.ensure_future(client.post("/v1/action-cards/refresh"))
        # In-process ASGI test calls resolve without ever truly suspending
        # back to the loop's scheduler unless something forces a handoff —
        # without this, /health can run to completion having never given the
        # refresh task a turn at all, which would prove nothing. One bare
        # yield hands control to whichever coroutine was scheduled first
        # (the refresh task), so if it blocks the thread synchronously, that
        # blocking is what the health request below runs into.
        await asyncio.sleep(0)
        health_response = await asyncio.wait_for(client.get("/health"), timeout=hold_seconds * 0.6)
        elapsed = time.monotonic() - started

        assert health_response.status_code == 200
        assert elapsed < hold_seconds * 0.5, (
            f"/health took {elapsed:.3f}s while a slow backing-store call was "
            "in flight for an unrelated shop — the sole worker's event loop "
            "was stalled"
        )

        # Let the stalled refresh call resolve (it must fail closed, never
        # enqueue) before the fixture tears the socket down.
        refresh_response = await asyncio.wait_for(refresh_task, timeout=hold_seconds + 10)
        assert refresh_response.status_code == 429
        assert mock_refresh_dispatcher.enqueue.call_count == 0


# --- Unit coverage on the gate module itself --------------------------------


def test_refresh_cooldown_seconds_reads_env_var(monkeypatch):
    monkeypatch.setenv("ACTION_CARD_REFRESH_COOLDOWN_SECONDS", "120")
    assert refresh_cooldown_seconds() == 120


def test_refresh_cooldown_seconds_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("ACTION_CARD_REFRESH_COOLDOWN_SECONDS", raising=False)
    assert refresh_cooldown_seconds() > 0


def test_refresh_cooldown_seconds_ignores_garbage_value(monkeypatch):
    monkeypatch.setenv("ACTION_CARD_REFRESH_COOLDOWN_SECONDS", "not-a-number")
    assert refresh_cooldown_seconds() > 0


@pytest.mark.asyncio
async def test_bind_with_no_redis_url_yields_unavailable_gate():
    bind_action_card_refresh_cooldown_gate(redis_url="")
    gate = get_refresh_cooldown_gate()
    assert isinstance(gate, UnavailableRefreshCooldownGate)
    decision = await gate.try_acquire("shop-899")
    assert decision.allowed is False


def test_bind_with_redis_url_yields_redis_backed_gate():
    from juli_backend.services.analytics_kpi_cache import reset_shared_redis_client_for_tests

    reset_shared_redis_client_for_tests()
    try:
        bind_action_card_refresh_cooldown_gate(redis_url="redis://127.0.0.1:6379/0")
        gate = get_refresh_cooldown_gate()
        assert isinstance(gate, RedisRefreshCooldownGate)
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
        bind_action_card_refresh_cooldown_gate(redis_url="redis://127.0.0.1:6379/0")
        gate = get_refresh_cooldown_gate()
        assert isinstance(gate, RedisRefreshCooldownGate)
        assert gate._redis is get_shared_redis_client("redis://127.0.0.1:6379/0")
    finally:
        reset_shared_redis_client_for_tests()


def test_get_refresh_cooldown_gate_raises_when_unbound():
    set_refresh_cooldown_gate(None)
    with pytest.raises(RuntimeError, match="cooldown gate"):
        get_refresh_cooldown_gate()


@pytest.mark.asyncio
async def test_redis_gate_denies_on_redis_error_and_reports_window_as_retry_hint():
    broken_redis = AsyncMock()
    broken_redis.set.side_effect = RedisConnectionError("boom")
    gate = RedisRefreshCooldownGate(broken_redis, cooldown_seconds=45)

    decision = await gate.try_acquire("shop-899")

    assert decision.allowed is False
    assert decision.retry_after_seconds == 45


@pytest.mark.asyncio
async def test_redis_gate_allows_first_call_then_denies_second():
    store: dict[str, str] = {}

    async def _set(key, value, nx=False, ex=None):
        if nx and key in store:
            return False
        store[key] = value
        return True

    redis_client = AsyncMock()
    redis_client.set.side_effect = _set
    redis_client.ttl.return_value = 60
    gate = RedisRefreshCooldownGate(redis_client, cooldown_seconds=60)

    first = await gate.try_acquire("shop-899")
    second = await gate.try_acquire("shop-899")

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds == 60
