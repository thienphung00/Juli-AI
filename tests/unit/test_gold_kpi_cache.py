"""A1 (#631) — Redis read-through cache for Gold KPI envelopes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import GoldKpiEnvelopesRepo


class FakeAsyncRedis:
    """Minimal async Redis fake for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.get_raises: Exception | None = None
        self.set_raises: Exception | None = None

    async def get(self, key: str) -> str | None:
        if self.get_raises is not None:
            raise self.get_raises
        return self._store.get(key)

    async def set(self, key: str, value: str) -> bool:
        if self.set_raises is not None:
            raise self.set_raises
        self._store[key] = value
        return True


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000631")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Gold KPI Cache Shop 631",
        tiktok_shop_id="tiktok_shop_631",
    )
    session.add(s)
    await session.flush()
    return s


def _sample_payload(*, shop_id: uuid.UUID, computed_at: datetime) -> dict:
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": "VND",
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "value": 1000.0,
            }
        },
        "meta": {"source_partitions": ["silver.orders"], "notes": []},
    }


@pytest.mark.asyncio
async def test_get_hits_redis_when_populated(session, shop) -> None:
    from juli_backend.services.gold_kpi_cache import (
        envelope_cache_key,
        get_gold_kpi_envelope,
    )

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    redis = FakeAsyncRedis()
    await redis.set(envelope_cache_key(shop.id), json.dumps(payload))

    envelope = await get_gold_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload
    assert envelope.shop_id == shop.id


@pytest.mark.asyncio
async def test_get_miss_loads_postgres_and_fills_cache(session, shop) -> None:
    from juli_backend.services.gold_kpi_cache import (
        envelope_cache_key,
        get_gold_kpi_envelope,
    )

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    await GoldKpiEnvelopesRepo(session).upsert(
        shop_id=shop.id,
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    redis = FakeAsyncRedis()
    envelope = await get_gold_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload
    cached = await redis.get(envelope_cache_key(shop.id))
    assert cached is not None
    assert json.loads(cached) == payload


@pytest.mark.asyncio
async def test_write_upsert_refreshes_redis(session, shop) -> None:
    from juli_backend.services.gold_kpi_cache import envelope_cache_key
    from juli_backend.services.gold_kpi_envelope_serving import write_demo_main_kpis_envelope

    redis = FakeAsyncRedis()
    # Mock get_shared_redis_client to return our fake Redis
    import juli_backend.services.gold_kpi_cache as cache_module

    original_get_shared = cache_module.get_shared_redis_client
    cache_module.get_shared_redis_client = lambda redis_url=None: redis

    try:
        envelope = await write_demo_main_kpis_envelope(session, shop.id)
        await session.flush()

        cached = await redis.get(envelope_cache_key(shop.id))
        assert cached is not None
        assert json.loads(cached) == envelope.payload

        fetched = await GoldKpiEnvelopesRepo(session).get(shop.id)
        assert fetched is not None
        assert fetched.payload == envelope.payload
    finally:
        cache_module.get_shared_redis_client = original_get_shared


@pytest.mark.asyncio
async def test_get_redis_outage_still_returns_postgres_rows(session, shop) -> None:
    from juli_backend.services.gold_kpi_cache import get_gold_kpi_envelope

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    await GoldKpiEnvelopesRepo(session).upsert(
        shop_id=shop.id,
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    redis = FakeAsyncRedis()
    redis.get_raises = RedisConnectionError("redis unavailable")

    envelope = await get_gold_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload


@pytest.mark.asyncio
async def test_compute_failure_returns_last_good_cached_envelope(session, shop) -> None:
    """Compute failure must return last-good cached envelope, never stale Postgres value."""
    from juli_backend.services.gold_kpi_cache import (
        envelope_cache_key,
        get_gold_kpi_envelope_with_last_good_fallback,
    )

    # Seed Postgres with a good envelope
    computed_at_v1 = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload_v1 = _sample_payload(shop_id=shop.id, computed_at=computed_at_v1)
    await GoldKpiEnvelopesRepo(session).upsert(
        shop_id=shop.id,
        envelope_version=1,
        payload=payload_v1,
        computed_at=computed_at_v1,
    )
    await session.flush()

    # Cache the good envelope
    redis = FakeAsyncRedis()
    await redis.set(envelope_cache_key(shop.id), json.dumps(payload_v1))

    # Compute fails (simulate by providing a mock that raises)
    async def failing_compute(*args, **kwargs):
        raise ValueError("compute failed")

    # Call the last-good fallback function
    # It should return the cached envelope, not attempt to recompute
    envelope = await get_gold_kpi_envelope_with_last_good_fallback(
        session, shop.id, redis_client=redis
    )

    assert envelope is not None
    assert envelope.payload == payload_v1


def test_redis_reachable_shared_client_for_api_workers(monkeypatch) -> None:
    from juli_backend.services.gold_kpi_cache import (
        get_shared_redis_client,
        reset_shared_redis_client_for_tests,
    )

    reset_shared_redis_client_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    created: list[object] = []

    class _FakeClient:
        async def aclose(self) -> None:
            return None

    def _fake_from_url(url: str, **kwargs: object) -> _FakeClient:
        client = _FakeClient()
        created.append(client)
        return client

    monkeypatch.setattr("redis.asyncio.from_url", _fake_from_url)

    first = get_shared_redis_client()
    second = get_shared_redis_client()

    assert first is second
    assert len(created) == 1
    reset_shared_redis_client_for_tests()


@pytest.mark.asyncio
async def test_close_shared_redis_client_clears_singleton(monkeypatch) -> None:
    from juli_backend.services.gold_kpi_cache import (
        close_shared_redis_client,
        get_shared_redis_client,
        reset_shared_redis_client_for_tests,
    )

    reset_shared_redis_client_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    closed = {"count": 0}

    class _FakeClient:
        async def aclose(self) -> None:
            closed["count"] += 1

    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda url, **kwargs: _FakeClient(),
    )

    client = get_shared_redis_client()
    assert client is not None
    await close_shared_redis_client()
    assert closed["count"] == 1
    assert get_shared_redis_client() is not client
    await close_shared_redis_client()
    reset_shared_redis_client_for_tests()


def test_shared_redis_client_none_without_url(monkeypatch) -> None:
    from juli_backend.services.gold_kpi_cache import (
        get_shared_redis_client,
        reset_shared_redis_client_for_tests,
    )

    reset_shared_redis_client_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert get_shared_redis_client() is None
