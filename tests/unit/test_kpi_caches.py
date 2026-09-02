"""Both KPI envelope caches, through one parametrized contract (``services/kpi_cache``).

``gold_kpi_cache`` and ``analytics_kpi_cache`` are adapters over the same
read-through and the same shared Redis client, so each behaviour is proved once
against both. Gold's last-good fallback is the one behaviour it alone has.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.repositories import AnalyticsKpiEnvelopesRepo, GoldKpiEnvelopesRepo
from juli_backend.services import analytics_kpi_cache, gold_kpi_cache
from juli_backend.services.kpi_cache import redis_client
from tests.support.builders import make_tenant
from tests.support.fakes import FakeAsyncRedis

COMPUTED_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def sample_payload(shop_id: uuid.UUID) -> dict[str, Any]:
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": COMPUTED_AT.isoformat(),
        "currency": "VND",
        "kpis": {"gmv_tiktok": {"availability": "available", "label": "GMV", "value": 1000.0}},
        "meta": {"source_partitions": ["silver.orders"], "notes": []},
    }


@dataclass(frozen=True)
class CacheUnderTest:
    """One adapter: how to write its source-of-truth row, and its read/refresh functions."""

    name: str
    key_prefix: str
    get: Any
    refresh: Any
    key: Any

    async def write_source_row(self, session, shop_id, payload):
        raise NotImplementedError


class GoldUnderTest(CacheUnderTest):
    async def write_source_row(self, session, shop_id, payload):
        return await GoldKpiEnvelopesRepo(session).upsert(
            shop_id=shop_id, envelope_version=1, payload=payload, computed_at=COMPUTED_AT
        )


class AnalyticsUnderTest(CacheUnderTest):
    async def write_source_row(self, session, shop_id, payload):
        return await AnalyticsKpiEnvelopesRepo(session).upsert(
            shop_id=shop_id,
            kind="analytics",
            envelope_version=1,
            payload=payload,
            computed_at=COMPUTED_AT,
        )


CACHES = [
    pytest.param(
        GoldUnderTest(
            name="gold",
            key_prefix="gold:kpi_envelope:",
            get=gold_kpi_cache.get_gold_kpi_envelope,
            refresh=gold_kpi_cache.refresh_gold_kpi_envelope_cache,
            key=gold_kpi_cache.envelope_cache_key,
        ),
        id="gold",
    ),
    pytest.param(
        AnalyticsUnderTest(
            name="analytics",
            key_prefix="analytics:kpi_envelope:",
            get=analytics_kpi_cache.get_analytics_kpi_envelope,
            refresh=analytics_kpi_cache.refresh_analytics_kpi_envelope_cache,
            key=analytics_kpi_cache.envelope_cache_key,
        ),
        id="analytics",
    ),
]


@pytest.mark.parametrize("cache", CACHES)
class TestReadThrough:
    def test_key_is_prefix_plus_shop_id(self, cache, shop):
        assert cache.key(shop.id) == f"{cache.key_prefix}{shop.id}"

    async def test_hit_serves_from_redis_without_touching_postgres(self, cache, session, shop):
        redis = FakeAsyncRedis()
        payload = sample_payload(shop.id)
        await redis.set(cache.key(shop.id), json.dumps(payload))

        envelope = await cache.get(session, shop.id, redis_client=redis)

        assert envelope is not None
        assert envelope.payload == payload
        assert envelope.shop_id == shop.id
        assert envelope.computed_at == COMPUTED_AT

    async def test_miss_loads_postgres_and_fills_the_cache(self, cache, session, shop):
        payload = sample_payload(shop.id)
        await cache.write_source_row(session, shop.id, payload)
        redis = FakeAsyncRedis()

        envelope = await cache.get(session, shop.id, redis_client=redis)

        assert envelope is not None and envelope.payload == payload
        assert json.loads(redis.store[cache.key(shop.id)]) == payload

    async def test_miss_with_no_row_anywhere_is_none(self, cache, session, shop):
        assert await cache.get(session, shop.id, redis_client=FakeAsyncRedis()) is None

    async def test_redis_outage_on_read_still_returns_postgres_rows(self, cache, session, shop):
        payload = sample_payload(shop.id)
        await cache.write_source_row(session, shop.id, payload)
        redis = FakeAsyncRedis()
        redis.get_raises = RedisConnectionError("redis unavailable")

        envelope = await cache.get(session, shop.id, redis_client=redis)

        assert envelope is not None and envelope.payload == payload

    async def test_corrupt_cached_json_is_treated_as_a_miss(self, cache, session, shop):
        payload = sample_payload(shop.id)
        await cache.write_source_row(session, shop.id, payload)
        redis = FakeAsyncRedis()
        await redis.set(cache.key(shop.id), "{not json")

        envelope = await cache.get(session, shop.id, redis_client=redis)

        assert envelope is not None and envelope.payload == payload
        assert json.loads(redis.store[cache.key(shop.id)]) == payload  # repaired on the way back

    async def test_refresh_failure_is_swallowed(self, cache, session, shop):
        envelope = await cache.write_source_row(session, shop.id, sample_payload(shop.id))
        redis = FakeAsyncRedis()
        redis.set_raises = RedisConnectionError("redis unavailable")

        await cache.refresh(shop.id, envelope, redis_client=redis)  # must not raise

        assert redis.store == {}

    async def test_no_client_means_postgres_only(self, cache, session, shop):
        payload = sample_payload(shop.id)
        await cache.write_source_row(session, shop.id, payload)

        envelope = await cache.get(session, shop.id, redis_client=None)

        assert envelope is not None and envelope.payload == payload


class TestGoldLastGoodFallback:
    """Gold alone may serve the last payload this process cached when both stores are empty."""

    async def test_cached_payload_wins_and_is_remembered(self, session, shop):
        redis = FakeAsyncRedis()
        payload = sample_payload(shop.id)
        await redis.set(gold_kpi_cache.envelope_cache_key(shop.id), json.dumps(payload))

        envelope = await gold_kpi_cache.get_gold_kpi_envelope_with_last_good_fallback(
            session, shop.id, redis_client=redis
        )

        assert envelope is not None and envelope.payload == payload

    async def test_falls_back_to_last_good_when_redis_and_postgres_are_empty(self, session, shop):
        redis = FakeAsyncRedis()
        payload = sample_payload(shop.id)
        await redis.set(gold_kpi_cache.envelope_cache_key(shop.id), json.dumps(payload))
        await gold_kpi_cache.get_gold_kpi_envelope_with_last_good_fallback(
            session, shop.id, redis_client=redis
        )
        await redis.delete(gold_kpi_cache.envelope_cache_key(shop.id))

        envelope = await gold_kpi_cache.get_gold_kpi_envelope_with_last_good_fallback(
            session, shop.id, redis_client=redis
        )

        assert envelope is not None and envelope.payload == payload

    async def test_nothing_anywhere_is_none_not_a_fabricated_envelope(self, session):
        _, fresh_shop = await make_tenant(session)

        assert (
            await gold_kpi_cache.get_gold_kpi_envelope_with_last_good_fallback(
                session, fresh_shop.id, redis_client=FakeAsyncRedis()
            )
            is None
        )


class TestWriteRefreshesCache:
    async def test_gold_serving_write_refreshes_redis(self, session, shop, monkeypatch):
        from juli_backend.services.gold_kpi_envelope_serving import write_demo_main_kpis_envelope

        redis = FakeAsyncRedis()
        monkeypatch.setattr(gold_kpi_cache, "get_shared_redis_client", lambda redis_url=None: redis)

        envelope = await write_demo_main_kpis_envelope(session, shop.id)

        assert (
            json.loads(redis.store[gold_kpi_cache.envelope_cache_key(shop.id)]) == envelope.payload
        )
        fetched = await GoldKpiEnvelopesRepo(session).get(shop.id)
        assert fetched is not None and fetched.payload == envelope.payload

    async def test_analytics_precompute_refreshes_redis(self, session, shop):
        from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

        redis = FakeAsyncRedis()

        envelope = await precompute_shop_analytics_kpis(
            session, shop.id, computed_at=COMPUTED_AT, redis_client=redis
        )

        key = analytics_kpi_cache.envelope_cache_key(shop.id)
        assert json.loads(redis.store[key]) == envelope.payload
        fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
        assert fetched is not None and fetched.payload == envelope.payload


class TestSharedRedisClient:
    """One ``redis.asyncio`` client per ``(url, event loop)``; both adapters expose the same one."""

    @pytest.fixture(autouse=True)
    def _fresh_singleton(self):
        redis_client.reset_shared_redis_client_for_tests()
        yield
        redis_client.reset_shared_redis_client_for_tests()

    @pytest.fixture
    def created(self, monkeypatch):
        created: list[object] = []

        class _FakeClient:
            closed = 0

            async def aclose(self) -> None:
                type(self).closed += 1

        def _from_url(url: str, **kwargs: object) -> _FakeClient:
            created.append((url, kwargs, _FakeClient()))
            return created[-1][2]

        monkeypatch.setattr("redis.asyncio.from_url", _from_url)
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        return created

    def test_none_without_a_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert redis_client.get_shared_redis_client() is None
        assert gold_kpi_cache.get_shared_redis_client() is None

    def test_both_adapters_share_one_client(self, created):
        first = gold_kpi_cache.get_shared_redis_client()
        second = analytics_kpi_cache.get_shared_redis_client()

        assert first is second is created[0][2]
        assert len(created) == 1

    def test_client_is_created_with_socket_timeouts(self, created):
        """#927: without these an unreachable Redis blocks for the OS TCP timeout."""
        redis_client.get_shared_redis_client()

        _, kwargs, _ = created[0]
        assert kwargs["socket_timeout"] == redis_client.SOCKET_TIMEOUT_SECONDS
        assert kwargs["socket_connect_timeout"] == redis_client.SOCKET_CONNECT_TIMEOUT_SECONDS
        assert kwargs["decode_responses"] is True

    def test_client_is_cached_per_event_loop(self, created):
        """#871: a worker task's ``asyncio.run()`` must not reuse a client bound to a dead loop."""

        async def grab_twice():
            return redis_client.get_shared_redis_client(), redis_client.get_shared_redis_client()

        a, b = asyncio.run(grab_twice())
        c, _ = asyncio.run(grab_twice())

        assert a is b, "same loop reuses the client"
        assert c is not a, "a new loop gets a new client"
        assert len(created) == 2

    async def test_close_clears_the_singleton_and_is_idempotent(self, created):
        client = redis_client.get_shared_redis_client()

        await redis_client.close_shared_redis_client()
        await redis_client.close_shared_redis_client()

        assert type(client).closed == 1
        assert redis_client.get_shared_redis_client() is not client


def test_release_evidence_plan_for_the_shared_client_is_committed():
    """Operator note (#535): the VPS runtime-config plan behind the shared client is on record."""
    from pathlib import Path

    plan = json.loads(
        Path("agent-runtime/artifacts/release-evidence-plan-issue-535.json").read_text(
            encoding="utf-8"
        )
    )
    assert plan["planId"] == "rep-535-vps-redis-shared-client"
    assert "demo.app-juli.com" in plan["affectedPublicSurfaces"]
