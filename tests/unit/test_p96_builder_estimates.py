"""P96: the builder's estimates follow the size of the change (bug sweep 2026-11-05, ORY).

Every test here failed on the code before P96. Pure prediction tests first, then the builder's
typed versions on the synthetic reco shop (``tests/support/shopee_reco``, SQLite, invented
figures). Owner decisions 2026-11-05: the lift scales with the size of the change (0-2x the
prior), only qualifying orders count, caps scale gain and cost, the price response is capped and
concave, a change runs its own days up to 90, follower / livestream vouchers are refused.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

import pytest
from pydantic import TypeAdapter

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import config, prediction
from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.model import ProfitModel
from tests.support.shopee_analytics import CUR_START, _line
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
SPEC = TypeAdapter(sp.VersionSpec)
QS = ("p10", "p25", "p50", "p75", "p90")


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def one(session, shop, **version):
    await materialize.backfill_shop(session, shop.shop_id)  # P98: the stored funnel
    out = await builder.evaluate_versions(
        session, shop.shop_id, [SPEC.validate_python(version)], as_of=AS_OF, now=NOW
    )
    return out["versions"][0]


def p50(v, key="gmv"):
    return v["delta"][key]["p50"]


# ==================== prediction: price response, bands, floor


def test_the_price_response_is_capped_and_flatter_beyond_thirty_percent():
    price = KINDS["product_discount"]
    lo30, hi30 = prediction.prior_range(price, 30, "unknown")
    lo60, hi60 = prediction.prior_range(price, 60, "unknown")
    assert hi60 < 2 * hi30  # concave: the second 30 points count less than the first
    _, hi90 = prediction.prior_range(price, 90, "unknown")
    assert hi90 <= config.PRICE_LIFT_MAX
    lo_rise, _ = prediction.prior_range(price, -100, "unknown")
    assert lo_rise >= config.PRICE_LIFT_MIN


def _pm(**kw):
    base = {
        "effect_days": 30,
        "base_gmv_per_day": D(100_000),
        "base_orders_per_day": D(1),
        "aov": D(100_000),
        "profit_per_gmv": D("0.2"),
    }
    return ProfitModel(**{**base, **kw})


def test_a_lift_never_takes_more_than_the_scopes_whole_gmv():
    lift = prediction.Lift("orders", -3.0, -1.5, 1.0, "prior")
    money = prediction.convert(lift, _pm())
    floor = -100_000 * 30
    assert all(money["total"][q]["dgmv"] >= floor for q in QS)
    assert all(money["period"]["total"][q]["dgmv"] >= floor for q in QS)


def test_bands_run_low_to_high_when_more_gmv_means_more_loss():
    lift = prediction.Lift("orders", 0.1, 0.5, 1.0, "prior")
    money = prediction.convert(lift, _pm(profit_per_gmv=D("-0.3")))
    for block in (money["total"], money["period"]["total"], money["per_day"]["total"]):
        profits = [block[q]["dprofit"] for q in QS]
        assert profits == sorted(profits)


def test_lift_scale_scales_the_predicted_gain_only():
    lift = prediction.Lift("orders", 0.1, 0.3, 1.0, "prior")
    full = prediction.convert(lift, _pm(certain_dgmv_per_day=D(1000)))
    half = prediction.convert(lift, _pm(certain_dgmv_per_day=D(1000), lift_scale=D("0.5")))
    assert half["predicted"]["p50"]["dgmv"] == pytest.approx(full["predicted"]["p50"]["dgmv"] / 2)
    assert half["certain"] == full["certain"]


# ==================== price, discount, flash sale


async def test_a_typed_new_price_is_used_to_the_dong(session, shop):
    for typed in (91_300, 94_700, 96_100, 99_900):
        v = await one(
            session,
            shop,
            kind="price",
            item_id="1001",
            variations=[{"variation_id": "", "final_price": typed}],
        )
        assert v["details"]["skus"][0]["price_after"] == typed


async def test_a_discount_runs_its_own_days_and_its_cost_follows_them(session, shop):
    def disc(start, end):
        return one(
            session,
            shop,
            kind="product_discount",
            item_id="1001",
            variations=[{"variation_id": "", "discount_pct": 10}],
            start=start,
            end=end,
        )

    three = await disc("2026-10-10", "2026-10-12")
    month = await disc("2026-10-10", "2026-11-08")
    two = await disc("2026-10-10", "2026-12-08")
    assert (three["delta"]["days"], month["delta"]["days"], two["delta"]["days"]) == (3, 30, 60)
    assert three["cost"]["amount"] == pytest.approx(month["cost"]["amount"] / 10, rel=0.02)
    assert two["cost"]["amount"] == pytest.approx(month["cost"]["amount"] * 2, rel=0.02)
    assert p50(two) == pytest.approx(p50(month) * 2, rel=0.02)


async def test_a_flash_slot_costs_its_hours_and_its_units(session, shop):
    def flash(hours, units):
        return one(
            session,
            shop,
            kind="flash_sale",
            item_id="1001",
            variations=[{"variation_id": "", "discount_pct": 20}],
            units=units,
            slot_hours=hours,
        )

    short, day = await flash(2, 1000), await flash(24, 1000)
    assert day["cost"]["amount"] == pytest.approx(short["cost"]["amount"] * 12, rel=0.02)
    single = await flash(24, 1)
    per_unit = 90_000 - 80_000  # G1 sells at 90k; 20 % off the 100k list = 80k
    assert 0 < single["cost"]["amount"] <= per_unit
    assert p50(single) <= p50(day)


# ==================== voucher


async def test_a_bigger_voucher_earns_a_bigger_lift(session, shop):
    small = await one(
        session, shop, kind="voucher", discount_type="amount", value=5000, min_spend=100_000
    )
    big = await one(
        session, shop, kind="voucher", discount_type="amount", value=10_000, min_spend=100_000
    )
    assert p50(big) > p50(small) > 0


async def test_a_voucher_nobody_qualifies_for_gains_nothing(session, shop):
    v = await one(
        session, shop, kind="voucher", discount_type="amount", value=5000, min_spend=10_000_000
    )
    assert p50(v) in (0, None) and v["cost"]["amount"] == 0  # was +59.920 đ on ORY
    assert v["break_even"]["reason"] == "no_qualifying_orders"
    assert v["break_even"]["reason_text"] == "Chưa có đơn nào đạt đơn tối thiểu."


async def test_a_binding_usage_limit_scales_the_gain_instead_of_zeroing_it(session, shop):
    free = await one(session, shop, kind="voucher", discount_type="amount", value=5000)
    expected = free["details"]["voucher_detail"]["usage"]["expected_uses"]
    limit = max(1, int(expected // 2))
    capped = await one(
        session, shop, kind="voucher", discount_type="amount", value=5000, usage_limit=limit
    )
    # P98: the usage limit caps the voucher's uses and so its cost (ADR-122 d.6)
    assert 0 < capped["result"]["cost"]["total"] < free["result"]["cost"]["total"]


async def test_follower_and_livestream_vouchers_are_refused_without_their_orders(session, shop):
    for scope in ("follower", "livestream"):
        v = await one(
            session, shop, kind="voucher", scope=scope, discount_type="amount", value=5000
        )
        assert v["ok"] is False and v["refusal"]["code"] == "voucher_scope_no_data"
        assert v["refusal"]["message"] == "Chưa có dữ liệu đơn theo loại voucher này để ước tính."


async def test_an_amount_voucher_at_or_above_its_minimum_spend_is_refused(session, shop):
    for value in (100_000, 150_000):
        v = await one(
            session, shop, kind="voucher", discount_type="amount", value=value, min_spend=100_000
        )
        assert v["ok"] is False and v["refusal"]["code"] == "voucher_value_over_min_spend"


async def test_a_voucher_break_even_is_an_aov_not_extra_orders(session, shop):
    v = await one(
        session, shop, kind="voucher", discount_type="amount", value=5000, min_spend=100_000
    )
    be = v["break_even"]
    assert be["basis"] == "aov" and be["extra_orders"] is None and "ctor_needed" not in be
    assert be["aov_needed"] > be["aov_now"] > 0


# ==================== gift


async def test_a_more_valuable_gift_earns_a_bigger_lift(session, shop):
    def gift(cost):
        return one(
            session,
            shop,
            kind="gift",
            gift={"unit_cost": cost, "label": "Móc khoá"},
            trigger={"type": "min_spend", "amount": 100_000},
        )

    cheap, rich = await gift(2000), await gift(8000)
    # P98: the gift's lift is its family's (CTOR on qualifying buyers); its value is its cost
    assert p50(rich) > 0 and p50(cheap) > 0
    assert rich["cost"]["amount"] > cheap["cost"]["amount"] > 0


async def test_a_gift_nobody_qualifies_for_gains_nothing(session, shop):
    v = await one(
        session,
        shop,
        kind="gift",
        gift={"unit_cost": 5000, "label": "Móc khoá"},
        trigger={"type": "min_spend", "amount": 10_000_000},
    )
    assert p50(v) in (0, None) and v["cost"]["amount"] == 0
    assert v["delta"]["profit"]["p50"] in (0, None)


async def test_the_typed_packaging_counts_for_a_listing_gift_too(session, shop):
    v = await one(
        session,
        shop,
        kind="gift",
        gift={"item_id": "1003", "qty": 1, "packaging": 5000},
        trigger={"type": "buy_item", "item_id": "1001"},
    )
    assert v["details"]["gift"]["cost_per_gift"] == 15_000 + 5000  # T1 giá vốn + typed packaging


async def test_a_gifts_order_count_comes_from_the_order_lines(session, shop):
    v = await one(
        session,
        shop,
        kind="gift",
        gift={"item_id": "1003", "qty": 1},
        trigger={"type": "buy_item", "item_id": "1001"},
    )
    orders = next(m for m in v["driver"]["metrics"] if m["key"] == "orders")
    # P98: the before is the stored funnel of the trigger product (ShopMetrics đơn)
    assert orders["before"] == v["result"]["detail"]["before"]["orders"] > 0
    assert v["details"]["gift"]["total_orders"] > 0


# ==================== add-on


async def add_baskets(session, shop, n=4, qty=1):
    for i in range(n):
        a = _line(shop.shop_id, 300 + i, CUR_START, "G1", deal=90_000)
        b = _line(shop.shop_id, 300 + i, CUR_START, "N1", original=60_000, deal=54_000, qty=qty)
        b.line_no = 1
        session.add_all([a, b])
    await session.commit()


async def test_an_add_on_costs_its_discount_on_the_attaches_it_brings(session, shop):
    v = await one(
        session, shop, kind="add_on", main_item_id="1001", addons=[{"item_id": "1002", "pct": 10}]
    )
    assert v["details"]["addons"][0]["orders_with_both_today"] == 0
    assert v["cost"]["amount"] > 0  # was 0: no basket held both yet


async def test_an_add_on_gain_follows_its_price_and_its_own_margin(session, shop):
    def addon(pct):
        return one(
            session,
            shop,
            kind="add_on",
            main_item_id="1001",
            addons=[{"item_id": "1002", "pct": pct}],
        )

    small, deep = await addon(5), await addon(20)
    assert p50(small) != p50(deep)
    for v in (small, deep):
        band = v["delta"]["profit"]
        assert band["low"] <= band["p50"] <= band["high"]


async def test_the_per_order_limit_caps_the_add_on_units(session, shop):
    await add_baskets(session, shop, 4, qty=3)

    def addon(limit):
        return one(
            session,
            shop,
            kind="add_on",
            main_item_id="1001",
            addons=[{"item_id": "1002", "pct": 10, "limit_per_order": limit}],
        )

    one_unit, three = await addon(1), await addon(3)
    a1, a3 = one_unit["details"]["addons"][0], three["details"]["addons"][0]
    assert a3["discount_cost_on_existing"] == 3 * a1["discount_cost_on_existing"] > 0


# ==================== variation set


async def test_a_set_has_a_profit_and_its_price_moves_the_estimate(session, shop):
    def set3(price):
        return one(
            session,
            shop,
            kind="variation_set",
            item_id="1001",
            new_variations=[{"name": "Set 3", "price": price, "pack_count": 3}],
        )

    cheap, mid = await set3(210_000), await set3(240_000)
    assert cheap["delta"]["profit"]["p50"] is not None
    assert p50(cheap) != p50(mid)


async def test_a_set_dearer_than_single_units_is_flagged(session, shop):
    v = await one(
        session,
        shop,
        kind="variation_set",
        item_id="1001",
        new_variations=[{"name": "Set 3", "price": 400_000, "pack_count": 3}],
    )
    assert any(w.get("code") == "set_dearer_than_single" for w in v["warnings"])


async def test_a_new_variation_cannot_reuse_an_existing_sku(session, shop):
    v = await one(
        session,
        shop,
        kind="variation_set",
        item_id="1001",
        new_variations=[{"name": "Set 3", "price": 240_000, "sku": "G1"}],
    )
    assert v["ok"] is False and v["refusal"]["code"] == "sku_duplicate"


# ==================== affiliate


async def test_a_higher_commission_earns_a_bigger_lift(session, shop):
    def aff(pct):
        return one(session, shop, kind="affiliate", item_id="1001", commission_pct=pct)

    low, high = await aff(5), await aff(20)
    # P98 / ADR-122 d.9: affiliate extra orders are measured only, from the KOL builder
    assert p50(high) is None and high["result_refusal"]["code"] == "affiliate_needs_kol"
    assert high["cost"]["amount"] > low["cost"]["amount"]


async def test_samples_come_out_of_the_profit(session, shop):
    def aff(qty):
        return one(
            session,
            shop,
            kind="affiliate",
            item_id="1001",
            commission_pct=10,
            sample_qty=qty,
            sample_ship_fee=20_000,
        )

    none, ten = await aff(0), await aff(10)
    sample = ten["cost"]["sample"]["total"]
    assert sample > 0
    assert ten["cost"]["amount"] == pytest.approx(none["cost"]["amount"] + sample, abs=2)


# ==================== listing hide / relist


async def test_hiding_a_selling_listing_loses_its_gmv(session, shop):
    v = await one(session, shop, kind="listing_hide", item_id="1001")
    assert p50(v) is not None and p50(v) < 0
    assert v["delta"]["profit"]["p50"] < 0


async def test_a_live_listing_in_stock_cannot_be_relisted(session, shop):
    v = await one(session, shop, kind="listing_relist", item_id="1001")
    assert v["ok"] is False and v["refusal"]["code"] == "listing_already_live"


# ==================== reasons are sentences


async def test_a_break_even_reason_comes_with_its_sentence(session, shop):
    v = await one(session, shop, kind="title", item_id="1001", title="Túi đựng thực phẩm mới")
    be = v["break_even"]
    assert be["reason"] == "not_applicable" and be["reason_text"]
    assert "not_applicable" not in be["reason_text"]


# ==================== SKU checks in the builder


class _Env:
    def __init__(self, skus):
        self._skus = skus

    def skus_of(self, item):
        return self._skus.get(item, [])


class _Ctx:
    """The parts of ``BuilderContext`` the combo / add-on translation reads."""

    def __init__(self, rows, skus):
        self._rows, self.env = rows, _Env(skus)

    def rows(self, item):
        return self._rows.get(item, [])

    def variation(self, item, vid):
        return next((r for r in self.rows(item) if r["variation_id"] == vid), None)

    def sku_key(self, item, vid):
        row = self.variation(item, vid)
        return None if row is None else row["sku_key"]


def test_a_variation_of_the_product_without_orders_is_not_called_unknown():
    from juli_backend.services.shopee_builder.context import SpecRefused
    from juli_backend.services.shopee_builder.translate import to_variant

    ctx = _Ctx(
        {
            "1": [
                {"variation_id": "a", "sku_key": "S-A"},
                {"variation_id": "b", "sku_key": "S-B"},
            ],
            "2": [{"variation_id": "", "sku_key": "S-2"}],
        },
        {"1": ["S-A"], "2": ["S-2"]},  # S-B has never sold
    )
    addon = SPEC.validate_python(
        {
            "kind": "add_on",
            "main_item_id": "2",
            "addons": [{"item_id": "1", "variation_id": "b", "pct": 10}],
        }
    )
    with pytest.raises(SpecRefused) as refused:
        to_variant(addon, ctx)
    assert refused.value.code == "sku_no_orders:S-B"


# ==================== variations: the best seller first


def test_variations_list_the_best_seller_first_with_its_order_count():
    from juli_backend.services.shopee_builder import variations as var

    rows = [
        {"variation_id": "a", "sku_key": "A", "stock": 0},
        {"variation_id": "b", "sku_key": "B", "stock": 5},
        {"variation_id": "c", "sku_key": "C", "stock": 9},
        {"variation_id": "d", "sku_key": "D", "stock": None},
    ]

    class L:
        def __init__(self, order_id, sku):
            self.order_id, self.sku, self.product_id = order_id, sku, "1"

    lines = [L("o1", "B"), L("o2", "B"), L("o3", "C"), L("o3", "C"), L("o4", "X")]
    out = var.with_orders(rows, lines, "1")
    assert [r["variation_id"] for r in out] == ["b", "c", "d", "a"]
    assert [r["orders_30d"] for r in out] == [2, 1, 0, 0]


async def test_the_variations_endpoint_counts_orders_per_variation(session, shop):
    out = await builder.product_variations(session, shop.shop_id, "1001", as_of=AS_OF, now=NOW)
    rows = out["variations"]
    assert all("orders_30d" in r for r in rows)
    assert rows[0]["orders_30d"] > 0  # the best seller leads
    assert [r["orders_30d"] for r in rows] == sorted((r["orders_30d"] for r in rows), reverse=True)
