"""Users, shops and the commerce aggregates (``repositories/identity.py``, ``commerce.py``)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from juli_backend.database import NotFound
from juli_backend.models.models import Product
from juli_backend.repositories import OrdersRepo, ProductsRepo, ShopsRepo, UsersRepo
from tests.support.builders import make_order, make_order_item, make_product, make_shop, make_user


class TestUsersAndShops:
    async def test_shops_list_is_scoped_to_the_owner(self, session):
        alice, bob = await make_user(session), await make_user(session)
        alices_shop = await make_shop(session, alice)
        await make_shop(session, bob)

        assert await ShopsRepo(session).list(alice.id) == [alices_shop]

    async def test_shops_list_is_empty_for_a_user_without_shops(self, session):
        user = await make_user(session)

        assert await ShopsRepo(session).list(user.id) == []

    async def test_users_get_returns_the_user_or_raises(self, session):
        user = await make_user(session, display_name="Seller X")
        repo = UsersRepo(session)

        assert (await repo.get(user.id)).display_name == "Seller X"
        with pytest.raises(NotFound, match="User .* not found"):
            await repo.get(uuid.uuid4())

    async def test_users_get_or_create_is_idempotent(self, session):
        repo = UsersRepo(session)
        user_id = uuid.uuid4()

        created = await repo.get_or_create(user_id, phone="+84900000001")
        again = await repo.get_or_create(user_id, phone="+84900000002")

        assert again is created
        assert created.phone == "+84900000001"

    async def test_shops_create_binds_to_the_owner_and_tiktok_id(self, session):
        user = await make_user(session)

        shop = await ShopsRepo(session).create(user.id, "New Shop", tiktok_shop_id="tts_123")

        assert (shop.user_id, shop.shop_name, shop.tiktok_shop_id) == (
            user.id,
            "New Shop",
            "tts_123",
        )
        assert shop.id is not None

    async def test_pause_automation_deactivates_and_tolerates_unknown_shop(self, session, shop):
        repo = ShopsRepo(session)

        await repo.pause_automation(shop.id)
        await repo.pause_automation(uuid.uuid4())  # never onboarded: nothing to pause

        assert shop.is_active is False


class TestProductsRevenueRecompute:
    """#943: ``revenue``/``units_sold`` are a full SUM over order lines, never an increment."""

    @staticmethod
    async def _refreshed(session, product: Product) -> Product:
        """``recompute`` writes with a bulk UPDATE, so the loaded instance is stale."""
        await session.refresh(product)
        return product

    async def test_sums_every_matching_line_and_ignores_other_products(self, session, shop):
        product = await make_product(session, shop, tiktok_product_id="prod-1")
        await make_order_item(
            session, shop, tiktok_product_id="prod-1", quantity=2, line_total=Decimal("200")
        )
        await make_order_item(
            session, shop, tiktok_product_id="prod-1", quantity=1, line_total=Decimal("50")
        )
        await make_order_item(
            session, shop, tiktok_product_id="prod-other", quantity=9, line_total=Decimal("9")
        )

        await ProductsRepo(session).recompute_revenue_from_order_items(shop.id, "prod-1")

        product = await self._refreshed(session, product)
        assert (product.revenue, product.units_sold) == (Decimal("250"), 3)

    async def test_redelivered_line_does_not_double_count(self, session, shop):
        product = await make_product(session, shop, tiktok_product_id="prod-2")
        item = await make_order_item(
            session, shop, tiktok_product_id="prod-2", line_total=Decimal("100")
        )
        repo = ProductsRepo(session)
        await repo.recompute_revenue_from_order_items(shop.id, "prod-2")

        item.line_total = Decimal("150")  # webhook redelivery with a corrected total
        await session.flush()
        await repo.recompute_revenue_from_order_items(shop.id, "prod-2")

        product = await self._refreshed(session, product)
        assert (product.revenue, product.units_sold) == (Decimal("150"), 1)

    async def test_is_a_noop_before_the_product_has_synced(self, session, shop):
        await make_order_item(session, shop, tiktok_product_id="prod-unsynced")

        await ProductsRepo(session).recompute_revenue_from_order_items(shop.id, "prod-unsynced")


class TestProductsRanking:
    async def test_highest_revenue_breaks_ties_on_tiktok_product_id(self, session, shop):
        """ADR-082: the same ActionCard approved twice must bind to the same listing."""
        await make_product(session, shop, tiktok_product_id="b", revenue=Decimal("10"))
        winner = await make_product(session, shop, tiktok_product_id="a", revenue=Decimal("10"))
        await make_product(session, shop, tiktok_product_id="c", revenue=Decimal("5"))

        assert (await ProductsRepo(session).get_highest_revenue_product(shop.id)) is winner

    async def test_highest_revenue_is_none_for_a_shop_without_products(self, session, shop):
        assert await ProductsRepo(session).get_highest_revenue_product(shop.id) is None

    async def test_list_by_revenue_pages_in_revenue_order(self, session, shop):
        low = await make_product(session, shop, revenue=Decimal("1"))
        high = await make_product(session, shop, revenue=Decimal("3"))
        mid = await make_product(session, shop, revenue=Decimal("2"))
        repo = ProductsRepo(session)

        page_one = await repo.list_by_revenue(shop.id, limit=2)
        page_two = await repo.list_by_revenue(shop.id, limit=2, after=page_one[-1].id)

        assert page_one == [high, mid]
        assert page_two == [low]


class TestOrders:
    async def test_list_filtered_by_status_and_window(self, session, shop):
        from datetime import timedelta

        from tests.support.builders import utc_now_naive

        now = utc_now_naive()
        shipped_recent = await make_order(session, shop, status="SHIPPED", update_time=now)
        await make_order(session, shop, status="SHIPPED", update_time=now - timedelta(days=3))
        await make_order(session, shop, status="AWAITING_SHIPMENT", update_time=now)

        result = await OrdersRepo(session).list_filtered(
            shop.id, status="SHIPPED", date_from=now - timedelta(days=1)
        )

        assert result == [shipped_recent]

    async def test_get_by_tiktok_id_is_shop_scoped(self, session, shop):
        from tests.support.builders import make_tenant

        _, other_shop = await make_tenant(session)
        await make_order(session, other_shop, tiktok_order_id="tt-shared")
        mine = await make_order(session, shop, tiktok_order_id="tt-shared")
        repo = OrdersRepo(session)

        assert (await repo.get_by_tiktok_id(shop.id, "tt-shared")) is mine
        assert await repo.get_by_tiktok_id(shop.id, "tt-missing") is None

    async def test_confirm_shipment_moves_awaiting_to_shipped_with_naive_utc(self, session, shop):
        """#1138: ``update_time`` is a naive column; asyncpg rejects an aware value at flush."""
        order = await make_order(session, shop, status="AWAITING_SHIPMENT")

        shipped = await OrdersRepo(session).confirm_shipment(shop.id, order.id)

        assert shipped.status == "SHIPPED"
        assert shipped.update_time.tzinfo is None

    @pytest.mark.parametrize("status", ["SHIPPED", "CANCELLED", "COMPLETED"])
    async def test_confirm_shipment_refuses_any_other_status(self, session, shop, status):
        order = await make_order(session, shop, status=status)

        with pytest.raises(ValueError, match=f"Cannot ship order in status '{status}'"):
            await OrdersRepo(session).confirm_shipment(shop.id, order.id)
