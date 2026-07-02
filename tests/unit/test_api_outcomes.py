"""POST /v1/outcomes — Issue #94 (P1-3).

AC1 → test_ac1_post_outcomes_returns_success_envelope
AC2 → test_ac2_duplicate_idempotency_key_is_idempotent
AC4 → test_ac4_recommendations_unaffected_when_outcome_invalid
AC5 → test_ac5_ingest_outcome_then_matching_score_reflects_update
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.catalog.domain.recommendations.engine import get_host_product_matching
from backend.database.models import (
    Creator,
    InventoryItem,
    Livestream,
    Product,
    Shop,
    User,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine, session):
    from backend.api.api.app import create_app
    from backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+84999888094")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Outcome API Shop 94",
        tiktok_shop_id="tiktok_shop_094",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from backend.api.api.dependencies import get_active_shop
    from backend.integrations.identity.infrastructure.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _seed_match_shop(session: AsyncSession, shop_id: uuid.UUID) -> tuple[Creator, Product]:
    creator = Creator(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_creator_id="creator_api_94",
        name="Mai",
        commission_rate=Decimal("0.10"),
    )
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id="prod_api_94",
        name="Kem dưỡng",
        status="ACTIVE",
        revenue=Decimal("2000000"),
        units_sold=80,
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    live = Livestream(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_livestream_id="live_api_94",
        creator_id=creator.id,
        title="Live outcome",
        start_time=datetime.now(timezone.utc) - timedelta(hours=2),
        end_time=datetime.now(timezone.utc) - timedelta(hours=1),
        viewer_count=500,
        order_count=20,
        revenue=Decimal("3000000"),
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    inv = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=product.tiktok_product_id,
        tiktok_sku_id="sku_api_94",
        quantity=30,
        velocity="medium",
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    session.add_all([creator, product, live, inv])
    await session.flush()
    return creator, product


async def test_ac1_post_outcomes_returns_success_envelope(auth_client, shop, session):
    """AC1: POST /v1/outcomes accepts realized GMV and returns success envelope."""
    creator, product = await _seed_match_shop(session, shop.id)
    response = await auth_client.post(
        "/v1/outcomes",
        json={
            "idempotency_key": "outcome-ac1",
            "creator_id": str(creator.id),
            "product_ids": [str(product.id)],
            "predicted_gmv": "5000000",
            "realized_gmv": "8000000",
            "realized_conversion": "0.04",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["campaign_id"]
    assert body["data"]["is_duplicate"] is False
    assert body["data"]["edge_count"] == 1


async def test_ac2_duplicate_idempotency_key_is_idempotent(auth_client, shop, session):
    """AC2: duplicate ingest with same idempotency key does not double-write."""
    creator, product = await _seed_match_shop(session, shop.id)
    payload = {
        "idempotency_key": "outcome-ac2-dup",
        "creator_id": str(creator.id),
        "product_ids": [str(product.id)],
        "predicted_gmv": "1000000",
        "realized_gmv": "2000000",
    }
    first = await auth_client.post("/v1/outcomes", json=payload)
    second = await auth_client.post("/v1/outcomes", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["is_duplicate"] is True
    assert second.json()["data"]["edge_count"] == 0


async def test_ac4_recommendations_unaffected_when_outcome_invalid(
    auth_client, shop, session
):
    """AC4: failed outcome ingest does not break GET /v1/recommendations."""
    creator, product = await _seed_match_shop(session, shop.id)
    bad = await auth_client.post(
        "/v1/outcomes",
        json={
            "idempotency_key": "bad-campaign",
            "creator_id": str(creator.id),
            "product_ids": [str(product.id)],
            "realized_gmv": "1000",
            "campaign_id": str(uuid.uuid4()),
        },
    )
    assert bad.status_code == 404

    reco = await auth_client.get("/v1/recommendations")
    assert reco.status_code == 200
    assert reco.json()["success"] is True


async def test_ac5_ingest_outcome_then_matching_score_reflects_update(
    session, shop
):
    """AC5: ingest outcome → re-run matching → score reflects graph calibration."""
    creator, product = await _seed_match_shop(session, shop.id)

    before = await get_host_product_matching(session, shop.id, limit=3)
    assert len(before) >= 1
    score_before = next(
        m.match_score
        for m in before
        if m.creator_id == str(creator.id) and m.tiktok_product_id == product.tiktok_product_id
    )

    from backend.integrations.catalog.domain.feedback import ingest_campaign_outcome

    await ingest_campaign_outcome(
        session,
        shop.id,
        idempotency_key="e2e-outcome-94",
        creator_id=creator.id,
        product_ids=[product.id],
        predicted_gmv=Decimal("1000000"),
        realized_gmv=Decimal("10000000"),
    )

    after = await get_host_product_matching(session, shop.id, limit=3)
    match_after = next(
        m
        for m in after
        if m.creator_id == str(creator.id) and m.tiktok_product_id == product.tiktok_product_id
    )
    assert match_after.match_score > score_before
