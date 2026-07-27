"""P2.10-A7 (#531) — unauthenticated GET /v1/demo/analytics."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo
from sqlalchemy.ext.asyncio import async_sessionmaker

REAL_SHOP_DISPLAY_NAME = "Fujiwa Official Store"
REAL_MERCHANT_ID = "7658073774813611784"


class FakeAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> bool:
        self._store[key] = value
        return True


def _raw_envelope_payload(*, shop_id: uuid.UUID, computed_at: datetime) -> dict:
    return {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": "VND",
        "identity": {
            "shop_display_name": REAL_SHOP_DISPLAY_NAME,
            "merchant_id": REAL_MERCHANT_ID,
            "products": [{"id": "7136011254174631686", "title": "Organic Matcha Powder"}],
        },
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "series": [
                    {"t": "2026-06-01", "v": 100.0},
                    {"t": "2026-07-01", "v": 6408074.0},
                    {"t": "2026-07-14", "v": 1200000.0},
                ],
            }
        },
        "meta": {"source_partitions": ["A-36"], "notes": []},
    }


@pytest.fixture
def demo_reference_shop_id() -> uuid.UUID:
    return uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@pytest.fixture
def demo_env(monkeypatch, demo_reference_shop_id):
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(demo_reference_shop_id))


@pytest_asyncio.fixture
async def reference_shop(session, user_id, demo_reference_shop_id):
    user = User(id=user_id, phone="+849305000531")
    session.add(user)
    await session.flush()
    shop = Shop(
        id=demo_reference_shop_id,
        user_id=user.id,
        shop_name="Reference Shop 531",
        tiktok_shop_id="tiktok_ref_531",
    )
    session.add(shop)
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def demo_client(engine, demo_env):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client
    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_demo_analytics_returns_masked_envelope_without_auth(
    demo_client,
    session,
    reference_shop,
    demo_reference_shop_id,
) -> None:
    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _raw_envelope_payload(shop_id=reference_shop.id, computed_at=computed_at)
    await AnalyticsKpiEnvelopesRepo(session).upsert(
        shop_id=reference_shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    with patch(
        "juli_backend.api.routes.demo_analytics.create_redis_client",
        return_value=None,
    ):
        resp = await demo_client.get("/v1/demo/analytics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["envelope_version"] == 1
    assert body["kind"] == "analytics"
    assert body["shop_id"] != str(demo_reference_shop_id)
    assert body["shop_id"].startswith("demo-shop-")
    identity = body["identity"]
    assert identity["shop_display_name"].startswith("Demo Shop")
    assert identity["shop_display_name"] != REAL_SHOP_DISPLAY_NAME
    assert "merchant_id" not in identity
    assert body["kpis"]["gmv_tiktok"]["series"][2]["v"] == 1200000.0


@pytest.mark.asyncio
async def test_get_demo_analytics_rejects_visitor_shop_id(demo_client, reference_shop) -> None:
    other_shop = uuid.uuid4()
    resp = await demo_client.get(
        "/v1/demo/analytics",
        params={"shop_id": str(other_shop)},
    )
    assert resp.status_code == 400
    assert "shop_id" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_demo_analytics_reads_through_redis_cache(
    demo_client,
    session,
    reference_shop,
) -> None:
    from juli_backend.services.analytics_kpi_cache import envelope_cache_key

    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _raw_envelope_payload(shop_id=reference_shop.id, computed_at=computed_at)
    redis = FakeAsyncRedis()
    await redis.set(envelope_cache_key(reference_shop.id), json.dumps(payload))

    with patch(
        "juli_backend.api.routes.demo_analytics.create_redis_client",
        return_value=redis,
    ):
        resp = await demo_client.get("/v1/demo/analytics")

    assert resp.status_code == 200
    assert (
        await AnalyticsKpiEnvelopesRepo(session).get_by_kind(reference_shop.id, "analytics") is None
    )


@pytest.mark.asyncio
async def test_get_demo_analytics_does_not_enqueue_compute(
    demo_client,
    session,
    reference_shop,
) -> None:
    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _raw_envelope_payload(shop_id=reference_shop.id, computed_at=computed_at)
    await AnalyticsKpiEnvelopesRepo(session).upsert(
        shop_id=reference_shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    with (
        patch(
            "juli_backend.api.routes.demo_analytics.create_redis_client",
            return_value=None,
        ),
        patch(
            "juli_backend.services.analytics_kpi_precompute.precompute_shop_analytics_kpis",
            new=AsyncMock(),
        ) as precompute_mock,
    ):
        resp = await demo_client.get("/v1/demo/analytics")

    assert resp.status_code == 200
    precompute_mock.assert_not_called()


@pytest.mark.asyncio
async def test_get_demo_analytics_range_filters_chart_series(
    demo_client,
    session,
    reference_shop,
) -> None:
    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = _raw_envelope_payload(shop_id=reference_shop.id, computed_at=computed_at)
    await AnalyticsKpiEnvelopesRepo(session).upsert(
        shop_id=reference_shop.id,
        kind="analytics",
        envelope_version=1,
        payload=payload,
        computed_at=computed_at,
    )
    await session.flush()

    with patch(
        "juli_backend.api.routes.demo_analytics.create_redis_client",
        return_value=None,
    ):
        resp = await demo_client.get("/v1/demo/analytics", params={"range": "30d"})

    assert resp.status_code == 200
    series = resp.json()["kpis"]["gmv_tiktok"]["series"]
    assert all(point["t"] >= "2026-06-27" for point in series)
    assert not any(point["t"] == "2026-06-01" for point in series)
