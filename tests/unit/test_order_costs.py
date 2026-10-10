"""P14-C (D24.13): per-order cost data, read-only.

- the two new GETs are on the production-read allowlist, exact, and nothing else is;
- the parsers turn the documented payloads (``tests/fixtures/tiktok_order_costs``)
  into rows: order-level + per-SKU (line items summed), seller- vs
  platform-funded amounts from the verified fields only, every fee line kept,
  no names or buyer data;
- the store replaces an order's rows idempotently and never crosses shops;
- the poll step fetches only new / changed orders, stops on the rate limiter or
  a vendor 429, stops on a missing scope, counts other errors per order, and
  never raises.

Two-tenant proof under RLS: ``tests/integration/test_order_costs_two_tenant.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from juli_backend.integrations.tiktok import (
    FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE,
    ORDER_PRICE_DETAIL_PATH_TEMPLATE,
    PermissionDeniedError,
    RateLimitError,
    TikTokAPIError,
    TransportGuardError,
)
from juli_backend.integrations.tiktok.constants import (
    finance_order_transactions_path,
    order_price_detail_path,
)
from juli_backend.integrations.tiktok.guards import ReadOnlyTransportGuard
from juli_backend.models.models import Order, Shop, User
from juli_backend.models.order_costs import (
    OrderCostFetch,
    OrderFinanceTransaction,
    OrderPriceDetail,
)
from juli_backend.services import order_costs
from juli_backend.services.order_costs import sync as worker
from tests.support.shop_ingestion_fakes import FakeRateLimiter

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/tiktok_order_costs"
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)

SKU_A = "1729700293904534135"
SKU_B = "1729700293904534999"
PRODUCT_A = "1729700293904403063"
PRODUCT_B = "1729700293904403999"
LINE_SKUS = {
    "577958834469570826": (SKU_A, PRODUCT_A),
    "577958834469570827": (SKU_A, PRODUCT_A),
    "577958834469570828": (SKU_B, PRODUCT_B),
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]["data"]


PRICE = _fixture("price_detail_response.json")
FINANCE = _fixture("statement_transactions_response.json")


def _order_detail(order_id: str) -> dict:
    """``GET /order/202507/orders`` data as TikTok returns it -- buyer data included."""
    return {
        "orders": [
            {
                "id": order_id,
                "buyer_email": "buyer@example.invalid",
                "recipient_address": {"name": "Nguyen Van A", "phone_number": "(+84)900000000"},
                "line_items": [
                    {"id": line, "sku_id": sku, "product_id": product, "product_name": "x"}
                    for line, (sku, product) in LINE_SKUS.items()
                ],
            }
        ]
    }


# -- allowlist ------------------------------------------------------------------------------


def test_both_reads_are_exact_production_read_gets():
    guard = ReadOnlyTransportGuard()
    guard.assert_allowed("GET", order_price_detail_path("576461413038785752"))
    guard.assert_allowed("GET", finance_order_transactions_path("5793990727963214852"))
    for method, path in (
        ("POST", "/order/202407/orders/576461413038785752/price_detail"),
        ("GET", "/order/202309/orders/576461413038785752/price_detail"),
        ("GET", "/order/202407/orders/abc/price_detail"),
        ("PUT", "/finance/202501/orders/5793990727963214852/statement_transactions"),
        ("GET", "/finance/202501/orders/5793990727963214852/statement_transactions/x"),
    ):
        with pytest.raises(TransportGuardError):
            guard.assert_allowed(method, path)


@pytest.mark.parametrize("bad", ["", "12/../34", "1 2", "abc", "12?x=1"])
def test_path_helpers_refuse_a_non_numeric_order_id(bad):
    with pytest.raises(ValueError):
        order_price_detail_path(bad)
    with pytest.raises(ValueError):
        finance_order_transactions_path(bad)


def test_the_endpoints_are_documented():
    text = (ROOT / "docs/integrations/tiktok_api/endpoints.md").read_text(encoding="utf-8")
    assert "GET /order/202407/orders/{order_id}/price_detail" in text
    assert "GET /finance/202501/orders/{order_id}/statement_transactions" in text
    assert ORDER_PRICE_DETAIL_PATH_TEMPLATE == "/order/202407/orders/{order_id}/price_detail"
    assert (
        FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE
        == "/finance/202501/orders/{order_id}/statement_transactions"
    )


# -- parsers --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12.50", Decimal("12.50")),
        ("-30", Decimal("-30")),
        ("1,000", Decimal("1000")),
        ("", None),
        (None, None),
        ("abc", None),
        ("NaN", None),
        (True, None),
        (7, Decimal(7)),
    ],
)
def test_parse_amount(raw, expected):
    assert order_costs.parse_amount(raw) == expected


def test_line_item_skus_reads_ids_only():
    mapping = order_costs.line_item_skus(_order_detail("111"))
    assert mapping == {"111": LINE_SKUS}
    assert "buyer" not in json.dumps(mapping) and "Nguyen" not in json.dumps(mapping)


def test_price_detail_has_an_order_row_and_one_row_per_sku():
    parsed = order_costs.parse_price_detail(PRICE, LINE_SKUS)
    assert parsed.unmapped_line_items == 0
    by_sku = {row.tiktok_sku_id: row for row in parsed.rows}
    assert set(by_sku) == {"", SKU_A, SKU_B}

    order = by_sku[""]
    assert order.currency == "VND" and order.line_item_count == 3
    assert order.amounts["sku_list_price"] == Decimal(500000)
    # Verified fields only: subtotal + shipping deductions; vouchers excluded.
    assert order.seller_funded_amount == Decimal(40000 + 8000)
    assert order.platform_funded_amount == Decimal(20000 + 15000)
    assert order.amounts["voucher_deduction_seller"] == Decimal(1020000)  # stored, unverified

    a = by_sku[SKU_A]  # two line items (one per unit) summed
    assert (a.line_item_count, a.tiktok_product_id) == (2, PRODUCT_A)
    assert a.amounts["sku_list_price"] == Decimal(400000)
    assert a.amounts["sku_sale_price"] == Decimal(360000)
    assert a.seller_funded_amount == Decimal(30000)
    assert a.platform_funded_amount == Decimal(10000)

    b = by_sku[SKU_B]  # empty-string amount -> None, not 0
    assert b.amounts["shipping_fee_deduction_seller"] is None
    assert b.amounts["voucher_deduction_seller"] is None
    assert b.seller_funded_amount == Decimal(10000)


def test_unmapped_line_items_stay_in_the_order_row_only():
    parsed = order_costs.parse_price_detail(PRICE, {})
    assert [row.tiktok_sku_id for row in parsed.rows] == [""]
    assert parsed.unmapped_line_items == 3


def test_statement_transactions_order_row_sku_rows_and_breakdowns():
    parsed = order_costs.parse_statement_transactions(FINANCE)
    assert parsed.settled is True
    assert parsed.order_create_time == datetime(2026, 9, 21, 14, 13, 20)
    rows = {(r.tiktok_sku_id, r.statement_id): r for r in parsed.rows}
    order = rows[("", "")]
    assert order.amounts["fee_tax_amount"] == Decimal(-52800)  # from fee_and_tax_amount
    assert order.amounts["settlement_amount"] == Decimal(380200)

    a = rows[(SKU_A, "7238804564097517339")]
    assert a.quantity == 2
    assert a.amounts["subtotal_before_discount_amount"] == Decimal(400000)
    assert a.amounts["seller_discount_amount"] == Decimal(-40000)
    assert a.amounts["platform_commission_amount"] == Decimal(-28800)
    assert a.amounts["voucher_xtra_service_fee_amount"] == Decimal(-7200)
    assert a.amounts["affiliate_commission_amount"] is None
    assert a.fee_breakdown["fee.transaction_fee_amount"] == "-7200"
    assert a.fee_breakdown["tax.vat_amount"] == "0"
    assert "fee.affiliate_commission_amount" not in a.fee_breakdown
    assert a.shipping_breakdown[
        "supplementary_component.platform_shipping_fee_discount_amount"
    ] == ("15000")
    dumped = json.dumps([r.fee_breakdown | r.shipping_breakdown for r in parsed.rows])
    assert "Test SKU name" not in dumped and "Product name" not in dumped


def test_an_unsettled_order_has_only_its_order_row():
    parsed = order_costs.parse_statement_transactions({"order_id": "1", "sku_transactions": []})
    assert parsed.settled is False and len(parsed.rows) == 1


def test_duplicate_sku_statement_lines_are_summed():
    tx = FINANCE["sku_transactions"][1]
    parsed = order_costs.parse_statement_transactions({"sku_transactions": [tx, tx]})
    row = [r for r in parsed.rows if r.tiktok_sku_id == SKU_B][0]
    assert row.quantity == 2 and row.amounts["revenue_amount"] == Decimal(160000)
    assert row.fee_breakdown["fee.platform_commission_amount"] == "-12800"


# -- store ----------------------------------------------------------------------------------


async def _shop(session, label: str) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8493{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name=f"{label} shop",
        tiktok_shop_id=f"tt-{label}",
        is_active=True,
    )
    session.add_all([user, shop])
    await session.commit()
    return shop


async def _order(
    session, shop, order_id: str, *, status="DELIVERED", days_ago=3, update_offset=0
) -> Order:
    created = NAIVE_NOW - timedelta(days=days_ago)
    order = Order(
        shop_id=shop.id,
        tiktok_order_id=order_id,
        status=status,
        total_amount=Decimal(440000),
        currency="VND",
        tiktok_created_at=created,
        update_time=created + timedelta(minutes=update_offset),
    )
    session.add(order)
    await session.commit()
    return order


async def _count(session, model, shop_id) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(model).where(model.shop_id == shop_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_replacing_an_orders_rows_is_idempotent_and_per_shop(session):
    a, b = await _shop(session, "a"), await _shop(session, "b")
    price = order_costs.parse_price_detail(PRICE, LINE_SKUS)
    finance = order_costs.parse_statement_transactions(FINANCE)
    for _ in range(2):
        await order_costs.replace_price_rows(session, a.id, "900", price, fetched_at=NAIVE_NOW)
        await order_costs.replace_finance_rows(session, a.id, "900", finance, fetched_at=NAIVE_NOW)
        await session.commit()
    assert await _count(session, OrderPriceDetail, a.id) == 3
    assert await _count(session, OrderFinanceTransaction, a.id) == 3

    # Shop B writing the same order id replaces nothing of A's.
    await order_costs.replace_price_rows(
        session, b.id, "900", order_costs.parse_price_detail(PRICE, {}), fetched_at=NAIVE_NOW
    )
    await session.commit()
    assert await _count(session, OrderPriceDetail, a.id) == 3
    assert await _count(session, OrderPriceDetail, b.id) == 1

    deductions = await order_costs.sku_deductions(
        session, a.id, since=NAIVE_NOW - timedelta(days=1)
    )
    assert set(deductions) == {SKU_A, SKU_B}
    assert deductions[SKU_A].units == 2 and deductions[SKU_A].orders == 1
    assert deductions[SKU_A].seller_funded_amount == Decimal(30000)
    assert (
        await order_costs.sku_deductions(session, b.id, since=NAIVE_NOW - timedelta(days=1)) == {}
    )


@pytest.mark.asyncio
async def test_work_lists_window_status_and_change_detection(session):
    shop = await _shop(session, "w")
    other = await _shop(session, "x")
    await _order(session, shop, "1", status="DELIVERED")
    await _order(session, shop, "2", status="AWAITING_SHIPMENT")
    await _order(session, shop, "3", status="CANCELLED")
    await _order(session, shop, "4", status="UNPAID")
    await _order(session, shop, "5", status="COMPLETED", days_ago=61)
    await _order(session, other, "6", status="DELIVERED")

    price = await order_costs.orders_needing_price(session, shop.id, now=NAIVE_NOW, limit=10)
    assert [r.tiktok_order_id for r in price] == ["1", "2"]
    finance = await order_costs.orders_needing_finance(session, shop.id, now=NAIVE_NOW, limit=10)
    assert [r.tiktok_order_id for r in finance] == ["1"]

    await order_costs.record_price_fetch(
        session, shop.id, "1", order_update_time=price[0].update_time, fetched_at=NAIVE_NOW
    )
    await order_costs.record_finance_fetch(
        session, shop.id, "1", settled=False, fetched_at=NAIVE_NOW
    )
    await session.commit()
    price = await order_costs.orders_needing_price(session, shop.id, now=NAIVE_NOW, limit=10)
    assert [r.tiktok_order_id for r in price] == ["2"]
    # Not settled: asked again only after a day.
    assert await order_costs.orders_needing_finance(session, shop.id, now=NAIVE_NOW, limit=10) == []
    later = NAIVE_NOW + order_costs.FINANCE_RECHECK
    assert [
        r.tiktok_order_id
        for r in await order_costs.orders_needing_finance(session, shop.id, now=later, limit=10)
    ] == ["1"]

    # A later update_time (a refund, say) makes the price detail due again.
    order = (await session.execute(select(Order).where(Order.tiktok_order_id == "1"))).scalar_one()
    order.update_time = order.update_time + timedelta(hours=2)
    await session.commit()
    price = await order_costs.orders_needing_price(session, shop.id, now=NAIVE_NOW, limit=10)
    assert [r.tiktok_order_id for r in price] == ["1", "2"]


# -- the poll step --------------------------------------------------------------------------


class FakeOrderCosts:
    def __init__(self, *, price=None, finance=None):
        self.price_calls: list[str] = []
        self.finance_calls: list[str] = []
        self.price = price or (lambda oid: PRICE)
        self.finance = finance or (lambda oid: FINANCE)

    def get_price_detail(self, order_id):
        self.price_calls.append(order_id)
        return self.price(order_id)

    def get_statement_transactions(self, order_id):
        self.finance_calls.append(order_id)
        return self.finance(order_id)


class FakeOrders:
    def __init__(self):
        self.detail_calls: list[list[str]] = []

    def get_details(self, ids):
        self.detail_calls.append(list(ids))
        orders = []
        for oid in ids:
            orders.extend(_order_detail(oid)["orders"])
        return {"orders": orders}


def _resources(costs: FakeOrderCosts | None = None, orders: FakeOrders | None = None):
    return SimpleNamespace(order_costs=costs or FakeOrderCosts(), orders=orders or FakeOrders())


async def _no_sleep(_seconds: float) -> None:
    return None


async def _sync(session, shop, resources, *, limiter=None, **kwargs):
    kwargs.setdefault("sleep", _no_sleep)
    return await worker.sync_order_costs(
        session=session,
        shop_id=shop.id,
        resources=resources,
        rate_limiter=limiter or FakeRateLimiter(),
        app_id="app",
        shop_key=shop.tiktok_shop_id,
        now=NOW,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_a_cycle_reads_new_orders_once_and_stores_amounts_only(session):
    shop = await _shop(session, "c")
    await _order(session, shop, "101")
    await _order(session, shop, "102", status="AWAITING_SHIPMENT")
    resources = _resources()

    result = await _sync(session, shop, resources)
    assert (result.price.fetched, result.finance.fetched) == (2, 1)
    assert resources.orders.detail_calls == [["101", "102"]]
    assert sorted(resources.order_costs.price_calls) == ["101", "102"]
    assert resources.order_costs.finance_calls == ["101"]
    assert await _count(session, OrderPriceDetail, shop.id) == 6
    assert await _count(session, OrderFinanceTransaction, shop.id) == 3
    fetch = (
        await session.execute(select(OrderCostFetch).where(OrderCostFetch.tiktok_order_id == "101"))
    ).scalar_one()
    assert fetch.finance_settled is True and fetch.price_fetched_at == NAIVE_NOW

    # No buyer data and no names anywhere in what was stored.
    for model in (OrderPriceDetail, OrderFinanceTransaction, OrderCostFetch):
        rows = (await session.execute(select(model))).scalars().all()
        dumped = json.dumps(
            [{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in rows],
            default=str,
        )
        for needle in ("buyer", "Nguyen", "+84", "Test SKU name", "Product name"):
            assert needle not in dumped, (model.__tablename__, needle)

    # Second cycle: nothing new, no vendor call.
    again = await _sync(session, shop, resources)
    assert (again.price.candidates, again.finance.candidates) == (0, 0)
    assert len(resources.order_costs.price_calls) == 2
    assert len(resources.orders.detail_calls) == 1


@pytest.mark.asyncio
async def test_the_rate_limiter_bounds_the_cycle(session):
    shop = await _shop(session, "rl")
    for i in range(4):
        await _order(session, shop, f"20{i}")
    limiter = FakeRateLimiter(limit=2)
    resources = _resources()
    result = await _sync(session, shop, resources, limiter=limiter, finance_limit=0)
    assert result.price.rate_limited and result.price.fetched == 2
    assert limiter.counts[ORDER_PRICE_DETAIL_PATH_TEMPLATE] == 2

    # The next cycle continues where this one stopped.
    limiter.refuse.add(FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE)
    limiter.reset()
    result = await _sync(session, shop, resources, limiter=limiter)
    assert result.price.fetched == 2 and len(set(resources.order_costs.price_calls)) == 4
    assert result.finance.rate_limited and result.finance.fetched == 0
    assert resources.order_costs.finance_calls == []


@pytest.mark.asyncio
async def test_a_vendor_429_stops_the_pass_without_counting_an_error(session):
    shop = await _shop(session, "429")
    await _order(session, shop, "301")
    await _order(session, shop, "302", days_ago=4)

    def throttled(_oid):
        raise RateLimitError(36009004, "too many requests")

    resources = _resources(FakeOrderCosts(price=throttled))
    result = await _sync(session, shop, resources, finance_limit=0)
    assert result.price.rate_limited and result.price.errors == 0
    assert resources.order_costs.price_calls == ["301"]
    assert await _count(session, OrderCostFetch, shop.id) == 0


@pytest.mark.asyncio
async def test_a_missing_finance_scope_stops_the_finance_pass(session):
    shop = await _shop(session, "scope")
    await _order(session, shop, "401")
    await _order(session, shop, "402", days_ago=4)

    def denied(_oid):
        raise PermissionDeniedError(105005, "scope seller.finance.info not granted")

    resources = _resources(FakeOrderCosts(finance=denied))
    result = await _sync(session, shop, resources)
    assert result.price.fetched == 2
    assert result.finance.permission_denied and resources.order_costs.finance_calls == ["401"]
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_other_vendor_errors_are_counted_per_order_and_retried_then_dropped(session):
    shop = await _shop(session, "err")
    await _order(session, shop, "501")

    def broken(_oid):
        raise TikTokAPIError(21008111, "The order does not belong to the seller")

    resources = _resources(FakeOrderCosts(price=broken))
    for attempt in range(1, order_costs.MAX_ATTEMPTS + 1):
        result = await _sync(session, shop, resources, finance_limit=0)
        assert result.price.errors == 1
        fetch = (
            await session.execute(
                select(OrderCostFetch).where(OrderCostFetch.tiktok_order_id == "501")
            )
        ).scalar_one()
        await session.refresh(fetch)
        assert fetch.price_attempts == attempt
        assert fetch.last_error == "price: TikTokAPIError code=21008111"
    result = await _sync(session, shop, resources, finance_limit=0)
    assert result.price.candidates == 0, "given up after MAX_ATTEMPTS"


@pytest.mark.asyncio
async def test_a_failed_sku_lookup_skips_the_price_pass(session):
    shop = await _shop(session, "lookup")
    await _order(session, shop, "601")

    class BrokenOrders(FakeOrders):
        def get_details(self, ids):
            raise TikTokAPIError(36009003, "internal")

    resources = _resources(orders=BrokenOrders())
    result = await _sync(session, shop, resources, finance_limit=0)
    assert result.price.fetched == 0 and resources.order_costs.price_calls == []
    assert await _count(session, OrderCostFetch, shop.id) == 0


@pytest.mark.asyncio
async def test_an_unexpected_error_never_escapes(session, monkeypatch):
    shop = await _shop(session, "boom")
    await _order(session, shop, "701")

    async def explode(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker.order_costs_store, "replace_price_rows", explode)
    result = await _sync(session, shop, _resources())
    assert result.skipped_reason == "error"


@pytest.mark.asyncio
async def test_switched_off_or_without_the_resource_it_does_nothing(session, monkeypatch):
    shop = await _shop(session, "off")
    await _order(session, shop, "801")
    monkeypatch.setenv(worker.ENABLED_ENV, "0")
    resources = _resources()
    assert (await _sync(session, shop, resources)).skipped_reason == "disabled"
    assert resources.order_costs.price_calls == []
    monkeypatch.delenv(worker.ENABLED_ENV)
    bare = SimpleNamespace(orders=FakeOrders())
    assert (await _sync(session, shop, bare)).skipped_reason == "no_resource"


def test_per_cycle_limits_come_from_the_environment(monkeypatch):
    assert worker.price_per_cycle() == worker.DEFAULT_PER_CYCLE
    monkeypatch.setenv(worker.PRICE_PER_CYCLE_ENV, "25")
    monkeypatch.setenv(worker.FINANCE_PER_CYCLE_ENV, "junk")
    assert worker.price_per_cycle() == 25
    assert worker.finance_per_cycle() == worker.DEFAULT_PER_CYCLE


# -- migration ------------------------------------------------------------------------------


MIGRATIONS = ROOT / "backend/src/juli_backend/database/migrations"


def test_migration_081_chains_after_080_and_the_cleanup_stays_last():
    text = (MIGRATIONS / "versions/081_order_cost_data.py").read_text(encoding="utf-8")
    assert 'revision: str = "081_order_cost_data"' in text
    assert 'down_revision: str | None = "080_lever_flows"' in text
    assert len("081_order_cost_data") <= 32
    deferred = (MIGRATIONS / "deferred/074_users_placeholder_phone_cleanup.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "081_order_cost_data"' in deferred


def test_the_new_tables_are_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    for table in ("order_price_details", "order_finance_transactions", "order_cost_fetches"):
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"


def test_the_migration_creates_every_model_column():
    from juli_backend.models.order_costs import OrderCostFetch as Fetch

    text = (MIGRATIONS / "versions/081_order_cost_data.py").read_text(encoding="utf-8")
    for model in (OrderPriceDetail, OrderFinanceTransaction, Fetch):
        assert f'"{model.__tablename__}"' in text
        for column in model.__table__.columns.keys():
            assert f'"{column}"' in text, (model.__tablename__, column)
    assert "ENABLE ROW LEVEL SECURITY" in text and "app_current_shop_id()" in text


# -- P17: a fast tier for the orders of the last 30 days --------------------------------------


class _WindowLimiter(FakeRateLimiter):
    """``limit`` tokens per endpoint per window; every awaited sleep opens a new window."""

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.reset()

    def __init__(self, *, limit: int) -> None:
        super().__init__(limit=limit)
        self.slept: list[float] = []


async def _orders(session, shop, prefix: str, count: int, *, days_ago: int) -> None:
    for i in range(count):
        await _order(
            session, shop, f"{prefix}{i:03d}", status="AWAITING_SHIPMENT", days_ago=days_ago
        )


@pytest.mark.asyncio
async def test_recent_orders_read_up_to_sixty_a_cycle_before_older_ones_at_ten(session):
    shop = await _shop(session, "fast")
    await _orders(session, shop, "7", 70, days_ago=5)
    await _orders(session, shop, "8", 15, days_ago=40)
    resources = _resources()

    result = await _sync(session, shop, resources, finance_limit=0)

    assert result.price.fetched == 70 and result.price.fetched_recent == 60
    calls = resources.order_costs.price_calls
    assert sum(1 for c in calls if c.startswith("7")) == 60
    assert sum(1 for c in calls if c.startswith("8")) == 10
    # Fast tier first.
    assert all(c.startswith("7") for c in calls[:60])

    # Next cycle: the 10 recent left, then 5 older.
    again = await _sync(session, shop, resources, finance_limit=0)
    assert again.price.fetched == 15 and again.price.fetched_recent == 10


@pytest.mark.asyncio
async def test_the_fast_tier_waits_for_the_window_instead_of_stopping(session):
    shop = await _shop(session, "wait")
    await _orders(session, shop, "6", 25, days_ago=2)
    limiter = _WindowLimiter(limit=10)
    resources = _resources()

    result = await _sync(
        session, shop, resources, limiter=limiter, finance_limit=0, sleep=limiter.sleep
    )

    assert result.price.fetched == 25 and not result.price.rate_limited
    assert limiter.slept and result.price.waited_seconds == sum(limiter.slept)
    assert all(s <= worker.TOKEN_POLL_SECONDS for s in limiter.slept)


@pytest.mark.asyncio
async def test_the_wait_budget_bounds_the_cycle_and_older_orders_never_wait(session):
    shop = await _shop(session, "budget")
    await _orders(session, shop, "5", 30, days_ago=2)
    limiter = FakeRateLimiter(limit=10)  # never refills
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    result = await _sync(
        session, shop, _resources(), limiter=limiter, finance_limit=0, sleep=sleep, max_wait=30
    )
    # 10 price reads (the SKU lookup has its own bucket), then 30 s of waiting and stop.
    assert result.price.rate_limited and result.price.fetched == 10
    assert sum(slept) == 30 and result.price.waited_seconds == 30

    shop_old = await _shop(session, "old")
    await _orders(session, shop_old, "4", 12, days_ago=45)
    slept.clear()
    old = await _sync(
        session,
        shop_old,
        _resources(),
        limiter=FakeRateLimiter(limit=5),
        finance_limit=0,
        sleep=sleep,
    )
    assert old.price.rate_limited and old.price.fetched == 5 and slept == []


@pytest.mark.asyncio
async def test_a_429_in_the_fast_tier_still_stops_at_once(session):
    shop = await _shop(session, "fast429")
    await _orders(session, shop, "3", 5, days_ago=1)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    def throttled(_oid):
        raise RateLimitError(36009004, "too many requests")

    resources = _resources(FakeOrderCosts(price=throttled))
    result = await _sync(session, shop, resources, finance_limit=0, sleep=sleep)
    assert result.price.rate_limited and len(resources.order_costs.price_calls) == 1
    assert slept == []


def test_fast_tier_settings_come_from_the_environment(monkeypatch):
    assert (worker.fast_window_days(), worker.fast_per_cycle()) == (30, 60)
    assert worker.max_wait_seconds() == 600.0
    monkeypatch.setenv(worker.FAST_WINDOW_DAYS_ENV, "14")
    monkeypatch.setenv(worker.FAST_PER_CYCLE_ENV, "40")
    monkeypatch.setenv(worker.MAX_WAIT_SECONDS_ENV, "junk")
    assert (worker.fast_window_days(), worker.fast_per_cycle()) == (14, 40)
    assert worker.max_wait_seconds() == 600.0
