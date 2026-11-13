"""P98 W3-H: every builder evaluation is ONE calculation -- the stored funnel base, the family's
``OptionInput``, ``engine.run`` -> ``result`` -- and the old view (``before_after``, ``delta``) is
laid out from it. ADR-122 d.1-d.13. Pure tests first (E2 / E3, the hidden Ads edits), then the
synthetic reco shop (``tests/support/shopee_reco``, SQLite, invented figures) end to end.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.engine.contract import Band
from juli_backend.services.shopee_builder.engine_families import (
    FamilyRefused,
    adapters,
    common,
    integrate,
    option_for,
)
from juli_backend.services.shopee_builder.engine_families.facts import (
    ListingComboFacts,
    PackEvidence,
)
from juli_backend.services.shopee_builder.engine_families.families import (
    listing_combo_option,
    voucher_option,
)
from juli_backend.services.shopee_profit.order_profit import OrderLine
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_builder import NOW, S

B = "/v1/demo/shopee/builder"


def line(order, qty, price, item="i1", sku=None):
    return OrderLine(order, sku or f"{item}-sku", item, date(2026, 10, 5), qty, D(price), D(price))


def fake_env(lines):
    pairs = [
        (ln, SimpleNamespace(contribution=ln.order_value * D("0.2"), excluded_reason=None))
        for ln in lines
    ]
    return SimpleNamespace(
        lines_for=lambda items: lines, view=SimpleNamespace(pairs=pairs), usage_rate=None
    )


# ==================== E2: reach measured from the order lines


def _voucher_lines(n_near, n_far, n_over):
    out = []
    for i in range(n_near):
        out.append(line(f"n{i}", 1, 90_000))  # within 20 % below 100.000
    for i in range(n_far):
        out.append(line(f"f{i}", 1, 40_000))  # far below
    for i in range(n_over):
        out.append(line(f"o{i}", 1, 120_000))
    return out


def test_e2_the_voucher_reach_is_the_share_of_orders_within_20_pct_below_the_minimum():
    spec = sp.VoucherSpec(kind="voucher", discount_type="amount", value=5000, min_spend=100_000)
    f = adapters.voucher_facts(spec, fake_env(_voucher_lines(10, 20, 10)))  # 40 orders
    assert f.reach is not None and f.reach.p50 == D(10) / D(40)  # the near orders, measured
    assert f.reach.p10 <= f.reach.p50 <= f.reach.p90 <= f.below_share
    assert f.reach_gap == D(10_000) and f.near_share == D(10) / D(40)
    o = voucher_option(spec, f)
    aov = o.drivers[0]
    assert aov.metric == "aov" and aov.basis == "measured"
    assert aov.lift is not None and aov.lift.p50 == f.reach.p50 * D(10_000) / f.aov_now
    # the uses: today's qualifying orders + the near ones that reach the minimum
    assert o.offers[0].use_share.p50 == f.qualifying_share + f.reach.p50
    assert o.drivers[1].metric == "ctor" and o.drivers[1].basis == "prior"  # E1


def test_e2_too_few_orders_keeps_the_tagged_prior_on_the_near_orders():
    spec = sp.VoucherSpec(kind="voucher", discount_type="amount", value=5000, min_spend=100_000)
    f = adapters.voucher_facts(spec, fake_env(_voucher_lines(2, 3, 2)))  # 7 orders
    assert f.reach is None
    o = voucher_option(spec, f)
    aov = o.drivers[0]
    assert aov.basis == "prior" and aov.lift is not None
    r_lo, r_mid, r_hi = common.REACH
    assert aov.lift.p50 == r_mid * f.near_share * f.reach_gap / f.aov_now
    # a far-below basket never counts: the gap is the near orders' only
    assert f.reach_gap == D(10_000)


def test_e2_nobody_near_a_minimum_gains_nothing():
    spec = sp.VoucherSpec(kind="voucher", discount_type="amount", value=5000, min_spend=10_000_000)
    o = voucher_option(spec, adapters.voucher_facts(spec, fake_env(_voucher_lines(5, 5, 5))))
    assert [d.metric for d in o.drivers] == ["aov"]  # no CTOR: nobody can use it
    assert o.drivers[0].lift == Band(D(0), D(0), D(0))
    assert o.offers[0].use_share.p50 == 0


def test_e2_the_combo_reach_is_measured_on_orders_within_reach_of_the_tier():
    lines = [line(f"a{i}", 1, 50_000) for i in range(20)]  # one unit under tier 2
    # already at tier 2, under a past combo (B.10: reach is measured once the shop ran one)
    lines += [replace(line(f"b{i}", 2, 50_000), bundle_discount=D(10_000)) for i in range(10)]
    lines += [line(f"c{i}", 1, 30_000, item="other") for i in range(5)]
    spec = sp.ComboSpec(
        kind="combo", item_ids=["i1"], discount_type="pct", tiers=[sp.ComboTier(qty=2, value=10)]
    )
    f = adapters.combo_facts(spec, fake_env(lines))
    assert f.reach is not None and f.reach.p50 == D(20) / D(35) and f.reach_units == 1
    o = option_for(spec, cast(Any, SimpleNamespace(env=fake_env(lines))))
    aov = o.drivers[0]
    assert aov.basis == "measured" and aov.lift is not None
    assert aov.lift.p50 == f.reach.p50 * f.unit_price / f.aov_now


# ==================== E3: a new combo listing


def _facts(**kw):
    d = dict(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        switch_share=D("0.1"),
        value_now=D(150_000),
        new_price=D(140_000),
        profit_per_order_after=None,
        pack=PackEvidence(D(3000), 30, D("0.05"), D("0.04"), D(140_000), D(30_000)),
    )
    d.update(kw)
    return ListingComboFacts(**d)


LISTING = sp.ListingComboSpec(
    kind="listing_combo", title="Hộp 3", price=140_000, stock=5, member_ids=["a", "b"]
)


def test_e3_a_pack_size_the_shop_does_not_sell_adds_orders_from_the_matching_variation():
    o = listing_combo_option(LISTING, _facts())
    added = [d for d in o.drivers if d.added is not None]
    assert len(added) == 1 and added[0].metric == "views" and added[0].basis == "measured"
    assert added[0].added is not None and added[0].added.ctor == D("0.04")


def test_e3_a_pack_size_the_shop_already_sells_is_switching_only():
    o = listing_combo_option(LISTING, _facts(pack_sold_today=True))
    assert [d.metric for d in o.drivers] == ["aov"] and all(d.added is None for d in o.drivers)
    assert o.note == common.NOTE_PACK_SOLD


def test_e3_a_combo_dearer_than_today_gives_nobody_a_reason_to_switch():
    o = listing_combo_option(LISTING, _facts(new_price=D(200_000), pack=None))
    assert o.drivers[0].lift == Band(D(0), D(0), D(0))


def test_e3_pack_sold_today_reads_the_variation_pack_counts():
    rows = [{"pack_count": 1}, {"pack_count": 3}]
    assert integrate.pack_sold_today(rows, 1, 3) is True
    assert integrate.pack_sold_today(rows, 1, 5) is False


# ==================== hidden Ads edits


def test_the_ads_edit_kinds_are_refused_hidden_by_the_family():
    spec = sp.AdsSpec(kind="ads", lever="budget", campaign_key="c", daily_budget=150_000)
    with pytest.raises(FamilyRefused) as refused:
        option_for(spec, BuilderContext(env=cast(Any, SimpleNamespace())))
    assert refused.value.hidden and integrate.hidden(spec)


def test_a_stable_seed_per_version():
    a = S(kind="title", item_id="1001", title="Găng tay")
    b = S(kind="title", item_id="1001", title="Găng tay")
    c = S(kind="title", item_id="1001", title="Găng tay xanh")
    assert integrate.seed_of(a.model_dump(mode="json")) == integrate.seed_of(
        b.model_dump(mode="json")
    )
    assert integrate.seed_of(a.model_dump(mode="json")) != integrate.seed_of(
        c.model_dump(mode="json")
    )


# ==================== end to end on the synthetic shop


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


async def evaluate(session, shop, *versions):
    specs = [S(**v) for v in versions]
    return await builder.evaluate_versions(session, shop.shop_id, specs, as_of=AS_OF, now=NOW)


def assert_funnel_holds(result):
    """ADR-122 d.11.1: in every column Lượt xem × CTR × CTOR = Đơn and Đơn × AOV = GMV."""
    for name in ("before", "low", "likely", "high"):
        c = result["detail"][name]
        if c is None:
            continue
        if c["views"]:
            got = c["views"] * c["ctr"] / 100 * c["ctor"] / 100
            assert got == pytest.approx(c["orders"], abs=1), name
        if c["orders"]:
            assert c["orders"] * c["aov"] == pytest.approx(c["gmv"], abs=1), name


def assert_one_calculation(v):
    """``delta`` and ``before_after`` show exactly the numbers of ``result``."""
    r = v["result"]
    rows = {row["key"]: row for row in v["before_after"]["rows"]}
    assert v["before_after"]["source"] == "result"
    before = r["detail"]["before"]
    assert rows["gmv"]["before"] == before["gmv"] and rows["orders"]["before"] == before["orders"]
    if not r["estimable"]:
        assert v["delta"]["gmv"]["p50"] is None and rows["gmv"]["after"] is None
        return
    likely = r["detail"]["likely"]
    assert v["delta"]["gmv"]["p50"] == r["delta"]["gmv"]["value"]
    assert v["delta"]["gmv"]["p50"] == round(rows["gmv"]["after"]["p50"] - rows["gmv"]["before"])
    assert v["delta"]["orders"]["p50"] == pytest.approx(r["delta"]["orders"]["value"])
    assert rows["orders"]["after"]["p50"] == pytest.approx(likely["orders"])
    if r["delta"]["profit"] is not None and v["cost_known"]:
        assert v["delta"]["profit"]["p50"] == r["delta"]["profit"]["value"]
        assert v["delta"]["profit"]["low"] == r["delta"]["profit"]["low"]
        assert v["delta"]["profit"]["high"] == r["delta"]["profit"]["high"]
    assert_funnel_holds(r)


FAMILIES = [
    {
        "kind": "voucher",
        "discount_type": "amount",
        "value": 5000,
        "min_spend": 100_000,
        "scope": "product",
        "item_ids": ["1001"],
    },
    {"kind": "voucher", "discount_type": "amount", "value": 5000},  # shop-wide
    {
        "kind": "combo",
        "item_ids": ["1001", "1002"],
        "discount_type": "pct",
        "tiers": [{"qty": 2, "value": 10}],
    },
    {
        "kind": "product_discount",
        "item_id": "1001",
        "variations": [{"variation_id": "", "discount_pct": 20}],
    },
    {"kind": "title", "item_id": "1001", "title": "Găng tay tự hủy sinh học hộp 100 chiếc"},
    {"kind": "cover_image", "item_id": "1001", "overlay": {"layout": "banner_bottom"}},
    {
        "kind": "gift",
        "gift": {"unit_cost": 5000},
        "trigger": {"type": "buy_item", "item_id": "1001"},
    },
    {"kind": "add_on", "main_item_id": "1001", "addons": [{"item_id": "1002", "pct": 10}]},
    {"kind": "listing_hide", "item_id": "1003"},
]


@pytest.mark.parametrize("version", FAMILIES, ids=lambda v: v["kind"])
async def test_every_family_returns_one_result_and_the_old_view_shows_its_numbers(
    session, shop, version
):
    out = await evaluate(session, shop, version)
    v = out["versions"][0]
    assert v["ok"], v.get("refusal")
    r = v["result"]
    assert r is not None and r["kind"] and r["days"] >= 1
    assert set(r) >= {"delta", "detail", "cost", "per_30d", "after", "build_up", "drivers_pct"}
    assert_one_calculation(v)
    assert out["compare"] == [0]


async def test_a_shop_wide_voucher_stands_on_the_shop_funnel(session, shop):
    out = await evaluate(session, shop, FAMILIES[1], FAMILIES[0])
    shop_wide, product = out["versions"]
    assert shop_wide["before_after"]["scope"] == "shop"
    assert product["before_after"]["scope"] == "product"
    assert (
        shop_wide["result"]["detail"]["before"]["orders"]
        > product["result"]["detail"]["before"]["orders"]
    )


async def test_the_compare_order_follows_per_30_day_profit(session, shop):
    out = await evaluate(session, shop, *FAMILIES[2:5])
    order = out["compare"]
    assert sorted(order) == [0, 1, 2]
    values = [out["versions"][i]["result"]["per_30d"]["profit"] for i in order]
    known = [x for x in values if x is not None]
    assert known == sorted(known, reverse=True)


async def test_several_targets_sum_their_own_results(session, shop):
    out = await evaluate(
        session, shop, {"kind": "product_discount", "discount_pct": 20, "targets": ["1001", "1002"]}
    )
    v = out["versions"][0]
    rows = v["targets"]
    assert all(row["result"] is not None for row in rows)
    likely = sum(row["result"]["detail"]["likely"]["gmv"] for row in rows)
    assert v["result"]["detail"]["likely"]["gmv"] == pytest.approx(likely)
    assert_one_calculation(v)


async def test_an_ads_edit_is_refused_with_a_clear_code(session, shop):
    out = await evaluate(
        session, shop, {"kind": "ads", "lever": "budget", "campaign_key": "x", "daily_budget": 1}
    )
    v = out["versions"][0]
    assert v["ok"] is False and v["refusal"]["code"] == "ads_edit_hidden"


async def test_the_variations_route_carries_both_margins(session, shop):
    out = await builder.product_variations(session, shop.shop_id, "1001", as_of=AS_OF, now=NOW)
    assert "final_margin_pct" in out["columns"]
    row = out["variations"][0]
    assert row["margin_pct"] is not None and row["final_margin_pct"] is not None
    assert row["final_margin_pct"] <= row["margin_pct"]
    assert row["final_margin_basis"] in ("variation", "product")


async def test_the_cards_env_reads_the_stored_funnel(session, shop):
    from juli_backend.services.shopee_recommendations import loader

    env = await loader.load_env(session, shop.shop_id, as_of=AS_OF, now=NOW)
    assert env is not None and env.view.data.funnel is not None
    assert env.view.data.funnel.available


# ==================== the P98 builder routes


@pytest.fixture
async def seller(session, shop):
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def test_combo_rows_carry_a_result_and_the_compare_order(seller):
    body = (
        await seller.post(
            f"{B}/combo/options",
            json={
                "products": [{"item_id": "1001", "variation_ids": [""]}],
                "pack_sizes": [3, 5],
                "as_of": AS_OF.isoformat(),
            },
        )
    ).json()
    rows = body["rows"]
    assert rows and all(row["result"] is not None for row in rows)
    assert sorted(body["compare"]) == sorted(row["key"] for row in rows)
    for row in rows:
        r = row["result"]
        assert r["kind"] == "listing_combo" and r["horizon"] == "first_30_days"
        assert_funnel_holds(r)


async def test_ads_and_kol_setups_carry_a_result(seller):
    setup = {
        "campaign": "single",
        "item_ids": ["1001"],
        "daily_budget": 150_000,
        "start_date": "2026-10-10",
        "end_date": "2026-10-16",
    }
    body = (
        await seller.post(f"{B}/ads/setup", json={"setups": [setup], "as_of": AS_OF.isoformat()})
    ).json()
    r = body["setups"][0]["result"]
    assert r["kind"] == "ads_new_campaign" and r["days"] == 7 and body["compare"] == [0]
    # ADR-122 d.8: the cost is exact (the budget, Shopee-optimised) whether or not it is estimable
    assert r["cost"]["total"] == pytest.approx(150_000 * 7)
    if not r["estimable"]:
        assert r["delta"]["profit"] is None and "cần chạy thử" in r["delta"]["orders"]["note"]
