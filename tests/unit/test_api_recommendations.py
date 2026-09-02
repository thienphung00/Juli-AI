"""GET /v1/recommendations -- extended ``host_product_match`` schema (#93 AC5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Creator, InventoryItem, Livestream, Shop
from juli_backend.repositories.repos import GraphRepo
from tests.support.builders import make_order, make_product, next_unique


async def seed_host_product_match(session: AsyncSession, shop: Shop) -> tuple[Creator, uuid.UUID]:
    """A creator, a product and a ``potential_match`` graph edge between them,
    plus enough livestream/inventory/order history for the matcher to score it."""
    now = datetime.now(UTC)
    creator = Creator(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_creator_id=next_unique("creator"),
        name="Lan",
        commission_rate=Decimal("0.08"),
    )
    session.add(creator)
    product = await make_product(session, shop, revenue=Decimal("3000000"), units_sold=120)
    session.add(
        Livestream(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_livestream_id=next_unique("live"),
            creator_id=creator.id,
            title="Live test",
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=2),
            viewer_count=800,
            order_count=40,
            revenue=Decimal("8000000"),
            update_time=now,
        )
    )
    session.add(
        InventoryItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=product.tiktok_product_id,
            tiktok_sku_id=next_unique("sku"),
            quantity=50,
            velocity="medium",
            update_time=now,
        )
    )
    # 14 distinct order days: get_velocity_changes needs >= 14 days of a SKU's
    # daily-units series (forecaster._daily_units_series reads Order.created_at).
    for i in range(14):
        await make_order(
            session,
            shop,
            status="COMPLETED",
            update_time=now.replace(tzinfo=None) - timedelta(days=i),
            created_at=now - timedelta(days=i),
        )
    await session.flush()

    await GraphRepo(session).upsert_edge(
        shop.id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=creator.id,
        target_node_type="product",
        target_node_id=product.id,
        weight=Decimal("0.92"),
    )
    return creator, product.id


class TestHostProductMatchSchema:
    """A refreshed ``host_product_match`` recommendation carries the extended
    predicted-outcome and payload fields (#93 AC5)."""

    async def test_response_carries_predicted_outcome_and_action_fields(
        self, auth_client, session, shop
    ):
        creator, product_id = await seed_host_product_match(session, shop)

        response = await auth_client.get("/v1/recommendations", headers={"X-Shop-Id": str(shop.id)})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        items = body["data"]
        assert items, "expected at least one recommendation"

        host_items = [i for i in items if i["recommendation_type"] == "host_product_match"]
        assert host_items, "expected a refreshed host_product_match row"
        item = host_items[0]

        assert isinstance(item["match_score"], (int, float))
        assert item["match_score"] > 0
        assert item["action_type"] in ("contact_creator", "adjust_commission", "schedule_live")
        assert item["confidence"] in ("high", "medium", "low")
        assert item["cta"]
        assert item.get("source") in ("llm", "rules")

        predicted = item["predicted_outcome"]
        assert predicted is not None
        assert predicted["gmv_vnd_week"]["high"] >= predicted["gmv_vnd_week"]["low"]
        assert isinstance(predicted["conversion_pct"], (int, float))
        assert isinstance(predicted["engagement_index"], (int, float))
        assert isinstance(predicted["risk_factors"], list)

        payload = item.get("payload") or {}
        assert payload.get("creator_id")
        assert payload.get("tiktok_product_id")
