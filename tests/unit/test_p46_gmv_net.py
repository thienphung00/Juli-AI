"""D55.1 (fast track P46, Ops only): group-verdict money metrics net of cancelled /
refunded orders.

- TikTok's GMV includes orders later cancelled or refunded. When the shop's own orders
  (``silver.orders`` + ``order_items`` + ``silver.returns``) cover the days a verdict
  reads, all-channel AOV and items per order are read net (each analytics day scaled
  by that day's cancel / refund share), with the TikTok-GMV reading stored beside it.
- An Ops group's money primary is net; a card group's primary -- behind the seller's
  "Kết quả nhóm" sentence -- stays on TikTok's GMV, its net reading under ``net``.
- Without the orders, every Ops label says "gồm đơn huỷ/hoàn, theo TikTok".

Synthetic fixtures only (no shop data).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio

from juli_backend.models.card_groups import ARM_TREATED, CardGroup, CardGroupMember
from juli_backend.models.models import AnalyticsPerformanceInterval, Order, OrderItem, Return
from juli_backend.services.action_cards import card_groups
from juli_backend.services.action_cards.card_groups import (
    create_ops_group,
    group_views,
    measure_due_groups,
    metric_summary,
    seller_sentences,
)
from juli_backend.services.action_cards.group_net import (
    BASIS_GROSS,
    BASIS_NET,
    GMV_GROSS_LABEL,
    REVENUE_NET_LABEL,
    OrderDay,
    OrderLine,
    Refund,
    basis_label,
    net_rows,
    order_days,
    refund_counts,
    shop_day,
)
from juli_backend.services.lever_flows.measurement import window_totals
from tests.support.builders import make_product, make_tenant

START = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)  # 09:00 in Vietnam
LAUNCH = date(2026, 10, 16)
D = date(2026, 9, 1)


# ------------------------------------------------------------------------------ pure


def _line(order, product="p1", *, value=100, units=1, cancelled=False, day=D):
    return OrderLine(order, product, day, cancelled, units, Decimal(value))


def test_a_cancelled_order_is_removed_in_full():
    days = order_days([_line("o1"), _line("o2", value=300, units=3, cancelled=True)], [])
    day = days["p1"][D]
    assert (day.orders, day.removed_orders, day.units, day.removed_units) == (2, 1, 4, 3)
    assert (day.value, day.removed_value) == (Decimal(400), Decimal(300))
    assert day.order_share == Decimal("0.5")
    assert day.unit_share == Decimal("0.75")
    assert day.value_share == Decimal("0.75")


def test_a_full_refund_removes_the_order_and_a_partial_one_only_its_value():
    lines = [_line("o1", value=200, units=2), _line("o2", value=200, units=2)]
    days = order_days(lines, [Refund("o1", "p1", Decimal(200)), Refund("o2", "p1", Decimal(50))])
    day = days["p1"][D]
    assert (day.removed_orders, day.removed_units) == (1, 2)
    assert day.removed_value == Decimal(250)


def test_a_refund_never_removes_more_than_the_lines_are_worth():
    day = order_days([_line("o1", value=100)], [Refund("o1", "p1", Decimal(900))])["p1"][D]
    assert (day.removed_orders, day.removed_value) == (1, Decimal(100))


def test_a_refund_without_a_product_spreads_over_the_order_by_value():
    lines = [_line("o1", "p1", value=300), _line("o1", "p2", value=100)]
    days = order_days(lines, [Refund("o1", None, Decimal(200))])
    assert days["p1"][D].removed_value == Decimal(150)
    assert days["p2"][D].removed_value == Decimal(50)
    assert days["p1"][D].removed_orders == 0  # partial on both products


def test_a_cancellation_record_removes_the_product_even_without_an_amount():
    lines = [_line("o1", "p1"), _line("o1", "p2")]
    days = order_days(lines, [Refund("o1", "p2", Decimal(0), cancellation=True)])
    assert days["p1"][D].removed_orders == 0
    assert days["p2"][D].removed_orders == 1


def test_which_return_rows_remove_money():
    assert refund_counts("other", "RETURN_OR_REFUND_REQUEST_COMPLETE", 100)
    assert refund_counts("other", "RETURN_OR_REFUND_REQUEST_SUCCESS", "100.00")
    assert refund_counts("cancellation", "CANCELLATION_REQUEST_COMPLETE", 0)
    assert not refund_counts("other", "RETURN_OR_REFUND_REQUEST_PENDING", 100)
    assert not refund_counts("other", "REFUND_OR_RETURN_REQUEST_REJECT", 100)
    assert not refund_counts("item_swap", "RETURN_OR_REFUND_REQUEST_COMPLETE", 100)
    assert not refund_counts("other", "RETURN_OR_REFUND_REQUEST_COMPLETE", 0)


def test_the_shop_day_is_utc_plus_seven():
    assert shop_day(datetime(2026, 9, 1, 16, 59)) == date(2026, 9, 1)
    assert shop_day(datetime(2026, 9, 1, 17, 0)) == date(2026, 9, 2)
    assert shop_day(datetime(2026, 9, 1, 17, 0, tzinfo=UTC)) == date(2026, 9, 2)


def _analytics(day, *, orders=10, items=12, gmv=1_000_000, impressions=500, clicks=20):
    return AnalyticsPerformanceInterval(
        start_date=day,
        impressions=impressions,
        clicks=clicks,
        sku_orders=orders,
        items_sold=items,
        gmv=Decimal(gmv),
    )


def test_net_rows_scale_orders_items_and_gmv_and_leave_traffic():
    rows = [_analytics(D), _analytics(D + timedelta(days=1))]
    shares = {
        D: OrderDay(
            orders=4,
            removed_orders=1,
            units=4,
            removed_units=2,
            value=Decimal(400),
            removed_value=Decimal(100),
        )
    }
    net = net_rows(rows, shares)
    assert (net[0].sku_orders, net[0].items_sold, net[0].gmv) == (
        Decimal("7.50"),
        Decimal("6.0"),
        Decimal("750000.00"),
    )
    assert (net[0].impressions, net[0].clicks) == (Decimal(500), Decimal(20))
    # A day with no order lines keeps TikTok's values (share 0).
    assert (net[1].sku_orders, net[1].gmv) == (Decimal(10), Decimal(1_000_000))
    gross = window_totals(rows, D, D + timedelta(days=1))
    totals = window_totals(net, D, D + timedelta(days=1))
    assert gross.value("gmv_per_order") == Decimal(100_000)
    assert totals.value("gmv_per_order") == Decimal("1750000") / Decimal("17.5")


def test_the_ops_labels_name_the_basis():
    assert basis_label("AOV", BASIS_NET) == "AOV (đã trừ huỷ/hoàn)"
    assert basis_label("AOV", BASIS_GROSS) == "AOV (gồm đơn huỷ/hoàn, theo TikTok)"
    verdict = {"primary": None, "products": []}
    assert metric_summary("aov", "total", verdict, basis=BASIS_NET)["label"] == (
        "AOV (đã trừ huỷ/hoàn) · tất cả kênh"
    )
    assert metric_summary("items_per_order", "total", verdict, basis=BASIS_GROSS)["label"] == (
        "Số món mỗi đơn (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh"
    )
    # CTR is not a money metric: no basis in its label; no basis = the old label.
    ctr = metric_summary("ctr", "product_card", verdict, basis=BASIS_NET)
    assert (ctr["label"], ctr["basis"]) == ("CTR · Thẻ sản phẩm", None)
    assert metric_summary("aov", "total", verdict)["label"] == "AOV · tất cả kênh"
    assert (REVENUE_NET_LABEL, GMV_GROSS_LABEL) == (
        "Doanh thu (đã trừ huỷ/hoàn)",
        "GMV TikTok (gồm huỷ/hoàn)",
    )


# ---------------------------------------------------------------------------- stored


@pytest_asyncio.fixture
async def shop(session):
    _user, shop = await make_tenant(session)
    return shop


async def _products(session, shop, n: int) -> list[str]:
    ids = [f"pk{i:02d}" for i in range(n)]
    for pid in ids:
        await make_product(session, shop, tiktok_product_id=pid, name=f"Sản phẩm {pid}")
    return ids


def _row(shop_id, product, day, *, orders, items, gmv):
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"t:{product}:{day.isoformat()}",
        grain="product",
        start_date=day,
        end_date=day + timedelta(days=1),
        tiktok_product_id=product,
        impressions=5000,
        clicks=200,
        sku_orders=orders,
        items_sold=items,
        gmv=Decimal(gmv),
        traffic_breakdown={
            "PRODUCT_CARD": {"impressions": 2000, "clicks": 80},
            "VIDEO": {"impressions": 3000, "clicks": 120},
        },
        update_time=datetime(2026, 10, 1),
    )


def _order(session, shop_id, order_id, product, day, *, value, units, status="DELIVERED"):
    created = datetime.combine(day, datetime.min.time()) + timedelta(hours=3)  # 10:00 VN
    order = Order(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_order_id=order_id,
        status=status,
        total_amount=Decimal(value),
        currency="VND",
        tiktok_created_at=created,
        update_time=created,
    )
    session.add(order)
    session.add(
        OrderItem(
            id=uuid.uuid4(),
            shop_id=shop_id,
            order_id=order.id,
            tiktok_order_id=order_id,
            tiktok_product_id=product,
            tiktok_sku_id=f"{product}-sku",
            quantity=units,
            unit_price=Decimal(value) / units,
            line_total=Decimal(value),
            update_time=created,
        )
    )


async def _data(session, shop_id, arms, *, aov_lift: float, with_orders: bool):
    """Days −42 … 13. Analytics: steady, the treated AOV / items +``aov_lift`` after
    launch. Orders (``with_orders``): two a day per product; after launch each treated
    product's bigger order (3 units, 3× the value) is cancelled one day and refunded
    in full the next -- so TikTok's GMV over-states the treated AOV."""
    for product, arm in arms.items():
        k = int(product[-2:])
        for offset in range(-42, 14):
            day = LAUNCH + timedelta(days=offset)
            wobble = 1 + 0.01 * ((k * 7 + offset) % 5 - 2)
            lift = 1 + aov_lift if arm == ARM_TREATED and offset >= 0 else 1
            session.add(
                _row(
                    shop_id,
                    product,
                    day,
                    orders=10,
                    items=round(10 * wobble * lift),
                    gmv=round(10 * 200_000 * wobble * lift),
                )
            )
            if not with_orders:
                continue
            small, big = f"{product}-{offset}-a", f"{product}-{offset}-b"
            _order(session, shop_id, small, product, day, value=100_000, units=1)
            bad = arm == ARM_TREATED and offset >= 0
            status = "cancelled" if bad and offset % 2 == 0 else "DELIVERED"
            _order(session, shop_id, big, product, day, value=300_000, units=3, status=status)
            if bad and offset % 2 == 1:
                session.add(
                    Return(
                        id=uuid.uuid4(),
                        shop_id=shop_id,
                        tiktok_return_id=f"r-{big}",
                        tiktok_order_id=big,
                        tiktok_product_id=product,
                        return_type="other",
                        refund_amount=Decimal(300_000),
                        status="RETURN_OR_REFUND_REQUEST_COMPLETE",
                        update_time=datetime(2026, 10, 30),
                    )
                )
    await session.flush()


async def _pack_group(session, shop, monkeypatch, *, with_orders: bool):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 777)
    products = await _products(session, shop, 6)
    await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=products,
        reason=None,
        guard=None,
        created_by="x",
        now=START,
    )
    arms = card_groups.assign_arms(products, 777)
    await _data(session, shop.id, arms, aov_lift=0.25, with_orders=with_orders)
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    return measured


@pytest.mark.asyncio
async def test_an_ops_group_reads_aov_net_and_keeps_tiktok_gmv_beside_it(
    session, shop, monkeypatch
):
    measured = await _pack_group(session, shop, monkeypatch, with_orders=True)
    verdict = measured.verdict
    assert verdict["basis"]["money"] == BASIS_NET
    assert "đã trừ đơn huỷ/hoàn" in verdict["basis"]["text"]
    # TikTok's GMV: +25 %. Net: the big order (3/4 of the value, 1/2 of the orders) goes
    # -> AOV × (1/4) / (1/2) = × 0.5 -> 1.25 × 0.5 = −37.5 %.
    gross = verdict["gross"]
    assert gross["label"] == "AOV (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh"
    assert gross["primary"]["difference"] == pytest.approx(25, abs=3)
    assert verdict["primary"]["difference"] == pytest.approx(-37.5, abs=3)
    # The replay and the EB lift run on the net series.
    assert verdict["false_alarm"] is not None
    assert verdict["primary"]["eb"]["observed_pct"] < 0
    items = verdict["metrics"]["items_per_order|total"]
    assert items["label"] == "Số món mỗi đơn (đã trừ huỷ/hoàn) · tất cả kênh"
    assert items["basis"] == BASIS_NET
    assert items["gross"]["primary"]["difference"] == pytest.approx(25, abs=4)
    # Items: 3 of 4 units go, half the orders -> × 0.5 as well.
    assert items["primary"]["difference"] == pytest.approx(-37.5, abs=4)
    ctr = verdict["metrics"]["ctr|product_card"]
    assert ctr["label"] == "CTR · Thẻ sản phẩm" and "gross" not in ctr
    # The guard reads the net AOV: it fell, so no "dù AOV tăng".
    assert "dù AOV tăng" not in verdict["guard"]["text"]
    [view] = await group_views(session, shop.id)
    plan = view["plan"]
    assert plan["revenue_basis"] == BASIS_NET
    before = plan["have_before"][ARM_TREATED]
    # Before launch nothing is removed: net = TikTok GMV.
    assert before["gmv_net"] == before["gmv"] and before["orders_net"] == before["orders"]


@pytest.mark.asyncio
async def test_without_shop_orders_the_verdict_stays_on_tiktok_gmv_and_says_so(
    session, shop, monkeypatch
):
    measured = await _pack_group(session, shop, monkeypatch, with_orders=False)
    verdict = measured.verdict
    assert verdict["basis"]["money"] == BASIS_GROSS
    assert "gồm đơn huỷ/hoàn" in verdict["basis"]["text"]
    assert "gross" not in verdict and "net" not in verdict
    assert verdict["primary"]["difference"] == pytest.approx(25, abs=3)
    items = verdict["metrics"]["items_per_order|total"]
    assert items["basis"] == BASIS_GROSS and "gross" not in items
    [view] = await group_views(session, shop.id)
    assert view["plan"]["revenue_basis"] == BASIS_GROSS
    assert "gmv_net" not in view["plan"]["have_before"][ARM_TREATED]


@pytest.mark.asyncio
async def test_orders_that_do_not_cover_the_pre_period_keep_tiktok_gmv(session, shop, monkeypatch):
    """Orders only from day −10: the verdict reads days −42 … 13, so no net basis."""
    monkeypatch.setattr(card_groups, "new_seed", lambda: 777)
    products = await _products(session, shop, 6)
    await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=products,
        reason=None,
        guard=None,
        created_by="x",
        now=START,
    )
    arms = card_groups.assign_arms(products, 777)
    await _data(session, shop.id, arms, aov_lift=0.25, with_orders=False)
    for product in products:
        for offset in range(-10, 14):
            day = LAUNCH + timedelta(days=offset)
            _order(session, shop.id, f"{product}-{offset}", product, day, value=1, units=1)
    await session.flush()
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    assert measured.verdict["basis"]["money"] == BASIS_GROSS


async def _card_aov_group(session, shop_id, products) -> CardGroup:
    group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        group_key="aov|buy_more_save_more|total",
        metric="aov",
        lever="buy_more_save_more",
        channel="total",
        launched_on=LAUNCH,
        release_on=LAUNCH + timedelta(days=14),
        seed=777,
        status="open",
    )
    session.add(group)
    arms = card_groups.assign_arms(products, 777)
    for product, arm in arms.items():
        session.add(
            CardGroupMember(
                id=uuid.uuid4(),
                shop_id=shop_id,
                group_id=group.id,
                tiktok_product_id=product,
                arm=arm,
                assigned_at=datetime(2026, 10, 16, 2, 0),
            )
        )
    await session.flush()
    return group


@pytest.mark.asyncio
async def test_a_card_groups_seller_sentence_and_primary_do_not_change(session, shop):
    """The seller-facing result stays on TikTok's GMV; the net reading is Ops-only."""
    products = [f"pk{i:02d}" for i in range(6)]
    group = await _card_aov_group(session, shop.id, products)
    arms = card_groups.assign_arms(products, 777)
    await _data(session, shop.id, arms, aov_lift=0.25, with_orders=False)
    [first] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    primary_before = first.verdict["primary"]
    sentence_before = await seller_sentences(session, shop.id)
    assert "net" not in first.verdict

    # Same analytics, now with the shop's orders (the treated big orders cancelled /
    # refunded): measure again from scratch.
    for product, arm in arms.items():
        for offset in range(-42, 14):
            day = LAUNCH + timedelta(days=offset)
            small, big = f"{product}-{offset}-a", f"{product}-{offset}-b"
            _order(session, shop.id, small, product, day, value=100_000, units=1)
            bad = arm == ARM_TREATED and offset >= 0
            _order(
                session,
                shop.id,
                big,
                product,
                day,
                value=300_000,
                units=3,
                status="cancelled" if bad else "DELIVERED",
            )
    group.status, group.verdict, group.measured_at = "open", None, None
    await session.flush()
    [again] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    verdict = again.verdict
    assert verdict["primary"] == primary_before
    assert await seller_sentences(session, shop.id) == sentence_before
    assert verdict["basis"]["money"] == BASIS_NET
    net = verdict["net"]
    assert net["label"] == "AOV (đã trừ huỷ/hoàn) · tất cả kênh"
    assert net["primary"]["difference"] == pytest.approx(-37.5, abs=3)
    assert verdict["ops_rule"]["label"] == "AOV (gồm đơn huỷ/hoàn, theo TikTok) · tất cả kênh"
    # The Ops EB pass re-shrinks the net reading too.
    [view] = card_groups.apply_pooled_eb(await group_views(session, shop.id), [], pooled=True)
    assert view["verdict"]["net"]["primary"]["eb"] is not None
    assert view["seller_sentence"] == sentence_before[group.group_key]
