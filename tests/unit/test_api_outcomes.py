"""POST /v1/outcomes -- realized-GMV feedback ingest (#94)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.recommendations.engine import get_host_product_matching
from juli_backend.models.models import Creator, InventoryItem, Livestream, Shop
from juli_backend.services.feedback import ingest_campaign_outcome
from tests.support.builders import make_product, next_unique


async def seed_match_shop(session: AsyncSession, shop: Shop) -> tuple[Creator, uuid.UUID, str]:
    """A creator and an active product with enough live/inventory history to match."""
    now = datetime.now(UTC)
    creator = Creator(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_creator_id=next_unique("creator"),
        name="Mai",
        commission_rate=Decimal("0.10"),
    )
    session.add(creator)
    product = await make_product(session, shop, revenue=Decimal("2000000"), units_sold=80)
    session.add(
        Livestream(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_livestream_id=next_unique("live"),
            creator_id=creator.id,
            title="Live outcome",
            start_time=now,
            end_time=now,
            viewer_count=500,
            order_count=20,
            revenue=Decimal("3000000"),
            update_time=now,
        )
    )
    session.add(
        InventoryItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=product.tiktok_product_id,
            tiktok_sku_id=next_unique("sku"),
            quantity=30,
            velocity="medium",
            update_time=now,
        )
    )
    await session.flush()
    return creator, product.id, product.tiktok_product_id


class TestIngest:
    """POST /v1/outcomes records realized GMV against a prior prediction."""

    async def test_returns_success_envelope_with_campaign_id_and_edge_count(
        self, auth_client, shop, session
    ):
        creator, product_id, _ = await seed_match_shop(session, shop)

        response = await auth_client.post(
            "/v1/outcomes",
            json={
                "idempotency_key": next_unique("outcome"),
                "creator_id": str(creator.id),
                "product_ids": [str(product_id)],
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

    async def test_duplicate_idempotency_key_does_not_double_write(
        self, auth_client, shop, session
    ):
        creator, product_id, _ = await seed_match_shop(session, shop)
        payload = {
            "idempotency_key": next_unique("outcome"),
            "creator_id": str(creator.id),
            "product_ids": [str(product_id)],
            "predicted_gmv": "1000000",
            "realized_gmv": "2000000",
        }

        first = await auth_client.post("/v1/outcomes", json=payload)
        second = await auth_client.post("/v1/outcomes", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["data"]["is_duplicate"] is True
        assert second.json()["data"]["edge_count"] == 0

    async def test_invalid_outcome_does_not_break_recommendations(self, auth_client, shop, session):
        creator, product_id, _ = await seed_match_shop(session, shop)

        bad = await auth_client.post(
            "/v1/outcomes",
            json={
                "idempotency_key": next_unique("outcome"),
                "creator_id": str(creator.id),
                "product_ids": [str(product_id)],
                "realized_gmv": "1000",
                "campaign_id": str(uuid.uuid4()),
            },
        )
        assert bad.status_code == 404

        reco = await auth_client.get("/v1/recommendations")

        assert reco.status_code == 200
        assert reco.json()["success"] is True

    async def test_matching_score_reflects_the_ingested_outcome(self, shop, session):
        creator, product_id, tiktok_product_id = await seed_match_shop(session, shop)

        before = await get_host_product_matching(session, shop.id, limit=3)
        score_before = next(
            m.match_score
            for m in before
            if m.creator_id == str(creator.id) and m.tiktok_product_id == tiktok_product_id
        )

        await ingest_campaign_outcome(
            session,
            shop.id,
            idempotency_key=next_unique("outcome"),
            creator_id=creator.id,
            product_ids=[product_id],
            predicted_gmv=Decimal("1000000"),
            realized_gmv=Decimal("10000000"),
        )

        after = await get_host_product_matching(session, shop.id, limit=3)
        score_after = next(
            m.match_score
            for m in after
            if m.creator_id == str(creator.id) and m.tiktok_product_id == tiktok_product_id
        )
        assert score_after > score_before
