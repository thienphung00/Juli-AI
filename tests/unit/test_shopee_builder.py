"""P92 B-1 .. B-5: the builder's typed versions, the picker, variation economics, the co-purchase
list, the estimate basis and the outcome block of every kind -- on the synthetic reco shop
(``tests/support/shopee_reco``), SQLite, invented figures."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select

from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_analytics.catalog import ItemInfo, Variation
from juli_backend.services.shopee_analytics.rules_view import ProfitRules
from juli_backend.services.shopee_builder import copurchase, outcome, response, traffic
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder import variations as var
from juli_backend.services.shopee_profit.fees import (
    FeeBase,
    FeeComponent,
    FeeFormula,
    FeeKind,
    FeeSchedule,
)
from juli_backend.services.shopee_profit.order_profit import OrderLine
from juli_backend.services.shopee_recommendations import manual
from juli_backend.services.shopee_recommendations.model import DiscountResponse
from tests.support.shopee_analytics import CUR_START, _line
from tests.support.shopee_reco import AS_OF, rule, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
SPEC = TypeAdapter(sp.VersionSpec)


def S(**kw):
    return SPEC.validate_python(kw)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


async def evaluate(session, shop, *versions, **kw):
    """P98: the builder reads the stored funnel, so rebuild it after a test adds order lines."""
    await materialize.backfill_shop(session, shop.shop_id)
    specs = [S(**v) for v in versions]
    return await builder.evaluate_versions(session, shop.shop_id, specs, as_of=AS_OF, now=NOW, **kw)


async def one(session, shop, **version):
    out = await evaluate(session, shop, version)
    return out["versions"][0]


async def add_baskets(session, shop, n=4):
    """``n`` orders holding a 1001 and a 1002 line (the seeded orders hold one line each)."""
    for i in range(n):
        a = _line(shop.shop_id, 300 + i, CUR_START, "G1", deal=90_000)
        b = _line(shop.shop_id, 300 + i, CUR_START, "N1", original=60_000, deal=54_000)
        b.line_no = 1
        session.add_all([a, b])
    await session.commit()
    await materialize.backfill_shop(session, shop.shop_id)  # P98: the stored funnel follows
    await session.commit()


# ==================== the typed inputs


def test_every_kind_has_a_model_and_unknown_keys_are_refused():
    assert set(sp.KIND_KEYS) == {
        "voucher",
        "combo",
        "listing_combo",
        "add_on",
        "gift",
        "product_discount",
        "price",
        "flash_sale",
        "variation_set",
        "ads",
        "title",
        "cover_image",
        "description_first_line",
        "affiliate",
        "price_display",
        "listing_hide",
        "listing_relist",
    }
    with pytest.raises(ValidationError):
        S(kind="voucher", discount_type="amount", value=5000, colour="red")
    with pytest.raises(ValidationError):
        S(kind="nope")


@pytest.mark.parametrize(
    "version",
    [
        {"kind": "voucher", "discount_type": "pct", "value": 95},
        {"kind": "voucher", "discount_type": "amount", "value": 5000, "max_value": 1000},
        {"kind": "voucher", "scope": "product", "discount_type": "amount", "value": 5000},
        {"kind": "voucher", "discount_type": "amount", "value": 5000, "item_ids": ["1"]},
        {
            "kind": "voucher",
            "discount_type": "amount",
            "value": 5000,
            "start": "2026-10-05",
            "end": "2026-10-01",
        },
        {
            "kind": "voucher",
            "discount_type": "amount",
            "value": 5000,
            "start": "2026-01-01",
            "end": "2026-06-01",
        },
        {"kind": "voucher", "discount_type": "amount", "value": 5000, "min_spend": -1},
        {
            "kind": "combo",
            "item_ids": [],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 5}],
        },
        {"kind": "combo", "item_ids": ["1"], "discount_type": "pct", "tiers": []},
        {
            "kind": "combo",
            "item_ids": ["1", "1"],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 5}],
        },
        {
            "kind": "combo",
            "item_ids": ["1", "2"],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 99}],
        },
        {
            "kind": "combo",
            "item_ids": ["1", "2"],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 5}, {"qty": 2, "value": 6}],
        },
        {
            "kind": "combo",
            "item_ids": ["1", "2"],
            "discount_type": "pct",
            "tiers": [{"qty": 1, "value": 5}],
        },
        {
            "kind": "combo",
            "item_ids": ["1", "2"],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 5}],
            "name": "x" * 26,
        },
        {"kind": "add_on", "main_item_id": "1", "addons": []},
        {
            "kind": "add_on",
            "main_item_id": "1",
            "addons": [{"item_id": str(n), "pct": 5} for n in range(2, 8)],
        },
        {"kind": "add_on", "main_item_id": "1", "addons": [{"item_id": "1", "pct": 5}]},
        {"kind": "add_on", "main_item_id": "1", "addons": [{"item_id": "2", "pct": 5, "price": 9}]},
        {
            "kind": "gift",
            "gift": {"item_id": "2", "unit_cost": 5},
            "trigger": {"type": "min_spend", "amount": 1},
        },
        {"kind": "gift", "gift": {"unit_cost": 5}, "trigger": {"type": "buy_item"}},
        {
            "kind": "product_discount",
            "item_id": "1",
            "variations": [{"discount_pct": 10, "final_price": 5}],
        },
        {"kind": "product_discount", "item_id": "1", "variations": [{"change_pct": 10}]},
        {"kind": "price", "item_id": "1", "variations": [{"discount_pct": 10}]},
        {"kind": "title", "item_id": "1", "title": "x" * 101},
        {"kind": "ads", "lever": "budget"},
        {"kind": "ads", "lever": "keywords", "keywords": []},
    ],
)
def test_the_inputs_have_hard_bounds(version):
    with pytest.raises(ValidationError):
        S(**version)


def test_items_of_lists_every_listing_a_version_names():
    gift = S(
        kind="gift",
        gift={"item_id": "9"},
        trigger={"type": "buy_item", "item_id": "5"},
    )
    addon = S(kind="add_on", main_item_id="1", addons=[{"item_id": "2", "pct": 5}])
    combo = S(
        kind="combo", item_ids=["3", "4"], discount_type="pct", tiers=[{"qty": 2, "value": 5}]
    )
    assert sorted(sp.items_of(gift)) == ["5", "9"] and sp.items_of(addon) == ["1", "2"]
    assert sp.items_of(combo) == ["3", "4"]


# ==================== B-2 variation economics

SCHEDULE = FeeSchedule(
    (
        FeeFormula(
            date(2026, 1, 1),
            (
                FeeComponent("commission", FeeKind.PCT, FeeBase.BUYER_PAID, rate=D("0.10")),
                FeeComponent("fixed", FeeKind.FIXED, amount=D(3000)),
            ),
        ),
    )
)
INFO = ItemInfo(
    "2001",
    "Hộp đựng",
    variations=(
        Variation("v3", "Combo 3 hộp", "BOX"),
        Variation("v5", "Combo 5 hộp", "BOX"),
        Variation("v1", "Hộp lẻ", "BOX1"),
    ),
)
SNAPS = [
    {"variation_id": "v3", "list_price": D(300_000), "current_price": D(270_000), "stock": 9},
    {"variation_id": "v5", "list_price": D(450_000), "current_price": D(400_000), "stock": 4},
    {"variation_id": "v1", "list_price": D(100_000), "current_price": D(100_000), "stock": 50},
]


def rows(rules: ProfitRules, **kw):
    return var.variation_rows(
        "2001", INFO, SNAPS, rules=rules, schedule=SCHEDULE, on=date(2026, 10, 7), **kw
    )


def test_variations_show_price_pack_unit_price_and_margin():
    rules = ProfitRules(
        sku_cost={"BOX": D(30_000), "BOX1": D(30_000)}, packaging_by_key={"2001": D(2000)}
    )
    by = {r["variation_id"]: r for r in rows(rules)}
    c3, c5, single = by["v3"], by["v5"], by["v1"]
    assert (c3["pack_count"], c3["pack_source"]) == (3, "name")
    assert (c5["pack_count"], single["pack_count"]) == (5, 1)
    assert (c3["list_price"], c3["selling_price"], c3["price_per_unit"]) == (300000, 270000, 90000)
    assert c5["price_per_unit"] == 80000 and single["price_per_unit"] == 100000
    # one Combo 3 order: 270.000 - 10 % - 3.000 fixed - 3 x 30.000 - 2.000 packaging = 148.000
    assert c3["profit_per_unit"] == 148_000 and c3["margin_pct"] == 54.8
    assert c3["margin_label"] is None and c3["has_cost"] is True
    # a bigger pack = a bigger giá vốn: Combo 5 earns 400.000 - 43.000 - 152.000
    assert c5["profit_per_unit"] == 205_000


def test_the_seller_pack_column_beats_the_name_and_vat_comes_out_of_the_margin():
    base = ProfitRules(sku_cost={"BOX": D(30_000), "BOX1": D(30_000)})
    set_pack = ProfitRules(
        sku_cost=dict(base.sku_cost), pack_count={"2001:v3": 4}, packaging_by_key={}
    )
    r3 = next(r for r in rows(set_pack) if r["variation_id"] == "v3")
    assert (r3["pack_count"], r3["pack_source"], r3["price_per_unit"]) == (4, "set", 67500)
    vat = ProfitRules(
        sku_cost=dict(base.sku_cost),
        vat_rate={"BOX": D("0.10"), "BOX1": D("0.10")},
        prices_include_vat=True,
        cost_includes_vat=False,
    )
    before = next(r for r in rows(base) if r["variation_id"] == "v1")
    after = next(r for r in rows(vat) if r["variation_id"] == "v1")
    assert after["margin_pct"] < before["margin_pct"]  # revenue = price / 1,1
    out = var.economics("2001", "Hộp", rows(vat), vat={"basis": "after_vat"})
    assert "VAT" in out["margin_basis"] and out["columns"][-1] == "margin_pct"


def test_no_cost_is_chua_tinh_never_the_one_third_fallback():
    rules = ProfitRules(sku_cost={"BOX": D(30_000)})  # BOX1 (Hộp lẻ) has no cost
    by = {r["variation_id"]: r for r in rows(rules)}
    assert by["v1"]["margin_pct"] is None and by["v1"]["profit_per_unit"] is None
    assert by["v1"]["margin_label"] == "chưa tính" and by["v1"]["has_cost"] is False
    assert "giá vốn" in by["v1"]["margin_reason"]
    assert by["v1"]["price_per_unit"] == 100000  # the price columns are still there
    out = var.economics("2001", "Hộp", list(by.values()), vat={})
    assert out["missing_cost"] == ["v1"]


def test_a_listing_without_variations_is_one_default_row_and_a_bom_costs_its_parts():
    plain = var.variation_rows(
        "7",
        None,
        [],
        rules=ProfitRules(product_cost={"7": D(10_000)}),
        schedule=SCHEDULE,
        on=date(2026, 10, 7),
        item_list_price=D(50_000),
        item_current_price=D(45_000),
    )
    assert len(plain) == 1 and plain[0]["variation_id"] == "" and plain[0]["name"] == "Mặc định"
    assert plain[0]["selling_price"] == 45000 and plain[0]["has_cost"] is True
    from juli_backend.services.shopee_profit.pack import Component

    bom = ProfitRules(
        sku_cost={"A": D(8_000), "B": D(2_000)},
        pack_components={"7": (Component("A", 2), Component("B", 3))},
    )
    row = var.variation_rows(
        "7",
        None,
        [],
        rules=bom,
        schedule=SCHEDULE,
        on=date(2026, 10, 7),
        item_list_price=D(50_000),
        item_current_price=D(50_000),
    )[0]
    assert row["sku_key"] == "bom:7" and row["has_cost"] is True


# ==================== B-4 co-purchase


def _ol(order, item):
    return OrderLine(order, item, item, date(2026, 10, 1), 1, D(1), D(1))


def test_co_purchase_counts_orders_that_held_both_and_skips_excluded():
    lines = [
        _ol("o1", "A"), _ol("o1", "B"),
        _ol("o2", "A"), _ol("o2", "B"), _ol("o2", "C"),
        _ol("o3", "A"), _ol("o3", "C"),
        _ol("o4", "B"),
    ]  # fmt: skip
    sets = copurchase.order_sets(lines)
    out = copurchase.suggestions(sets, "A", names={"A": "Ay", "B": "Bê", "C": "Xê"}, min_together=2)
    assert out["orders_with_anchor"] == 3 and out["orders_total"] == 4
    assert [(s["item_id"], s["together"]) for s in out["suggestions"]] == [("B", 2), ("C", 2)]
    b = out["suggestions"][0]
    assert b["share_of_anchor_orders"] == round(2 / 3, 4) and b["orders_with_partner"] == 3
    assert b["share_of_partner_orders"] == round(2 / 3, 4)
    hidden = copurchase.order_sets(lines, {"B": "khac"})
    assert (
        copurchase.suggestions(hidden, "A", names={}, min_together=2)["suggestions"][0]["item_id"]
        == "C"
    )
    assert copurchase.suggestions(sets, "A", names={}, min_together=3)["suggestions"] == []


# ==================== B-3 the estimate basis


def test_own_response_to_a_price_cut_needs_enough_days_and_orders():
    start = date(2026, 8, 1)
    days = [date.fromordinal(start.toordinal() + i) for i in range(60)]
    depth = {d: (0.2 if i % 3 == 0 else 0.0) for i, d in enumerate(days)}  # cut every third day
    orders = {d: (6 if depth[d] else 3) for d in days}  # twice the orders on cut days
    got = response.product_response(orders, depth, days[0], days[-1])
    assert got is not None and got.source == "product_history"
    assert got.discount_days == 20 and got.base_days == 40
    # twice the orders for a 20 % cut = +100 % / 20 = +5 % per 1 %; the band is below and above it
    assert got.per_pct_low < 0.05 < got.per_pct_high
    thin = {d: 0 for d in days}
    assert response.product_response(thin, depth, days[0], days[-1]) is None
    few_cuts = {d: (0.2 if i < 3 else 0.0) for i, d in enumerate(days)}
    assert response.product_response(orders, few_cuts, days[0], days[-1]) is None


def test_the_shops_other_products_stand_in_only_from_three_responses():
    one = DiscountResponse(0.01, 0.03, "product_history", 10, 20)
    assert response.shop_response({"a": one, "b": one}) is None
    pooled = response.shop_response(
        {
            "a": one,
            "b": DiscountResponse(0.02, 0.05, "product_history", 10, 20),
            "c": DiscountResponse(0.03, 0.07, "product_history", 10, 20),
        }
    )
    assert pooled is not None and pooled.source == "shop_products" and pooled.products == 3
    assert (pooled.per_pct_low, pooled.per_pct_high) == (0.02, 0.05)  # medians


def test_depth_by_day_follows_the_newest_snapshot():
    snaps = [
        (date(2026, 9, 1), D(100), D(100)),
        (date(2026, 9, 5), D(100), D(80)),
        (date(2026, 9, 8), D(100), D(100)),
    ]
    got = response.depth_by_day(snaps, date(2026, 8, 30), date(2026, 9, 9))
    assert date(2026, 8, 30) not in got  # before the first snapshot: unknown
    assert got[date(2026, 9, 3)] == 0 and round(got[date(2026, 9, 6)], 2) == 0.2
    assert got[date(2026, 9, 9)] == 0


async def test_the_basis_label_is_product_history_then_shop_then_prior_then_insufficient(
    session, shop
):
    ctx = await builder.build_context(
        session,
        shop.shop_id,
        [S(kind="product_discount", item_id="1001", variations=[{"discount_pct": 10}])],
        as_of=AS_OF,
        now=NOW,
    )
    spec = S(
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 20}],
    )
    prior, _ = builder.evaluate_version(ctx, spec, 0, NOW)
    assert prior["basis"]["key"] == "prior" and prior["basis"]["label"] == "ước tính chung"
    ctx.env.response_shop = DiscountResponse(0.01, 0.02, "shop_products", 30, 30, 4)
    shop_level, _ = builder.evaluate_version(ctx, spec, 0, NOW)
    assert shop_level["basis"]["key"] == "shop" and shop_level["basis"]["label"] == "của shop"
    ctx.env.response_by_item = {"1001": DiscountResponse(0.02, 0.04, "product_history", 12, 40)}
    own, _ = builder.evaluate_version(ctx, spec, 0, NOW)
    assert own["basis"]["key"] == "product_history"
    assert own["basis"]["label"] == "từ lịch sử sản phẩm"
    # the buyer pays 90.000 today; 80.000 is an 11,1 % cut, at +2..+4 % orders per 1 %: the range
    # is the product's own, not the preset elasticity
    lift = own["driver"]["relative_lift"]
    assert round(lift["p10"], 3) == 0.222 and round(lift["p90"], 3) == 0.444
    assert own["delta"]["orders"]["low"] < own["delta"]["orders"]["high"]
    # P96: hiding a selling listing loses its own last 30 days (product history, not "insufficient")
    hide, _ = builder.evaluate_version(ctx, S(kind="listing_hide", item_id="1003"), 1, NOW)
    assert hide["basis"]["key"] == "product_history"
    assert hide["delta"]["gmv"]["p50"] < 0


# ==================== the picker


async def test_the_picker_lists_every_active_listing_by_90_day_gmv(session, shop):
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    ids = [p["item_id"] for p in out["products"]]
    assert ids == ["1001", "1002", "1003"] and out["count"] == 3
    first = out["products"][0]
    assert first["orders_90d"] >= first["orders_30d"] >= 1
    assert first["gmv_90d"] >= out["products"][1]["gmv_90d"]
    assert (first["has_cost"], first["missing_cost_chip"]) == (True, None)
    assert out["window"]["days"] == 90 and out["excluded_hidden"] == 0
    by_orders = await builder.products(session, shop.shop_id, as_of=AS_OF, sort="orders_90d")
    assert [p["orders_90d"] for p in by_orders["products"]] == sorted(
        (p["orders_90d"] for p in by_orders["products"]), reverse=True
    )
    found = await builder.products(session, shop.shop_id, as_of=AS_OF, query="rửa chén")
    assert [p["item_id"] for p in found["products"]] == ["1002"]
    page = await builder.products(session, shop.shop_id, as_of=AS_OF, limit=1, offset=1)
    assert [p["item_id"] for p in page["products"]] == ["1002"] and page["count"] == 3
    with pytest.raises(ValueError):
        await builder.products(session, shop.shop_id, as_of=AS_OF, sort="rich")


async def test_the_picker_hides_excluded_unless_asked_and_flags_a_missing_cost(session, shop):
    session.add(rule(shop.shop_id, "excluded", "1002", True))
    session.add(rule(shop.shop_id, "exclude_reason", "1002", "phan_phoi"))
    await session.execute(
        delete(ShopRule).where(ShopRule.rule_key == "sku_cost", ShopRule.scope_ref == "T1")
    )
    await session.commit()
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    assert [p["item_id"] for p in out["products"]] == ["1001", "1003"]
    assert out["excluded_hidden"] == 1 and out["missing_cost_count"] == 1
    no_cost = next(p for p in out["products"] if p["item_id"] == "1003")
    assert (no_cost["has_cost"], no_cost["missing_cost_chip"]) == (False, "thiếu giá vốn")
    everything = await builder.products(session, shop.shop_id, as_of=AS_OF, include_excluded=True)
    flagged = next(p for p in everything["products"] if p["item_id"] == "1002")
    assert (flagged["excluded"], flagged["exclude_reason"]) == (True, "phan_phoi")


async def test_a_unlisted_catalogue_item_is_not_active(session, shop):
    assert builder.catalogue.is_active("NORMAL") and builder.catalogue.is_active(None)
    for status in ("UNLIST", "BANNED", "SELLER_DELETE", "Đã ẩn"):
        assert not builder.catalogue.is_active(status), status


# ==================== B-3/B-4 each kind


async def test_two_vouchers_compare_side_by_side_with_typed_numbers(session, shop):
    out = await evaluate(
        session,
        shop,
        {"kind": "voucher", "discount_type": "amount", "value": 5000, "min_spend": 100_000},
        {"kind": "voucher", "discount_type": "amount", "value": 10_000, "min_spend": 100_000},
    )
    a, b = out["versions"]
    assert a["ok"] and b["ok"] and a["driver"]["target_metric"] == "aov"
    # P98: the result's drivers (AOV + the visible-offer CTOR) and đơn
    assert [m["key"] for m in a["driver"]["metrics"]] == ["aov", "ctor", "orders"]
    da, db = a["details"], b["details"]
    assert da["qualifying_orders"] == db["qualifying_orders"] > 0  # same minimum spend
    assert da["total_orders"] > da["qualifying_orders"]
    assert db["voucher_cost_scenario"] == 2 * da["voucher_cost_scenario"]
    # P99: a voucher without dates keeps its OptionResult's 30-day horizon ("30 ngày đầu")
    assert b["cost"]["amount"] == 2 * a["cost"]["amount"] and a["cost"]["period_days"] == 30
    assert a["result"]["days"] == 30 and a["result"]["horizon"] == "first_30_days"
    # the shop's stored profit is partial (order lines cover 7 of 30 days): "chưa tính", never a
    # second calculation from the order lines
    assert b["result"]["estimable"] and b["margin_after_pct"] is not None
    be = a["break_even"]  # P96: a voucher pays back through the basket (AOV), not extra orders
    assert be["basis"] == "aov" and be["aov_needed"] > be["aov_now"]
    # the table puts them side by side: cost, deltas, margin, then each driver metric
    keys = [r["key"] for r in out["table"]["rows"]]
    assert keys[:5] == ["cost", "delta_gmv", "delta_orders", "delta_profit", "margin_after"]
    assert "driver:aov" in keys and "driver:ctor" in keys
    assert out["table"]["rows"][0]["values"] == [a["cost"]["amount"], b["cost"]["amount"]]
    assert out["saved"] is False and out["today"]["aov"]


async def test_a_voucher_from_zero_a_percent_cap_limits_and_the_four_kinds(session, shop):
    zero = await one(session, shop, kind="voucher", discount_type="amount", value=5000, min_spend=0)
    assert zero["details"]["qualifying_orders"] == zero["details"]["total_orders"]
    capped = await one(
        session, shop, kind="voucher", discount_type="pct", value=10, min_spend=0, max_value=3000
    )
    uncapped = await one(session, shop, kind="voucher", discount_type="pct", value=10, min_spend=0)
    assert capped["details"]["voucher_cost_scenario"] < uncapped["details"]["voucher_cost_scenario"]
    limited = await one(
        session,
        shop,
        kind="voucher",
        discount_type="amount",
        value=5000,
        usage_limit=1,
        per_buyer_limit=1,
    )
    assert limited["details"]["usage_limit"] == 1 and limited["details"]["usage_capped"] is True
    assert limited["details"]["per_user_limit"] == 1
    product = await one(
        session,
        shop,
        kind="voucher",
        scope="product",
        item_ids=["1001"],
        discount_type="amount",
        value=5000,
        min_spend=0,
    )
    assert product["details"]["total_orders"] < zero["details"]["total_orders"]
    for scope in ("follower", "livestream"):  # P96: refused until orders record the voucher type
        v = await one(
            session, shop, kind="voucher", scope=scope, discount_type="amount", value=5000
        )
        assert v["ok"] is False and v["refusal"]["code"] == "voucher_scope_no_data"


async def test_a_voucher_period_follows_the_dates(session, shop):
    v = await one(
        session,
        shop,
        kind="voucher",
        discount_type="amount",
        value=5000,
        start="2026-10-10",
        end="2026-10-16",
    )
    assert v["details"]["days"] == 7 and v["break_even"]["period_days"] == 7


async def test_an_add_on_deal_prices_each_add_on_and_the_attach_rate_that_pays_it_back(
    session, shop
):
    await add_baskets(session, shop, 4)
    v = await one(
        session,
        shop,
        kind="add_on",
        main_item_id="1001",
        addons=[
            {"item_id": "1002", "pct": 10, "limit_per_order": 2},
            {"item_id": "1003", "price": 40_000},
        ],
    )
    first, second = v["details"]["addons"]
    assert first["price_before"] == 54_000 and first["price_after"] == 48_600
    assert first["limit_per_order"] == 2 and second["price_after"] == 40_000
    assert first["margin_pct"] is not None and first["below_floor"] is False
    assert first["orders_with_both_today"] == 4  # the four baskets
    assert first["discount_cost_on_existing"] == 4 * 5_400
    need = first["break_even_extra_attaches"]
    assert need == -(-first["discount_cost_on_existing"] // first["profit_per_unit"])
    assert first["attach_rate_break_even"] > first["attach_rate_now"] > 0
    assert v["driver"]["target_metric"] == "aov"
    assert v["break_even"]["attach"][0]["extra_attaches"] == need
    # P96: the cost covers today's attaches and the ones the deal is expected to bring
    assert v["cost"]["amount"] >= first["discount_cost_on_existing"]
    low = await one(
        session,
        shop,
        kind="add_on",
        main_item_id="1001",
        addons=[{"item_id": "1002", "price": 20_000}],
    )
    assert low["breach"] is True and low["details"]["addons"][0]["below_floor"] is True
    nodata = await one(
        session, shop, kind="add_on", main_item_id="1001", addons=[{"item_id": "7777", "pct": 5}]
    )
    assert nodata["ok"] is False


async def test_a_gift_can_be_a_listing_or_a_typed_cost_and_the_trigger_is_buy_x_or_min_spend(
    session, shop
):
    typed = await one(
        session,
        shop,
        kind="gift",
        gift={"unit_cost": 5000, "label": "Móc khoá", "qty": 2},
        trigger={"type": "min_spend", "amount": 100_000},
    )
    g = typed["details"]["gift"]
    assert (g["typed_cost"], g["item_id"], g["stock"]) == (True, None, None)
    assert (
        g["cost_per_gift"] == 10_000
        and g["cost_per_gift"] * g["qualifying_orders"] == g["gift_cost_window"]
    )
    assert "tồn kho" in g["stock_note"] and typed["cost"]["amount"] == g["gift_cost_window"]
    listing = await one(
        session,
        shop,
        kind="gift",
        gift={"item_id": "1003", "qty": 1},
        trigger={"type": "buy_item", "item_id": "1001"},
    )
    lg = listing["details"]["gift"]
    assert lg["item_id"] == "1003" and lg["cost_per_gift"] == 16_000  # giá vốn + đóng gói
    assert lg["stock"] == 120 and lg["units_used_in_window"] == lg["qualifying_orders"]
    assert lg["stock_covers_window"] is True
    buy_only = [lg["qualifying_orders"], lg["total_orders"]]
    assert buy_only[0] == buy_only[1]  # every order of the scope holds a 1001
    assert listing["break_even"]["extra_orders"] == lg["break_even_extra_orders"]
    assert listing["driver"]["target_metric"] == "ctor"
    assert [m["key"] for m in listing["driver"]["metrics"]] == ["ctor", "orders"]
    assert listing["margin_after_pct"] < listing["margin_before_pct"]
    none = await one(
        session,
        shop,
        kind="gift",
        gift={"item_id": "5555"},
        trigger={"type": "min_spend", "amount": 1},
    )
    assert none["ok"] is False and none["refusal"]["code"] == "item_unknown:5555"


async def test_a_discount_per_variation_shows_margin_before_after_and_the_dates(session, shop):
    v = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "final_price": 80_000}],
        start="2026-10-10",
        end="2026-10-16",
        per_buyer_limit=2,
    )
    row = v["details"]["skus"][0]
    assert row["price_after"] == 80_000 and row["sku"] == "G1"
    assert row["margin_pct_after"] < row["margin_pct_before"]
    assert v["cost"]["period_days"] == 7 and v["cost"]["amount"] > 0
    assert v["driver"]["target_metric"] == "ctor" and v["basis"]["key"] == "prior"
    assert (
        v["break_even"]["extra_orders"] >= 1
        and v["break_even"]["ctor_needed"] > v["break_even"]["ctor_now"]
    )
    deep = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "final_price": 30_000}],
    )
    assert deep["breach"] is True and deep["warnings"][0]["type"] == "floor"
    above = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "final_price": 120_000}],
    )
    assert above["ok"] is False and above["refusal"]["code"] == "final_price_not_below_list"
    nothing = await one(session, shop, kind="product_discount", item_id="1001", variations=[])
    assert nothing["refusal"]["code"] == "variations_required"
    other = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "zzz", "discount_pct": 10}],
    )
    assert other["refusal"]["code"].startswith("variation_unknown")


async def test_price_and_flash_sale_share_the_economics(session, shop):
    up = await one(
        session,
        shop,
        kind="price",
        item_id="1001",
        variations=[{"variation_id": "", "change_pct": 5}],
    )
    to = await one(
        session,
        shop,
        kind="price",
        item_id="1001",
        variations=[{"variation_id": "", "final_price": 94_500}],
    )
    assert (
        up["details"]["skus"][0]["price_after"] == to["details"]["skus"][0]["price_after"] == 94_500
    )
    assert up["details"]["profit_delta_same_volume"] > 0 and up["cost"]["amount"] == 0
    flash = await one(
        session,
        shop,
        kind="flash_sale",
        item_id="1002",
        variations=[{"variation_id": "", "discount_pct": 20}],
        units=5,
        slot_hours=3,
    )
    assert flash["ok"] and flash["cost"]["period_days"] == 1
    assert flash["details"]["skus"][0]["price_after"] == 48_000
    nope = await one(session, shop, kind="flash_sale", item_id="1002", units=5)
    assert nope["refusal"]["code"] == "variations_required"


async def test_a_variation_set_prices_each_new_variation_and_saves_as_a_restructure(session, shop):
    v = await one(
        session,
        shop,
        kind="variation_set",
        item_id="1001",
        new_variations=[{"name": "Set 3", "price": 240_000}, {"name": "Set 5", "price": 380_000}],
    )
    sets = {r["name"]: r for r in v["details"]["new_variations"]}
    assert sets["Set 3"]["pack_count"] == 3 and sets["Set 3"]["price_per_unit"] == 80_000
    assert sets["Set 5"]["price_per_unit"] == 76_000
    assert sets["Set 3"]["margin_pct"] is not None and sets["Set 3"]["margin_label"] is None
    assert v["card_kind"] == "variation_restructure" and v["driver"]["target_metric"] == "aov"
    # ADR-122 d.10: a variation change drives AOV + CTOR (tagged prior), so đơn may move
    assert v["delta"]["orders"]["p50"] >= 0 and v["result"]["drivers"] == ["aov", "ctor"]
    assert v["delta"]["gmv"]["p50"] is not None and v["basis"]["key"] == "prior"


async def test_ads_levers_budget_roas_and_products(session, shop):
    camps = await builder.ads_campaigns(session, shop.shop_id, as_of=AS_OF, now=NOW)
    key = camps["campaigns"][0]["campaign_key"]
    assert camps["cap_rule"] == "daily_marketing_cap" and camps["daily_cap"] == 500_000
    assert camps["campaigns"][0]["products"] and camps["campaigns"][0]["roas_target"] == 3
    # P100 B.15 (owner 2026-11-13): edits of running campaigns are evaluated in Tự tạo phương án
    item = camps["campaigns"][0]["products"][0]["item_id"]
    for version in (
        {"lever": "budget", "campaign_key": key, "daily_budget": 150_000},
        {"lever": "roas", "campaign_key": key, "roas_target": 4.5},
        {"lever": "remove_product", "campaign_key": key, "item_id": item},
    ):
        v = await one(session, shop, kind="ads", **version)
        assert v["ok"] is True and v.get("refusal") is None, v.get("refusal")
        assert v["result_refusal"] is None, v["result_refusal"]
        ads = v["result"]["ads"]
        assert ads is not None and ads["lever"] == version["lever"]
        assert ads["spend"]["now"] is not None and ads["spend_text"]


def test_keyword_bids_are_not_a_lever_any_more():
    """P97 D85.17: Shopee's product-ads form has no keyword / bid field."""
    with pytest.raises(ValidationError) as refused:
        S(
            kind="ads",
            lever="keywords",
            item_id="1001",
            keywords=[{"keyword": "găng tay", "bid": 700}],
        )
    assert "keywords" in str(refused.value)


async def test_listing_levers_have_a_range_or_say_they_cannot(session, shop):
    from tests.unit.test_shopee_builder_drafts import _market

    await _market(session, shop.shop_id)  # the keyword volumes a title / first line is scored on
    await session.commit()
    title = await one(
        session,
        shop,
        kind="title",
        item_id="1001",
        title="Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc, găng tay dùng một lần",
        keywords=["găng tay"],
    )
    assert title["driver"]["target_metric"] == "views"
    assert [m["key"] for m in title["driver"]["metrics"]] == ["views", "ctr", "orders"]
    assert title["delta"]["gmv"]["high"] > title["delta"]["gmv"]["low"]
    cover = await one(
        session,
        shop,
        kind="cover_image",
        item_id="1001",
        overlay={
            "layout": "banner_bottom",
            "price_vnd": 90_000,
            "discount_pct": 10,
            "hook_text": "Dùng một lần",
        },
    )
    assert (
        cover["driver"]["target_metric"] == "ctr"
        and cover["details"]["overlay"]["layout"] == "banner_bottom"
    )
    assert cover["ok"] and cover["result"]["estimable"] is False  # measured after the run
    desc = await one(
        session,
        shop,
        kind="description_first_line",
        item_id="1001",
        first_line="Găng tay tự hủy sinh học, găng tay dùng một lần, đơn giá 90.000đ.",
    )
    assert desc["driver"]["target_metric"] == "ctor" and desc["ok"]
    display = await one(
        session, shop, kind="price_display", item_id="1001", text="Chỉ 3.000đ/chiếc"
    )
    # ADR-122 d.10: Hiển thị giá drives CTR on Thẻ sản phẩm only
    assert [m["key"] for m in display["driver"]["metrics"]] == ["ctr", "orders"]
    hide = await one(session, shop, kind="listing_hide", item_id="1003")
    relist = await one(session, shop, kind="listing_relist", item_id="1003", stock=40)
    assert hide["basis"]["key"] == "product_history"  # P96: the listing's own lost GMV
    assert relist["refusal"]["code"] == "listing_already_live"  # P96: 1003 is live, in stock
    assert hide["driver"]["metrics"][0]["key"] == "views"
    banned = await one(
        session,
        shop,
        kind="description_first_line",
        item_id="1001",
        first_line="Rẻ nhất thị trường!",
    )
    assert banned["ok"] is False and banned["refusal"]["code"] == "banned_term"


async def test_affiliate_commission_and_sample_cost(session, shop):
    v = await one(
        session,
        shop,
        kind="affiliate",
        item_id="1001",
        commission_pct=8,
        sample_qty=3,
        sample_ship_fee=20_000,
    )
    sample = v["cost"]["sample"]
    assert (
        sample["unit_cost"] == 31_000 and sample["total"] == 3 * 31_000 + 20_000
    )  # giá vốn + đóng gói + ship
    assert v["cost"]["amount"] >= sample["total"]
    # P99: the affiliate version has an OptionResult -- Lượt xem on Liên kết, cost and break-even
    assert v["driver"]["metrics"][0]["key"] == "views"
    assert v["result"]["estimable"] is False and v["result"]["cost"]["total"] >= sample["total"]
    target = await one(
        session, shop, kind="affiliate", item_id="1001", commission_pct=12, target_campaign=True
    )
    assert target["change_kind"] == "affiliate_target_campaign" and "sample" not in target["cost"]


# ==================== B-7 rules of the block


async def test_a_listing_without_cost_can_be_built_and_shows_chua_tinh(session, shop):
    await session.execute(
        delete(ShopRule).where(ShopRule.rule_key == "sku_cost", ShopRule.scope_ref == "G1")
    )
    await session.commit()
    v = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 20}],
    )
    assert v["ok"] and v["profit_status"] == "chua_tinh" and v["cost_known"] is False
    assert v["delta"]["profit"] == {"low": None, "p50": None, "high": None}
    assert v["margin_after_pct"] is None and v["delta"]["certain_profit"] is None
    assert v["delta"]["gmv"]["p50"] is not None  # GMV and orders are still shown
    assert any(w["type"] == "cost_unknown" and w["items"] == ["1001"] for w in v["warnings"])
    table = builder.table_of([v])
    assert next(r for r in table["rows"] if r["key"] == "delta_profit")["values"][0]["p50"] is None


async def test_an_ads_edit_can_be_chosen(session, shop):
    """P100 B.15: "Chọn" saves an edit of a running campaign as a card, its outcome carries the
    campaign's CPA facts (no 422 ``ads_edit_hidden`` any more)."""
    camps = await builder.ads_campaigns(session, shop.shop_id, as_of=AS_OF, now=NOW)
    spec = S(
        kind="ads",
        lever="budget",
        campaign_key=camps["campaigns"][0]["campaign_key"],
        daily_budget=190_000,
    )
    out = await builder.choose(
        session,
        shop.shop_id,
        [spec],
        0,
        primary=False,
        acknowledge_breaches=True,
        actor=manual.Actor("seller", shop.user.id),
        as_of=AS_OF,
        now=NOW,
    )
    assert out["card"]["change_kind"] == "ads_budget"
    assert out["outcome"]["ok"] and out["outcome"]["result"]["ads"]["lever"] == "budget"


async def test_an_excluded_listing_has_no_builder_entry(session, shop):
    session.add(rule(shop.shop_id, "excluded", "1001", True))
    session.add(rule(shop.shop_id, "exclude_reason", "1001", "khac"))
    await session.commit()
    v = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 20}],
    )
    assert v["ok"] is False and v["refusal"]["code"] == "item_excluded:1001"
    assert "Loại trừ sản phẩm" in v["refusal"]["message"]
    combo = await one(
        session,
        shop,
        kind="combo",
        discount_type="pct",
        tiers=[{"qty": 2, "value": 10}],
        item_ids=["1001", "1002"],
    )
    assert combo["refusal"]["code"] == "item_excluded:1001"
    partner = await one(
        session, shop, kind="add_on", main_item_id="1002", addons=[{"item_id": "1001", "pct": 5}]
    )
    assert partner["refusal"]["code"] == "item_excluded:1001"


# ==================== B-5 compare + choose


async def test_four_versions_of_mixed_kinds_compare_and_the_best_is_a_safe_one(session, shop):
    out = await evaluate(
        session,
        shop,
        {"kind": "voucher", "discount_type": "amount", "value": 5000, "min_spend": 100_000},
        {"kind": "voucher", "discount_type": "amount", "value": 10_000, "min_spend": 100_000},
        {
            "kind": "combo",
            "item_ids": ["1001", "1002"],
            "discount_type": "pct",
            "tiers": [{"qty": 2, "value": 10}],
        },
        {
            "kind": "gift",
            "gift": {"unit_cost": 5000},
            "trigger": {"type": "min_spend", "amount": 150_000},
        },
    )
    assert [v["kind"] for v in out["versions"]] == ["voucher", "voucher", "combo", "gift"]
    rows = {r["key"]: r["values"] for r in out["table"]["rows"]}
    assert len(rows["cost"]) == 4 and all(len(v) == 4 for v in rows.values())
    assert rows["driver:aov"][3] is None and all(v is not None for v in rows["driver:orders"])
    best = out["best_profit_p50"]
    assert best is not None and not out["versions"][best]["breach"]

    def p50(i):
        return out["versions"][i]["delta"]["profit"]["p50"]

    assert p50(best) == max(p50(i) for i in range(4) if p50(i) is not None)


async def test_a_refused_version_does_not_stop_the_others(session, shop):
    out = await evaluate(
        session,
        shop,
        {
            "kind": "voucher",
            "discount_type": "amount",
            "value": 5000,
            "scope": "product",
            "item_ids": ["1001"],
        },
        {"kind": "product_discount", "item_id": "1001", "variations": []},
    )
    ok, bad = out["versions"]
    assert ok["ok"] is True and bad["ok"] is False
    assert bad["refusal"] == {
        "code": "variations_required",
        "message": "Chọn phân loại và mức giảm.",
    }
    assert out["table"]["rows"][0]["values"][1] is None and out["best_profit_p50"] == 0


async def test_choose_saves_the_chosen_version_as_a_manual_card_with_the_others_as_versions(
    session, shop
):
    specs = [
        S(kind="voucher", discount_type="amount", value=5000, min_spend=100_000, label="5k/100k"),
        S(
            kind="voucher",
            discount_type="amount",
            value=10_000,
            min_spend=100_000,
            label="10k/100k",
        ),
        S(kind="gift", gift={"unit_cost": 5000}, trigger={"type": "min_spend", "amount": 150_000}),
    ]
    actor = manual.Actor("seller", shop.user.id)
    out = await builder.choose(
        session,
        shop.shop_id,
        specs,
        1,
        primary=True,
        acknowledge_breaches=False,
        actor=actor,
        as_of=AS_OF,
        now=NOW,
    )
    assert out["origin"] == "manual" and out["status"] == "sent" and out["code"].startswith("JC-")
    assert [v["index"] for v in out["versions"]] == [1, 0, 2]  # chosen first
    assert out["versions"][0]["label"] == "10k/100k" and out["versions"][0]["chosen"] is True
    assert out["card"]["change_kind"] == "min_spend_voucher"
    assert (
        out["card"]["inputs"]["value"] == 10_000 and out["card"]["inputs"]["min_spend"] == 100_000
    )
    assert out["outcome"]["label"] == "10k/100k" and out["outcome"]["ok"]
    proposal = await session.get(ShopProposal, uuid.UUID(out["id"]))
    assert proposal.status == "sent"


async def test_choosing_a_breaching_version_needs_the_acknowledgement(session, shop):
    specs = [
        S(
            kind="product_discount",
            item_id="1001",
            variations=[{"variation_id": "", "final_price": 30_000}],
        ),
        S(kind="voucher", discount_type="amount", value=5000),
    ]
    actor = manual.Actor("seller", shop.user.id)
    with pytest.raises(manual.BreachNotAcknowledged) as refused:
        await builder.choose(
            session,
            shop.shop_id,
            specs,
            0,
            primary=False,
            acknowledge_breaches=False,
            actor=actor,
            as_of=AS_OF,
            now=NOW,
        )
    assert refused.value.breaches[0]["type"] == "floor"
    assert (await session.scalars(select(ShopProposal))).first() is None
    ok = await builder.choose(
        session,
        shop.shop_id,
        specs,
        0,
        primary=False,
        acknowledge_breaches=True,
        actor=actor,
        as_of=AS_OF,
        now=NOW,
    )
    assert ok["card"]["acknowledged_breaches"]["breaches"][0]["type"] == "floor"


async def test_choosing_a_version_that_cannot_be_built_is_refused_and_a_bad_sibling_is_kept(
    session, shop
):
    actor = manual.Actor("seller", shop.user.id)
    specs = [
        S(kind="product_discount", item_id="1001", variations=[]),
        S(kind="voucher", discount_type="amount", value=5000),
    ]
    with pytest.raises(manual.ProposalError) as bad:
        await builder.choose(
            session,
            shop.shop_id,
            specs,
            0,
            primary=False,
            acknowledge_breaches=False,
            actor=actor,
            as_of=AS_OF,
            now=NOW,
        )
    assert bad.value.code == "reco_manual_invalid"
    out = await builder.choose(
        session,
        shop.shop_id,
        specs,
        1,
        primary=False,
        acknowledge_breaches=False,
        actor=actor,
        as_of=AS_OF,
        now=NOW,
    )
    refused = next(v for v in out["versions"] if v["index"] == 0)
    assert refused["status"] == "refused"


async def test_a_variation_set_is_saved_as_a_restructure_card_with_its_sheet(session, shop):
    specs = [
        S(
            kind="variation_set",
            item_id="1001",
            new_variations=[{"name": "Set 3", "price": 240_000}],
        ),
    ]
    out = await builder.choose(
        session,
        shop.shop_id,
        specs,
        0,
        primary=False,
        acknowledge_breaches=False,
        actor=manual.Actor("seller", shop.user.id),
        as_of=AS_OF,
        now=NOW,
    )
    assert out["card"]["change_kind"] == "variation_restructure"
    assert out["card"]["inputs"]["variations"][0]["name"] == "Set 3"
    assert out["card"]["execution_sheet"]["steps"]


# ==================== traffic


def test_the_break_even_ctor_is_orders_over_the_same_clicks():
    t = traffic.Traffic(orders=30, clicks=1000, views=20_000, window_days=30)
    assert (t.ctor, t.ctr) == (0.03, 0.05)
    got = traffic.break_even_ctor(t, 18, 30)
    assert got["ctor_now"] == 3.0 and got["ctor_needed"] == 4.8  # (30 + 18) / 1000
    half = traffic.break_even_ctor(t, 3, 14)  # a 14-day voucher: 14 / 30 of the pace
    assert half["orders_base"] == 14.0 and half["clicks_base"] == 467
    assert half["ctor_needed"] == pytest.approx((14 + 3) / (1000 * 14 / 30) * 100, abs=0.001)
    assert traffic.break_even_ctor(None, 1, 30)["reason"] == "no_flow_data"
    assert traffic.break_even_ctor(traffic.Traffic(5, 0, 0, 30), 1, 30)["reason"] == "no_clicks"
    assert outcome.BASIS_LABELS["shop"] == "của shop"


async def test_the_loader_derives_a_products_own_response_from_90_days_of_orders_and_prices(
    session, shop
):
    from datetime import timedelta

    from juli_backend.models.shopee_profit import PlatformItemSnapshot
    from tests.support.shopee_analytics import snapshot

    await session.execute(
        delete(PlatformItemSnapshot).where(PlatformItemSnapshot.item_id == "1001")
    )
    start = date(2026, 7, 9)
    n = 2000
    for i in range(91):
        day = start + timedelta(days=i)
        cut = i % 3 == 0
        for _ in range(6 if cut else 3):  # twice the orders on the days the price was cut 20 %
            n += 1
            session.add(
                _line(shop.shop_id, n, day, "G1", original=100_000, deal=80_000 if cut else 100_000)
            )
        stamp = datetime(day.year, day.month, day.day)
        session.add(
            snapshot(
                shop.shop_id, "1001", captured_at=stamp,
                list_price=D(100_000), current_price=D(80_000 if cut else 100_000),
            )
        )  # fmt: skip
    await session.commit()
    await materialize.backfill_shop(session, shop.shop_id)  # P99b: the ingest hook's rows
    await session.commit()
    spec = S(
        kind="product_discount", item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 30}],
    )  # fmt: skip
    ctx = await builder.build_context(session, shop.shop_id, [spec], as_of=AS_OF, now=NOW)
    got = ctx.env.response_by_item["1001"]
    assert got.source == "product_history" and got.discount_days >= 25 and got.base_days >= 50
    assert got.per_pct_low < 0.05 < got.per_pct_high  # +100 % orders for a 20 % cut
    assert ctx.env.response_shop is None  # one product with a response is not "the shop's others"
    out, _ = builder.evaluate_version(ctx, spec, 0, NOW)
    assert out["basis"]["key"] == "product_history"
    assert out["basis"]["detail"] == "Đơn của chính sản phẩm khi từng giảm giá trước đây."
    # the seller already sells at 90.000; 70.000 is a 22 % cut and the range is the product's own
    lift = out["driver"]["relative_lift"]
    assert lift["p10"] > 0 and lift["p90"] > lift["p10"]


def test_removed_kinds_cannot_be_created_from_the_builder_but_their_specs_still_parse():
    """P100: hide, relist and listing combo left the builder; stored cards of them still rebuild."""
    from pydantic import ValidationError

    from juli_backend.api.routes import shopee_builder_common as common

    hide = {"kind": "listing_hide", "item_id": "1003"}
    relist = {"kind": "listing_relist", "item_id": "1003"}
    combo = {
        "kind": "listing_combo",
        "title": "Combo",
        "price": 120000,
        "stock": 5,
        "member_ids": ["1001", "1002"],
    }
    for body in (common.EvaluateBody, common.ChooseBody, common.GroupBody):
        for raw in (hide, relist, combo):
            extra = {"members": [0]} if body is common.GroupBody else {}
            with pytest.raises(ValidationError):
                body.model_validate({"versions": [raw], **extra})
    with pytest.raises(ValidationError):
        common.CompareBody.model_validate({"versions": [hide, relist]})
    assert common.EvaluateBody.model_validate(
        {"versions": [{"kind": "price_display", "item_id": "1003"}]}
    )
    assert S(**hide).kind == "listing_hide"
