"""P2.10-A5 (#529) — Redis read-through cache for Analytics KPI envelopes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo


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
    user = User(id=user_id, phone="+849305000529")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="KPI Cache Shop 529",
        tiktok_shop_id="tiktok_shop_529",
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
                "series": [{"t": "2026-07-01", "v": 1000.0}],
            }
        },
        "meta": {"source_partitions": ["A-36"], "notes": []},
    }


@pytest.mark.asyncio
async def test_get_hits_redis_when_populated(session, shop) -> None:
    from juli_backend.services.analytics_kpi_cache import (
        envelope_cache_key,
        get_analytics_kpi_envelope,
    )

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    redis = FakeAsyncRedis()
    await redis.set(envelope_cache_key(shop.id), json.dumps(payload))

    envelope = await get_analytics_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload
    assert envelope.shop_id == shop.id
    assert envelope.kind == "analytics"

    repo = AnalyticsKpiEnvelopesRepo(session)
    assert await repo.get_by_kind(shop.id, "analytics") is None


@pytest.mark.asyncio
async def test_get_miss_loads_postgres_and_fills_cache(session, shop) -> None:
    from juli_backend.services.analytics_kpi_cache import (
        envelope_cache_key,
        get_analytics_kpi_envelope,
    )

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    await AnalyticsKpiEnvelopesRepo(session).upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    redis = FakeAsyncRedis()
    envelope = await get_analytics_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload
    cached = await redis.get(envelope_cache_key(shop.id))
    assert cached is not None
    assert json.loads(cached) == payload


@pytest.mark.asyncio
async def test_precompute_upsert_refreshes_redis(session, shop) -> None:
    from juli_backend.services.analytics_kpi_cache import envelope_cache_key
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    redis = FakeAsyncRedis()
    envelope = await precompute_shop_analytics_kpis(
        session,
        shop.id,
        computed_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        redis_client=redis,
    )
    await session.flush()

    cached = await redis.get(envelope_cache_key(shop.id))
    assert cached is not None
    assert json.loads(cached) == envelope.payload

    fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload == envelope.payload


@pytest.mark.asyncio
async def test_get_redis_outage_still_returns_postgres_rows(session, shop) -> None:
    from juli_backend.services.analytics_kpi_cache import get_analytics_kpi_envelope

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _sample_payload(shop_id=shop.id, computed_at=computed_at)
    await AnalyticsKpiEnvelopesRepo(session).upsert(
        shop_id=shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    redis = FakeAsyncRedis()
    redis.get_raises = RedisConnectionError("redis unavailable")

    envelope = await get_analytics_kpi_envelope(session, shop.id, redis_client=redis)

    assert envelope is not None
    assert envelope.payload == payload


def test_shared_redis_client_reuses_same_instance(monkeypatch) -> None:
    from juli_backend.services.analytics_kpi_cache import (
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
    from juli_backend.services.analytics_kpi_cache import (
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
    from juli_backend.services.analytics_kpi_cache import (
        get_shared_redis_client,
        reset_shared_redis_client_for_tests,
    )

    reset_shared_redis_client_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert get_shared_redis_client() is None
