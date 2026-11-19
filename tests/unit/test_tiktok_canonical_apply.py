"""P101 W2 t1: TikTok raw -> canonical (``services/ingest/tiktok_canonical``), SQLite.

S-1 same-job lines, S-2 the 9 statuses through returns + settlements from finance rows, S-3
re-run / rank, S-4 late change touches its day only + reconcile, S-6 no buyer PII. Synthetic
payloads in the TikTok shapes (order search 202309, return search 202309, finance 202501); no
real shop, order or amount."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.models import BronzeOrderRawPayload, Order, Return
from juli_backend.models.order_costs import ORDER_LEVEL, OrderFinanceTransaction
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest import tiktok_canonical as tc
from juli_backend.services.ingest.canonical import OrderLine, day_of
from juli_backend.services.ingest.canonical_writer import DbCanonicalWriter
from tests.support.builders import make_tenant

D = Decimal
CREATED = 1_790_000_000  # 2026-09-21 14:13:20 UTC = 21:13 VN
DAY = date(2026, 9, 21)
NOW = datetime(2026, 9, 30, 2, 0, tzinfo=UTC)


def _order(order_id: str = "900000000000000001", **over: Any) -> dict[str, Any]:
    order: dict[str, Any] = {
        "id": order_id,
        "status": "COMPLETED",
        "create_time": CREATED,
        "update_time": CREATED + 3600,
        "paid_time": CREATED + 60,
        "delivery_time": CREATED + 86_400,
        "payment": {"currency": "VND", "shipping_fee": "20000"},
        "recipient_address": {"name": "PII_MARKER_name", "phone_number": "PII_MARKER_phone"},
        "buyer_email": "PII_MARKER_mail",
        "buyer_message": "PII_MARKER_msg",
        "user_id": "PII_MARKER_user",
        "line_items": [
            {
                "id": f"{order_id}1",
                "product_id": "700000000000000001",
                "sku_id": "600000000000000001",
                "sku_name": "Do / M",
                "seller_sku": "SYN-A",
                "original_price": "200000",
                "sale_price": "170000",
                "seller_discount": "20000",
                "platform_discount": "10000",
                "currency": "VND",
                "display_status": "COMPLETED",
            },
            {
                "id": f"{order_id}2",
                "product_id": "700000000000000002",
                "sku_id": "600000000000000002",
                "sku_name": "Xanh / L",
                "seller_sku": "SYN-B",
                "original_price": "100000",
                "sale_price": "90000",
                "seller_discount": "10000",
                "platform_discount": "0",
                "currency": "VND",
                "display_status": "COMPLETED",
            },
        ],
    }
    order.update(over)
    return order


def _return(order_id: str, status: str, *, sku: str = "600000000000000001", at: int = 0) -> dict:
    return {
        "return_id": f"r{order_id}{sku[-1]}",
        "order_id": order_id,
        "return_status": status,
        "update_time": CREATED + 7200 + at,
        "return_line_items": [{"order_line_item_id": f"{order_id}1", "sku_id": sku}],
    }


async def _lines(session) -> list[ShopeeOrderLine]:
    stmt = select(ShopeeOrderLine).execution_options(populate_existing=True)
    return sorted((await session.execute(stmt)).scalars(), key=lambda r: (r.order_ref, r.line_no))


async def _settlements(session) -> list[ShopeeOrderIncome]:
    stmt = select(ShopeeOrderIncome).execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars())


def _columns(row) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key != "updated_at"}


class _Days:
    def __init__(self) -> None:
        self.calls: list[frozenset[date]] = []

    async def __call__(self, session, shop_id, days) -> None:
        self.calls.append(days)

    @property
    def touched(self) -> set[date]:
        return set().union(*self.calls) if self.calls else set()


async def _silver_return(session, shop, order_id: str, sku: str, status: str) -> None:
    session.add(
        Return(
            shop_id=shop.id,
            tiktok_return_id=f"r-{order_id}-{sku}",
            tiktok_order_id=order_id,
            tiktok_sku_id=sku,
            return_type="RETURN_AND_REFUND",
            refund_amount=D("0"),
            status=status,
            update_time=datetime(2026, 9, 22, 1, 0),
        )
    )
    await session.flush()


async def _finance(session, shop, order_id: str, *, fetched_at: datetime) -> None:
    created = datetime(2026, 9, 21, 14, 13, 20)
    session.add_all(
        [
            OrderFinanceTransaction(
                shop_id=shop.id,
                tiktok_order_id=order_id,
                tiktok_sku_id=ORDER_LEVEL,
                statement_id=ORDER_LEVEL,
                currency="VND",
                settlement_amount=D("190000"),
                shipping_cost_amount=D("-5000"),
                order_create_time=created,
                fetched_at=fetched_at,
            ),
            OrderFinanceTransaction(
                shop_id=shop.id,
                tiktok_order_id=order_id,
                tiktok_sku_id="600000000000000001",
                statement_id="st-1",
                currency="VND",
                quantity=1,
                settlement_amount=D("190000"),
                subtotal_before_discount_amount=D("200000"),
                fee_breakdown={
                    "fee.platform_commission_amount": "-10000",
                    "fee.transaction_fee_amount": "-2000",
                    "fee.sfp_service_fee_amount": "-1500",
                    "tax.vat_amount": "-1000",
                },
                shipping_breakdown={
                    "actual_shipping_fee_amount": "-25000",
                    "customer_paid_shipping_fee_amount": "20000",
                },
                order_create_time=created,
                fetched_at=fetched_at,
            ),
        ]
    )
    await session.flush()


# -- S-1 / S-6 ------------------------------------------------------------------------------


async def test_the_orders_a_job_fetched_land_as_canonical_lines_in_that_job(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    days = _Days()
    sync = tc.TikTokCanonicalSync(session, shop.id, days_fn=days)

    applied = await sync.on_orders([_order()])

    lines = await _lines(session)
    assert [(r.platform, r.order_ref, r.line_no, r.status) for r in lines] == [
        ("tiktok", "900000000000000001", 0, "delivered"),
        ("tiktok", "900000000000000001", 1, "delivered"),
    ]
    assert {(r.source, r.source_rank, r.day) for r in lines} == {("api", 4, DAY)}
    assert (applied.orders, applied.lines_written, applied.days) == (1, 2, {DAY})
    assert days.touched == {DAY}


async def test_no_buyer_field_reaches_a_canonical_row(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    await tc.apply_orders(session, shop.id, [_order()], days_fn=_Days())

    stored = [str(v) for row in await _lines(session) for v in _columns(row).values()]
    assert stored and not [v for v in stored if "PII_MARKER" in v]
    assert {c.key for c in ShopeeOrderLine.__table__.columns}.isdisjoint(
        {"buyer_id", "buyer_name", "buyer_email", "recipient_address", "phone"}
    )


# -- S-2: the nine statuses -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("order_status", "return_status", "expected"),
    [
        ("UNPAID", None, "pending"),
        ("AWAITING_SHIPMENT", None, "confirmed"),
        ("IN_TRANSIT", None, "in_transit"),
        ("COMPLETED", None, "delivered"),
        ("CANCELLED", None, "cancelled"),
        ("ON_HOLD", None, "on_hold"),
        ("COMPLETED", "AWAITING_BUYER_SHIP", "refunded_accepted"),
        ("COMPLETED", "BUYER_SHIPPED_ITEM", "refunded_not_received"),
        ("COMPLETED", "RETURN_OR_REFUND_REQUEST_COMPLETE", "returned"),
    ],
)
async def test_each_of_the_nine_statuses_lands_from_the_landed_returns(
    session, order_status: str, return_status: str | None, expected: str
) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    if return_status is not None:
        await _silver_return(
            session, shop, "900000000000000001", "600000000000000001", return_status
        )
    paid = {} if order_status == "UNPAID" else {"paid_time": CREATED + 60}
    order = _order(status=order_status, **paid)
    if order_status == "UNPAID":
        order.pop("paid_time")

    await tc.apply_orders(session, shop.id, [order], days_fn=_Days())

    first, second = await _lines(session)
    assert first.status == expected
    # a return names one line: the other keeps the order's status
    assert second.status == (expected if return_status is None else "delivered")


async def test_a_return_this_job_fetched_re_maps_its_held_order_and_refetches_the_rest(
    session,
) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    sync = tc.TikTokCanonicalSync(session, shop.id, days_fn=_Days())
    await sync.on_orders([_order("900000000000000001")])
    asked: list[list[str]] = []

    def fetch(ids: list[str]) -> list[dict]:
        asked.append(ids)
        return [_order(i) for i in ids]

    await sync.on_returns(
        [
            _return("900000000000000001", "RETURN_OR_REFUND_REQUEST_COMPLETE"),
            _return("900000000000000002", "BUYER_SHIPPED_ITEM"),
        ]
    )
    await sync.finish(fetch_details=fetch)

    assert asked == [["900000000000000002"]]
    by_ref = {(r.order_ref, r.line_no): r.status for r in await _lines(session)}
    assert by_ref == {
        ("900000000000000001", 0): "returned",
        ("900000000000000001", 1): "delivered",
        ("900000000000000002", 0): "refunded_not_received",
        ("900000000000000002", 1): "delivered",
    }


async def test_settlements_map_from_the_finance_rows_read_since_the_job_started(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    started = datetime(2026, 9, 30, 1, 0)
    await _finance(session, shop, "900000000000000001", fetched_at=datetime(2026, 9, 30, 1, 5))
    await _finance(session, shop, "900000000000000009", fetched_at=datetime(2026, 9, 29, 1, 5))
    days = _Days()
    sync = tc.TikTokCanonicalSync(session, shop.id, days_fn=days)

    result = await sync.finish(settled_since=started)

    (row,) = await _settlements(session)
    assert (row.platform, row.order_ref, row.source, row.source_rank) == (
        "tiktok",
        "900000000000000001",
        "api",
        4,
    )
    assert (row.payout, row.fee_fixed, row.fee_payment, row.fee_other) == (
        D("190000"),
        D("10000"),
        D("2000"),
        D("1500"),
    )
    assert (row.ship_actual_cost, row.ship_buyer_paid, row.product_price) == (
        D("25000"),
        D("20000"),
        D("200000"),
    )
    assert row.vat_withheld == D("1000")  # stored as reported, never a cost
    assert row.ordered_on == DAY
    assert (result.settlements_written, days.touched) == (1, {DAY})


async def test_an_order_mapped_with_its_finance_rows_writes_its_settlement(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    await _finance(session, shop, "900000000000000001", fetched_at=datetime(2026, 9, 30, 1, 5))

    result = await tc.apply_orders(session, shop.id, [_order()], days_fn=_Days())

    assert (result.lines_written, result.settlements_written) == (2, 1)
    assert [r.order_ref for r in await _settlements(session)] == ["900000000000000001"]


# -- S-3 ------------------------------------------------------------------------------------


async def test_a_rerun_of_the_same_window_writes_nothing_and_touches_no_day(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    await _finance(session, shop, "900000000000000001", fetched_at=datetime(2026, 9, 30, 1, 5))
    orders = [_order("900000000000000001"), _order("900000000000000002", status="IN_TRANSIT")]
    await tc.apply_orders(session, shop.id, orders, days_fn=_Days())
    before = (
        [_columns(r) for r in await _lines(session)],
        [_columns(r) for r in await _settlements(session)],
    )
    days = _Days()

    again = await tc.apply_orders(session, shop.id, orders, days_fn=days)
    settled = await tc.apply_settlements(
        session, shop.id, fetched_since=datetime(2026, 9, 30), days_fn=days
    )

    assert (again.lines_written, again.settlements_written, settled.settlements_written) == (
        0,
        0,
        0,
    )
    assert days.touched == set()
    after = (
        [_columns(r) for r in await _lines(session)],
        [_columns(r) for r in await _settlements(session)],
    )
    assert after == before
    assert (len(after[0]), len(after[1])) == (4, 1)


async def test_a_lower_ranked_post_never_overwrites_the_tiktok_api_row(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    await tc.apply_orders(session, shop.id, [_order()], days_fn=_Days())
    (api_line, _) = await _lines(session)
    connector = OrderLine(
        shop_id=shop.id,
        platform="tiktok",
        order_ref=api_line.order_ref,
        line_no=0,
        ordered_at=api_line.ordered_at,
        status="cancelled",
        item_id="x",
        variation_id="y",
        qty=1,
        original_price=D("1"),
        deal_price=D("1"),
        fee_fixed=D("9000"),
        source="extension",
        source_version="connector:test",
    )

    written = await DbCanonicalWriter(session).upsert_order_lines(shop.id, "tiktok", [connector])

    stored, _ = await _lines(session)
    assert (stored.status, stored.source, stored.deal_price) == ("delivered", "api", D("180000"))
    assert stored.fee_fixed == D("9000")  # a lower rank only fills a NULL column
    assert written == 1


# -- S-4 ------------------------------------------------------------------------------------


async def test_a_late_cancel_marks_only_the_day_of_its_order(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    other_created = CREATED + 5 * 86_400
    orders = [_order("900000000000000001"), _order("900000000000000002", create_time=other_created)]
    await tc.apply_orders(session, shop.id, orders, days_fn=_Days())
    days = _Days()

    late = [_order("900000000000000001", status="CANCELLED"), orders[1]]
    result = await tc.apply_orders(session, shop.id, late, days_fn=days)

    assert days.calls == [frozenset({DAY})]
    assert (result.lines_written, result.days) == (2, {DAY})
    assert {r.order_ref: r.status for r in await _lines(session)}["900000000000000002"] == (
        "delivered"
    )


async def test_the_day_hook_is_called_per_run_of_consecutive_days(session, monkeypatch) -> None:
    from juli_backend.services.shopee_analytics import materialize

    _, shop = await make_tenant(session, platform="tiktok")
    calls: list[tuple[str, str, date, date]] = []

    async def hook(session, shop_id, *, platform, dataset, start, end) -> None:
        calls.append((platform, dataset, start, end))

    monkeypatch.setattr(materialize, "after_ingest", hook)
    days = frozenset({date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 5)})

    await tc.record_touched_days(session, shop.id, days)

    assert calls == [
        ("tiktok", "order_lines", date(2026, 9, 1), date(2026, 9, 2)),
        ("tiktok", "order_lines", date(2026, 9, 5), date(2026, 9, 5)),
    ]


async def test_reconcile_remaps_from_bronze_queues_the_rest_and_fills_settlements(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    created = datetime(2026, 9, 21, 14, 13, 20)
    for order_id, at in (
        ("900000000000000001", created),
        ("900000000000000002", created),
        ("900000000000000003", created + timedelta(days=1)),
        ("900000000000000004", created + timedelta(days=1)),
    ):
        session.add(
            Order(
                shop_id=shop.id,
                tiktok_order_id=order_id,
                status="COMPLETED",
                total_amount=D("1"),
                currency="VND",
                tiktok_created_at=at,
                update_time=at,
            )
        )
    session.add(
        BronzeOrderRawPayload(
            shop_id=shop.id,
            ingest_source="targeted_fetch",
            payload=_order("900000000000000002"),
            tiktok_order_id="900000000000000002",
            received_at=datetime(2026, 9, 22, 1, 0),
        )
    )
    session.add(
        BronzeOrderRawPayload(  # a webhook payload: no line items, never used
            shop_id=shop.id,
            ingest_source="webhook",
            payload={"order_id": "900000000000000003", "order_status": "CANCELLED"},
            tiktok_order_id="900000000000000003",
            received_at=datetime(2026, 9, 23, 1, 0),
        )
    )
    await session.flush()
    await _finance(session, shop, "900000000000000001", fetched_at=datetime(2026, 9, 30, 1, 5))
    await tc.apply_orders(
        session, shop.id, [_order("900000000000000001")], days_fn=_Days()
    )  # settlement too
    await session.execute(ShopeeOrderIncome.__table__.delete())
    queue = tc.InMemoryRefetchQueue()

    result = await tc.reconcile_shop(
        session, shop.id, start=DAY, end=DAY + timedelta(days=1), queue=queue, days_fn=_Days()
    )

    assert (result.raw_orders, result.canonical_orders) == (4, 1)
    assert result.gap_days == {DAY: (2, 1), DAY + timedelta(days=1): (2, 0)}
    assert (result.remapped, result.queued, result.settlements_written) == (1, 2, 1)
    assert queue.ids[shop.id] == {"900000000000000003", "900000000000000004"}
    assert {r.order_ref for r in await _lines(session)} == {
        "900000000000000001",
        "900000000000000002",
    }
    assert [r.order_ref for r in await _settlements(session)] == ["900000000000000001"]


async def test_finish_refetches_queued_ids_at_most_fifty_per_call(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    queue = tc.InMemoryRefetchQueue()
    ids = [f"9{n:017d}" for n in range(120)]
    queue.push(shop.id, ids)
    asked: list[int] = []

    def fetch(batch: list[str]) -> list[dict]:
        asked.append(len(batch))
        return [_order(i) for i in batch]

    sync = tc.TikTokCanonicalSync(session, shop.id, days_fn=_Days())
    result = await sync.finish(fetch_details=fetch, queue=queue, refetch_limit=110)

    assert asked == [50, 50, 10]
    assert result.orders == 110 and len(queue.ids[shop.id]) == 10
    assert len({r.order_ref for r in await _lines(session)}) == 110


async def test_a_failed_refetch_puts_the_unfetched_ids_back(session) -> None:
    _, shop = await make_tenant(session, platform="tiktok")
    queue = tc.InMemoryRefetchQueue()
    queue.push(shop.id, ["900000000000000001"])

    def fetch(batch: list[str]) -> list[dict]:
        raise RuntimeError("vendor down")

    sync = tc.TikTokCanonicalSync(session, shop.id, days_fn=_Days())
    await sync.finish(fetch_details=fetch, queue=queue, fetch_errors=(RuntimeError,))

    assert queue.ids[shop.id] == {"900000000000000001"}
    assert await _lines(session) == []


# -- small parts ----------------------------------------------------------------------------


def test_return_statuses_take_the_latest_per_line() -> None:
    statuses = tc.return_statuses_of(
        [
            _return("1", "AWAITING_BUYER_SHIP", at=0),
            _return("1", "RETURN_OR_REFUND_REQUEST_COMPLETE", at=10),
            {"order_id": "2", "return_status": "BUYER_SHIPPED_ITEM", "sku_id": "s2"},
            {"order_id": "3"},
        ]
    )
    assert statuses == {
        "1": {
            "11": "RETURN_OR_REFUND_REQUEST_COMPLETE",
            "600000000000000001": ("RETURN_OR_REFUND_REQUEST_COMPLETE"),
        },
        "2": {"s2": "BUYER_SHIPPED_ITEM"},
    }


def test_the_kill_switch_and_the_connect_window(monkeypatch) -> None:
    monkeypatch.delenv(tc.ENABLED_ENV, raising=False)
    assert tc.enabled() is True
    monkeypatch.setenv(tc.ENABLED_ENV, "0")
    assert tc.enabled() is False

    start = tc.connect_window_start(
        90, datetime(2026, 11, 19, 18, 30, tzinfo=UTC)
    )  # 01:30 VN 20/11
    assert start == datetime(2026, 8, 22, 17, 0, tzinfo=UTC)  # 00:00 VN 23/08
    assert day_of(start) == date(2026, 8, 23)
    assert (date(2026, 11, 20) - day_of(start)).days + 1 == 90


def test_the_redis_queue_adds_once_and_pops_at_most_the_limit() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.sets: dict[str, set[bytes]] = {}
            self.ttl: dict[str, int] = {}

        def sadd(self, key, *values):
            bucket = self.sets.setdefault(key, set())
            new = {v.encode() for v in values} - bucket
            bucket |= new
            return len(new)

        def expire(self, key, seconds):
            self.ttl[key] = seconds

        def spop(self, key, count):
            bucket = self.sets.get(key, set())
            out = sorted(bucket)[:count]
            bucket.difference_update(out)
            return out

    shop_id = uuid.uuid4()
    redis = FakeRedis()
    queue = tc.RedisRefetchQueue(redis)

    assert queue.push(shop_id, ["b", "a", "a"]) == 2
    assert queue.push(shop_id, ["a"]) == 0
    assert redis.ttl[queue.key(shop_id)] == 7 * 24 * 3600
    assert queue.pop(shop_id, 1) == ["a"]
    assert queue.pop(shop_id, 5) == ["b"]
    assert queue.pop(shop_id, 0) == []
