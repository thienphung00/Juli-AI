"""P2.10-A7 (#531) — unauthenticated GET /v1/demo/analytics."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import Order, Shop, User
from juli_backend.repositories.repos import GoldKpiEnvelopesRepo

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


async def _create_orders_with_gmv_series(session, shop_id: uuid.UUID) -> None:
    """Create test orders that will produce the expected gmv_tiktok series.

    Expected series from test assertions:
    - 2026-06-01: 100.0
    - 2026-07-01: 6408074.0
    - 2026-07-14: 1200000.0
    """
    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_order_id="order-1",
            status="COMPLETED",
            total_amount=Decimal("100.0"),
            currency="VND",
            tiktok_created_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            update_time=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ),
        Order(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_order_id="order-2",
            status="COMPLETED",
            total_amount=Decimal("6408074.0"),
            currency="VND",
            tiktok_created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            update_time=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        ),
        Order(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_order_id="order-3",
            status="COMPLETED",
            total_amount=Decimal("1200000.0"),
            currency="VND",
            tiktok_created_at=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
            update_time=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        ),
    ]
    for order in orders:
        session.add(order)
    await session.flush()


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
    # Create orders that will generate the expected gold envelope
    await _create_orders_with_gmv_series(session, reference_shop.id)

    # Compute and persist the gold envelope
    from juli_backend.services.gold_kpi_envelope_serving import (
        write_demo_main_kpis_envelope,
    )

    await write_demo_main_kpis_envelope(session, reference_shop.id)
    await session.flush()

    with patch(
        "juli_backend.api.routes.demo_analytics.get_shared_redis_client",
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
async def test_reference_shop_id_configured_server_side_for_public_analytics_get(
    demo_client,
    session,
    reference_shop,
    demo_reference_shop_id,
) -> None:
    # Create orders that will generate the expected gold envelope
    await _create_orders_with_gmv_series(session, reference_shop.id)

    # Compute and persist the gold envelope
    from juli_backend.services.gold_kpi_envelope_serving import (
        write_demo_main_kpis_envelope,
    )

    await write_demo_main_kpis_envelope(session, reference_shop.id)
    await session.flush()

    with patch(
        "juli_backend.api.routes.demo_analytics.get_shared_redis_client",
        return_value=None,
    ):
        resp = await demo_client.get("/v1/demo/analytics")

    assert resp.status_code == 200
    assert resp.json()["shop_id"] != str(demo_reference_shop_id)


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
async def test_get_demo_analytics_uses_cache_sot_read_path(
    demo_client,
    session,
    reference_shop,
) -> None:
    from juli_backend.services.gold_kpi_cache import envelope_cache_key
    from juli_backend.services.gold_kpi_envelope_serving import (
        compute_demo_main_kpis_payload,
    )

    # Create orders that will generate the expected gold envelope payload
    await _create_orders_with_gmv_series(session, reference_shop.id)

    # Compute the payload and cache it
    computed_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    payload = await compute_demo_main_kpis_payload(
        session, reference_shop.id, computed_at=computed_at
    )
    redis = FakeAsyncRedis()
    await redis.set(envelope_cache_key(reference_shop.id), json.dumps(payload))

    with patch(
        "juli_backend.api.routes.demo_analytics.get_shared_redis_client",
        return_value=redis,
    ):
        resp = await demo_client.get("/v1/demo/analytics")

    assert resp.status_code == 200
    # Verify the gold envelope was read from cache and not from Postgres
    assert await GoldKpiEnvelopesRepo(session).get(reference_shop.id) is None


@pytest.mark.asyncio
async def test_smoke_fake_refresh_does_not_trigger_partner_fetch_storm(
    demo_client,
    session,
    reference_shop,
) -> None:
    # Create orders that will generate the expected gold envelope
    await _create_orders_with_gmv_series(session, reference_shop.id)

    # Compute and persist the gold envelope
    from juli_backend.services.gold_kpi_envelope_serving import (
        write_demo_main_kpis_envelope,
    )

    await write_demo_main_kpis_envelope(session, reference_shop.id)
    await session.flush()

    with (
        patch(
            "juli_backend.api.routes.demo_analytics.get_shared_redis_client",
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
    # Create orders that will generate the expected gold envelope
    await _create_orders_with_gmv_series(session, reference_shop.id)

    # Compute and persist the gold envelope
    from juli_backend.services.gold_kpi_envelope_serving import (
        write_demo_main_kpis_envelope,
    )

    await write_demo_main_kpis_envelope(session, reference_shop.id)
    await session.flush()

    with patch(
        "juli_backend.api.routes.demo_analytics.get_shared_redis_client",
        return_value=None,
    ):
        resp = await demo_client.get("/v1/demo/analytics", params={"range": "30d"})

    assert resp.status_code == 200
    series = resp.json()["kpis"]["gmv_tiktok"]["series"]
    assert all(point["t"] >= "2026-06-27" for point in series)
    assert not any(point["t"] == "2026-06-01" for point in series)
