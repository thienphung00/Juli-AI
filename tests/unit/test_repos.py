"""AC2 — ShopsRepo.list(user_id) returns only shops belonging to that user;
UsersRepo.get(user_id) returns user or raises NotFound."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import NotFound, Shop, ShopsRepo, User, UsersRepo
from juli_backend.models.models import OrderItem, Product
from juli_backend.repositories.repos import ProductsRepo

pytestmark = pytest.mark.asyncio


class TestShopsRepoScopedByUser:
    """AC2: Repository queries enforce user-scoped data isolation."""

    async def test_shops_repo_list_returns_only_user_shops(
        self, session: AsyncSession, user_id, other_user_id
    ):
        user_a = User(id=user_id, phone="+84901111111")
        user_b = User(id=other_user_id, phone="+84902222222")
        shop_a = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Shop A")
        shop_b = Shop(id=uuid.uuid4(), user_id=other_user_id, shop_name="Shop B")
        session.add_all([user_a, user_b, shop_a, shop_b])
        await session.flush()

        repo = ShopsRepo(session)
        result = await repo.list(user_id)

        assert len(result) == 1
        assert result[0].shop_name == "Shop A"
        assert result[0].user_id == user_id

    async def test_shops_repo_list_returns_empty_when_no_shops(self, session: AsyncSession):
        lonely_user_id = uuid.uuid4()
        user = User(id=lonely_user_id, phone="+84903333333")
        session.add(user)
        await session.flush()

        repo = ShopsRepo(session)
        result = await repo.list(lonely_user_id)
        assert result == []

    async def test_users_repo_get_returns_user(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84904444444", display_name="Seller X")
        session.add(user)
        await session.flush()

        repo = UsersRepo(session)
        result = await repo.get(user_id)

        assert result.id == user_id
        assert result.display_name == "Seller X"

    async def test_users_repo_get_raises_not_found(self, session: AsyncSession):
        repo = UsersRepo(session)
        with pytest.raises(NotFound):
            await repo.get(uuid.uuid4())

    async def test_shops_repo_create(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84905555555")
        session.add(user)
        await session.flush()

        repo = ShopsRepo(session)
        shop = await repo.create(
            user_id=user_id,
            shop_name="New Shop",
            tiktok_shop_id="tts_123456",
        )

        assert shop.user_id == user_id
        assert shop.shop_name == "New Shop"
        assert shop.tiktok_shop_id == "tts_123456"
        assert shop.id is not None


class TestProductsRepoRecomputeRevenueFromOrderItems:
    """#943 — products.revenue/units_sold sourced from real order_items data."""

    def _now(self):
        return datetime.now(UTC)

    async def _seed_product(
        self, session: AsyncSession, *, shop_id: uuid.UUID, tiktok_product_id: str
    ) -> Product:
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
            name="Widget",
            status="ACTIVE",
            update_time=self._now(),
        )
        session.add(product)
        await session.flush()
        return product

    async def _add_order_item(
        self,
        session: AsyncSession,
        *,
        shop_id: uuid.UUID,
        tiktok_order_id: str,
        tiktok_product_id: str,
        tiktok_sku_id: str,
        quantity: int,
        line_total: Decimal,
    ) -> OrderItem:
        item = OrderItem(
            id=uuid.uuid4(),
            shop_id=shop_id,
            order_id=uuid.uuid4(),
            tiktok_order_id=tiktok_order_id,
            tiktok_product_id=tiktok_product_id,
            tiktok_sku_id=tiktok_sku_id,
            quantity=quantity,
            unit_price=line_total / quantity,
            line_total=line_total,
            update_time=self._now(),
        )
        session.add(item)
        await session.flush()
        return item

    async def _get_product(
        self, session: AsyncSession, *, shop_id: uuid.UUID, tiktok_product_id: str
    ) -> Product:
        stmt = select(Product).where(
            Product.shop_id == shop_id,
            Product.tiktok_product_id == tiktok_product_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def test_recompute_sums_all_matching_order_items(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84906666666")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Revenue Shop")
        session.add_all([user, shop])
        await session.flush()
        shop_id = shop.id

        await self._seed_product(session, shop_id=shop_id, tiktok_product_id="prod-1")
        await self._add_order_item(
            session,
            shop_id=shop_id,
            tiktok_order_id="ord-1",
            tiktok_product_id="prod-1",
            tiktok_sku_id="sku-1",
            quantity=2,
            line_total=Decimal("200.00"),
        )
        await self._add_order_item(
            session,
            shop_id=shop_id,
            tiktok_order_id="ord-2",
            tiktok_product_id="prod-1",
            tiktok_sku_id="sku-2",
            quantity=3,
            line_total=Decimal("300.00"),
        )

        repo = ProductsRepo(session)
        await repo.recompute_revenue_from_order_items(shop_id, "prod-1")
        await session.flush()
        session.expire_all()

        product = await self._get_product(session, shop_id=shop_id, tiktok_product_id="prod-1")
        assert product.revenue == Decimal("500.00")
        assert product.units_sold == 5

    async def test_recompute_is_a_full_recompute_not_an_increment(
        self, session: AsyncSession, user_id
    ):
        """A corrected/redelivered order_item must not double-count on re-run."""
        user = User(id=user_id, phone="+84907777777")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Revenue Shop 2")
        session.add_all([user, shop])
        await session.flush()
        shop_id = shop.id

        await self._seed_product(session, shop_id=shop_id, tiktok_product_id="prod-2")
        item = await self._add_order_item(
            session,
            shop_id=shop_id,
            tiktok_order_id="ord-3",
            tiktok_product_id="prod-2",
            tiktok_sku_id="sku-3",
            quantity=1,
            line_total=Decimal("100.00"),
        )

        repo = ProductsRepo(session)
        await repo.recompute_revenue_from_order_items(shop_id, "prod-2")

        # Webhook redelivery with a corrected total for the same line.
        item.line_total = Decimal("150.00")
        item.quantity = 1
        await session.flush()
        await repo.recompute_revenue_from_order_items(shop_id, "prod-2")
        await session.flush()
        session.expire_all()

        product = await self._get_product(session, shop_id=shop_id, tiktok_product_id="prod-2")
        assert product.revenue == Decimal("150.00")
        assert product.units_sold == 1

    async def test_recompute_is_a_noop_when_product_not_yet_synced(
        self, session: AsyncSession, user_id
    ):
        user = User(id=user_id, phone="+84908888888")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Revenue Shop 3")
        session.add_all([user, shop])
        await session.flush()

        await self._add_order_item(
            session,
            shop_id=shop.id,
            tiktok_order_id="ord-4",
            tiktok_product_id="prod-unsynced",
            tiktok_sku_id="sku-4",
            quantity=1,
            line_total=Decimal("50.00"),
        )

        repo = ProductsRepo(session)
        # Must not raise even though no product row matches yet.
        await repo.recompute_revenue_from_order_items(shop.id, "prod-unsynced")
