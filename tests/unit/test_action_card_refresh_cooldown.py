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

import uuid
from unittest.mock import MagicMock

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
    broken_redis = MagicMock()
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


def test_bind_with_no_redis_url_yields_unavailable_gate():
    bind_action_card_refresh_cooldown_gate(redis_url="")
    gate = get_refresh_cooldown_gate()
    assert isinstance(gate, UnavailableRefreshCooldownGate)
    decision = gate.try_acquire("shop-899")
    assert decision.allowed is False


def test_bind_with_redis_url_yields_redis_backed_gate():
    bind_action_card_refresh_cooldown_gate(redis_url="redis://127.0.0.1:6379/0")
    gate = get_refresh_cooldown_gate()
    assert isinstance(gate, RedisRefreshCooldownGate)


def test_get_refresh_cooldown_gate_raises_when_unbound():
    set_refresh_cooldown_gate(None)
    with pytest.raises(RuntimeError, match="cooldown gate"):
        get_refresh_cooldown_gate()


def test_redis_gate_denies_on_redis_error_and_reports_window_as_retry_hint():
    broken_redis = MagicMock()
    broken_redis.set.side_effect = RedisConnectionError("boom")
    gate = RedisRefreshCooldownGate(broken_redis, cooldown_seconds=45)

    decision = gate.try_acquire("shop-899")

    assert decision.allowed is False
    assert decision.retry_after_seconds == 45


def test_redis_gate_allows_first_call_then_denies_second():
    store: dict[str, str] = {}

    def _set(key, value, nx=False, ex=None):
        if nx and key in store:
            return False
        store[key] = value
        return True

    redis_client = MagicMock()
    redis_client.set.side_effect = _set
    redis_client.ttl.return_value = 60
    gate = RedisRefreshCooldownGate(redis_client, cooldown_seconds=60)

    first = gate.try_acquire("shop-899")
    second = gate.try_acquire("shop-899")

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds == 60
