"""The contract every ``ShopScopedRepo`` inherits (``repositories/_base.py``).

Exercised through two concrete repositories with different natural keys --
``OrdersRepo`` (one column) and ``OrderItemsRepo`` (two) -- so the proofs are
about the base, not about one table.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from juli_backend.database import NotFound
from juli_backend.repositories import OrderItemsRepo, OrdersRepo, ProductsRepo, ReturnsRepo
from tests.support.builders import make_order, make_tenant, utc_now_naive


class TestGet:
    async def test_returns_the_shops_own_row(self, session, shop):
        order = await make_order(session, shop)

        assert (await OrdersRepo(session).get(shop.id, order.id)) is order

    async def test_another_shops_row_reads_as_missing_not_forbidden(self, session, shop):
        """No existence oracle: a foreign id and a nonexistent id look identical."""
        _, other_shop = await make_tenant(session)
        foreign = await make_order(session, other_shop)

        with pytest.raises(NotFound, match=f"Order {foreign.id} not found"):
            await OrdersRepo(session).get(shop.id, foreign.id)
        with pytest.raises(NotFound, match="Order .* not found"):
            await OrdersRepo(session).get(shop.id, uuid.uuid4())


class TestListPagination:
    async def test_newest_first_and_only_this_shop(self, session, shop):
        _, other_shop = await make_tenant(session)
        await make_order(session, other_shop)
        older = await make_order(session, shop, created_at=utc_now_naive() - timedelta(days=1))
        newer = await make_order(session, shop, created_at=utc_now_naive())

        assert await OrdersRepo(session).list(shop.id) == [newer, older]

    async def test_after_cursor_continues_past_the_given_row(self, session, shop):
        base = utc_now_naive()
        rows = [
            await make_order(session, shop, created_at=base - timedelta(minutes=i))
            for i in range(4)
        ]
        repo = OrdersRepo(session)

        first_page = await repo.list(shop.id, limit=2)
        second_page = await repo.list(shop.id, limit=2, after=first_page[-1].id)

        assert first_page == rows[:2]
        assert second_page == rows[2:]

    async def test_unknown_cursor_yields_the_first_page(self, session, shop):
        """A cursor to a since-deleted row is not an error; the client gets page one."""
        order = await make_order(session, shop)

        assert await OrdersRepo(session).list(shop.id, after=uuid.uuid4()) == [order]

    async def test_equal_sort_values_break_ties_on_id(self, session, shop):
        same_instant = utc_now_naive()
        rows = [await make_order(session, shop, created_at=same_instant) for _ in range(3)]
        repo = OrdersRepo(session)

        page_one = await repo.list(shop.id, limit=2)
        page_two = await repo.list(shop.id, limit=2, after=page_one[-1].id)

        assert sorted(r.id for r in page_one + page_two) == sorted(r.id for r in rows)
        assert len(page_one + page_two) == 3


class TestUpsert:
    async def test_inserts_when_the_natural_key_is_new(self, session, shop):
        order = await OrdersRepo(session).upsert(
            shop_id=shop.id,
            tiktok_order_id="tt-1",
            status="AWAITING_SHIPMENT",
            total_amount=Decimal("10"),
            currency="VND",
            update_time=utc_now_naive(),
        )

        assert order.id is not None
        assert order.shop_id == shop.id

    async def test_updates_in_place_when_incoming_is_newer(self, session, shop):
        repo = OrdersRepo(session)
        t0 = utc_now_naive()
        first = await repo.upsert(
            shop_id=shop.id,
            tiktok_order_id="tt-1",
            status="AWAITING_SHIPMENT",
            total_amount=Decimal("10"),
            currency="VND",
            update_time=t0,
        )

        second = await repo.upsert(
            shop_id=shop.id,
            tiktok_order_id="tt-1",
            status="SHIPPED",
            total_amount=Decimal("10"),
            currency="VND",
            update_time=t0 + timedelta(seconds=1),
        )

        assert second is first
        assert first.status == "SHIPPED"

    @pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=-5)], ids=["same", "older"])
    async def test_ignores_stale_or_equal_update_time(self, session, shop, delta):
        """A redelivered or out-of-order sync message never rolls a row backwards."""
        repo = OrdersRepo(session)
        t0 = utc_now_naive()
        stored = await repo.upsert(
            shop_id=shop.id,
            tiktok_order_id="tt-1",
            status="SHIPPED",
            total_amount=Decimal("10"),
            currency="VND",
            update_time=t0,
        )

        result = await repo.upsert(
            shop_id=shop.id,
            tiktok_order_id="tt-1",
            status="AWAITING_SHIPMENT",
            total_amount=Decimal("99"),
            currency="VND",
            update_time=t0 + delta,
        )

        assert result is stored
        assert stored.status == "SHIPPED"
        assert stored.total_amount == Decimal("10")

    async def test_same_key_under_two_shops_is_two_rows(self, session, shop):
        _, other_shop = await make_tenant(session)
        repo = OrdersRepo(session)
        common = dict(
            tiktok_order_id="tt-1",
            status="SHIPPED",
            total_amount=Decimal("1"),
            currency="VND",
            update_time=utc_now_naive(),
        )

        mine = await repo.upsert(shop_id=shop.id, **common)
        theirs = await repo.upsert(shop_id=other_shop.id, **common)

        assert mine.id != theirs.id

    async def test_multi_column_natural_key_matches_on_every_column(self, session, shop):
        repo = OrderItemsRepo(session)
        common = dict(
            order_id=uuid.uuid4(),
            tiktok_product_id="p",
            quantity=1,
            unit_price=Decimal("1"),
            line_total=Decimal("1"),
            update_time=utc_now_naive(),
        )

        a = await repo.upsert(shop_id=shop.id, tiktok_order_id="o1", tiktok_sku_id="s1", **common)
        b = await repo.upsert(shop_id=shop.id, tiktok_order_id="o1", tiktok_sku_id="s2", **common)
        a_again = await repo.upsert(
            shop_id=shop.id,
            tiktok_order_id="o1",
            tiktok_sku_id="s1",
            **{**common, "update_time": common["update_time"] + timedelta(seconds=1)},
        )

        assert a is a_again
        assert a.id != b.id

    @pytest.mark.parametrize("missing_value", [None, ""], ids=["none", "empty"])
    async def test_rejects_a_missing_natural_key_column(self, session, shop, missing_value):
        with pytest.raises(
            ValueError, match="requires tiktok_order_id, tiktok_sku_id; missing tiktok_sku_id"
        ):
            await OrderItemsRepo(session).upsert(
                shop_id=shop.id,
                tiktok_order_id="o1",
                tiktok_sku_id=missing_value,
            )

    async def test_repo_without_a_natural_key_refuses_upsert(self, session, shop):
        from juli_backend.repositories import RecommendationsRepo

        with pytest.raises(
            NotImplementedError, match="RecommendationsRepo does not support upsert"
        ):
            await RecommendationsRepo(session).upsert(shop_id=shop.id, title="x")


@pytest.mark.parametrize(
    ("repo_class", "key"),
    [
        (OrdersRepo, ("tiktok_order_id",)),
        (OrderItemsRepo, ("tiktok_order_id", "tiktok_sku_id")),
        (ReturnsRepo, ("tiktok_return_id",)),
        (ProductsRepo, ("tiktok_product_id",)),
    ],
)
def test_natural_keys_are_declared_per_aggregate(repo_class, key):
    """The key is data on the class; ``upsert`` is inherited, never reimplemented."""
    assert repo_class._lookup_attrs == key
    assert "upsert" not in vars(repo_class)
