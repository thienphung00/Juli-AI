"""Issue #28 — Commerce + analytics tables + repository layer.

AC1 → test_commerce_models_indexed_by_shop_and_date
AC2 → test_analytics_models_relationships
AC3 → test_repos_enforce_shop_scoping_and_pagination
"""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.exceptions import NotFound
from src.data.models import (
    AlertConfig,
    AlertHistory,
    Creator,
    InventoryItem,
    Livestream,
    Order,
    Product,
    Recommendation,
    Settlement,
    Shop,
    User,
)
from src.data.repos import OrdersRepo

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def two_shops(session, user_id, other_user_id):
    user_a = User(id=user_id, phone="+84901111111")
    user_b = User(id=other_user_id, phone="+84902222222")
    shop_a = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Shop A")
    shop_b = Shop(id=uuid.uuid4(), user_id=other_user_id, shop_name="Shop B")
    session.add_all([user_a, user_b, shop_a, shop_b])
    await session.flush()
    return shop_a, shop_b


# --- AC1: Commerce models with composite indexes on (shop_id, created_at) ---


class TestCommerceModelsIndexedByShopAndDate:
    @pytest.mark.parametrize("model", [Order, Product, InventoryItem, Settlement])
    def test_commerce_model_has_shop_created_at_index(self, model):
        found = False
        for idx in model.__table__.indexes:
            cols = {c.name for c in idx.columns}
            if "shop_id" in cols and "created_at" in cols:
                found = True
                break
        assert found, (
            f"{model.__name__} missing composite index on (shop_id, created_at)"
        )

    async def test_settlement_status_defaults_to_pending(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        s = Settlement(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_settlement_id="stl_1",
            amount=100.00,
            currency="VND",
            update_time=datetime.utcnow(),
        )
        session.add(s)
        await session.flush()
        await session.refresh(s)
        assert s.status == "pending"


# --- AC2: Analytics models with appropriate relationships ---


class TestAnalyticsModelsRelationships:
    async def test_livestream_belongs_to_creator(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        creator = Creator(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_creator_id="cr_1",
            name="Creator A",
        )
        session.add(creator)
        await session.flush()

        livestream = Livestream(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_livestream_id="ls_1",
            creator_id=creator.id,
            title="Test Stream",
        )
        session.add(livestream)
        await session.flush()

        await session.refresh(livestream, ["creator"])
        assert livestream.creator.name == "Creator A"

    async def test_alert_history_belongs_to_alert_config(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        config = AlertConfig(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            alert_type="low_stock",
            channel="fcm",
            is_active=True,
        )
        session.add(config)
        await session.flush()

        history = AlertHistory(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            alert_config_id=config.id,
            triggered_at=datetime.utcnow(),
            status="sent",
        )
        session.add(history)
        await session.flush()

        await session.refresh(history, ["alert_config"])
        assert history.alert_config.alert_type == "low_stock"

    @pytest.mark.parametrize(
        "model", [Creator, Livestream, AlertConfig, AlertHistory, Recommendation]
    )
    def test_analytics_model_has_shop_id(self, model):
        assert hasattr(model, "shop_id"), f"{model.__name__} missing shop_id"


# --- AC3: Repos with mandatory shop_id scoping and cursor-based pagination ---


class TestReposEnforceShopScopingAndPagination:
    async def test_list_returns_only_orders_for_given_shop(
        self, session: AsyncSession, two_shops
    ):
        shop_a, shop_b = two_shops
        now = datetime.utcnow()

        order_a = Order(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="UNPAID",
            total_amount=100,
            currency="VND",
            update_time=now,
        )
        order_b = Order(
            id=uuid.uuid4(),
            shop_id=shop_b.id,
            tiktok_order_id="ord_2",
            status="PAID",
            total_amount=200,
            currency="VND",
            update_time=now,
        )
        session.add_all([order_a, order_b])
        await session.flush()

        repo = OrdersRepo(session)
        result = await repo.list(shop_a.id)

        assert len(result) == 1
        assert result[0].tiktok_order_id == "ord_1"

    async def test_list_cursor_pagination(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        now = datetime.utcnow()

        orders = []
        for i in range(5):
            o = Order(
                id=uuid.uuid4(),
                shop_id=shop_a.id,
                tiktok_order_id=f"ord_{i}",
                status="PAID",
                total_amount=i * 100,
                currency="VND",
                created_at=now + timedelta(seconds=i),
                update_time=now + timedelta(seconds=i),
            )
            orders.append(o)
        session.add_all(orders)
        await session.flush()

        repo = OrdersRepo(session)

        page1 = await repo.list(shop_a.id, limit=2)
        assert len(page1) == 2

        page2 = await repo.list(shop_a.id, limit=2, after=page1[-1].id)
        assert len(page2) == 2

        page3 = await repo.list(shop_a.id, limit=2, after=page2[-1].id)
        assert len(page3) == 1

        all_ids = [o.id for o in page1 + page2 + page3]
        assert len(set(all_ids)) == 5

    async def test_get_raises_not_found_for_wrong_shop(
        self, session: AsyncSession, two_shops
    ):
        shop_a, shop_b = two_shops
        order = Order(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="PAID",
            total_amount=100,
            currency="VND",
            update_time=datetime.utcnow(),
        )
        session.add(order)
        await session.flush()

        repo = OrdersRepo(session)
        with pytest.raises(NotFound):
            await repo.get(shop_b.id, order.id)

    async def test_get_returns_entity_for_correct_shop(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        order = Order(
            id=uuid.uuid4(),
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="PAID",
            total_amount=100,
            currency="VND",
            update_time=datetime.utcnow(),
        )
        session.add(order)
        await session.flush()

        repo = OrdersRepo(session)
        result = await repo.get(shop_a.id, order.id)
        assert result.tiktok_order_id == "ord_1"

    async def test_upsert_creates_new_entity(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        repo = OrdersRepo(session)

        order = await repo.upsert(
            shop_id=shop_a.id,
            tiktok_order_id="ord_new",
            status="UNPAID",
            total_amount=500,
            currency="VND",
            update_time=datetime.utcnow(),
        )
        assert order.tiktok_order_id == "ord_new"
        assert order.shop_id == shop_a.id
        assert order.id is not None

    async def test_upsert_updates_existing_when_newer(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        now = datetime.utcnow()
        repo = OrdersRepo(session)

        await repo.upsert(
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="UNPAID",
            total_amount=100,
            currency="VND",
            update_time=now,
        )

        updated = await repo.upsert(
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="PAID",
            total_amount=100,
            currency="VND",
            update_time=now + timedelta(seconds=10),
        )
        assert updated.status == "PAID"

    async def test_upsert_skips_stale_update(
        self, session: AsyncSession, two_shops
    ):
        shop_a, _ = two_shops
        now = datetime.utcnow()
        repo = OrdersRepo(session)

        await repo.upsert(
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="PAID",
            total_amount=100,
            currency="VND",
            update_time=now,
        )

        stale = await repo.upsert(
            shop_id=shop_a.id,
            tiktok_order_id="ord_1",
            status="UNPAID",
            total_amount=50,
            currency="VND",
            update_time=now - timedelta(seconds=10),
        )
        assert stale.status == "PAID"
