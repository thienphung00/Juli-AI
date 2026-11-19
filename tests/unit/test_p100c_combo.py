"""P100-C: Combo Khuyến Mãi in Shopee's exact shape, offer costs inside the ``OptionResult``,
ROI = ΔGMV ÷ chi phí, combo reach that cannot be measured stays empty (B.9, B.10, A.9, B.4, B.6).
Synthetic numbers only."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import (
    WIRE_KEYS,
    Band,
    FunnelBase,
    MarginBasis,
    OfferCost,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.common import (
    NOTE_COMBO_REACH,
    FamilyRefused,
)
from juli_backend.services.shopee_builder.engine_families.facts import (
    ComboFacts,
    LiftEvidence,
    PriceFacts,
    SimpleFacts,
)
from juli_backend.services.shopee_builder.engine_families.families import (
    combo_option,
    price_option,
    simple_option,
)
from juli_backend.services.shopee_profit.order_profit import OrderLine


def b(a, m, c):
    return Band(D(str(a)), D(str(m)), D(str(c)))


def src(key, views, clicks, orders, gmv, profit):
    return SourceFunnel(key, D(views), D(clicks), D(orders), D(gmv), D(profit))


def base():
    return FunnelBase(
        "shop-1",
        "products",
        ("i1",),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, 20_000_000, 4_000_000),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000),
            SourceFunnel("chenh_lech_nguon", None, None, D(5), D(500_000), D(100_000)),
        ),
        D("0.3"),
    )


def line(order, qty, price, item="i1"):
    return OrderLine(order, f"{item}-sku", item, date(2026, 10, 5), qty, D(price), D(price))


def fake_env(lines):
    pairs = [
        (ln, SimpleNamespace(contribution=ln.order_value * D("0.2"), excluded_reason=None))
        for ln in lines
    ]
    return SimpleNamespace(
        lines_for=lambda items: lines, view=SimpleNamespace(pairs=pairs), usage_rate=None
    )


def combo(dtype, tiers, **kw):
    return sp.ComboSpec(
        kind="combo",
        item_ids=["i1"],
        discount_type=dtype,
        tiers=[sp.ComboTier(qty=q, value=v) for q, v in tiers],
        **kw,
    )


# -- each Loại Combo -> an effective % per tier ---------------------------------------------------


@pytest.mark.parametrize(
    ("dtype", "tiers", "expected"),
    [
        ("pct", [(2, 5), (3, 8)], [D(5), D(8)]),
        # số tiền: amount ÷ (N × đơn giá) -- 20.000 off 2 × 100.000 = 10 %, 45.000 off 3 = 15 %
        ("amount", [(2, 20_000), (3, 45_000)], [D(10), D(15)]),
        # giá đặc biệt: 1 − giá ÷ (N × đơn giá) -- 180.000 for 2 = 10 %, 240.000 for 3 = 20 %
        ("special_price", [(2, 180_000), (3, 240_000)], [D(10), D(20)]),
    ],
)
def test_each_combo_type_becomes_an_effective_pct_per_tier(dtype, tiers, expected):
    spec = combo(dtype, tiers)
    got = adapters.effective_tiers(spec, D(100_000))
    assert [q for q, _ in got] == [q for q, _ in tiers]
    assert [round(p, 6) for _, p in got] == expected


@pytest.mark.parametrize(
    ("dtype", "tiers"),
    [
        ("pct", [(2, 10), (3, 5)]),  # 3 units for less than 2
        ("pct", [(2, 10), (3, 10)]),  # the same % twice
        ("amount", [(2, 20_000), (4, 30_000)]),  # 10.000 / unit then 7.500 / unit
        ("special_price", [(2, 180_000), (3, 280_000)]),  # 90.000 / unit then 93.333 / unit
    ],
)
def test_tiers_that_do_not_increase_are_refused(dtype, tiers):
    with pytest.raises(ValidationError, match="mức ưu đãi sau"):
        combo(dtype, tiers)


def test_a_tier_at_or_above_100_pct_or_at_or_below_0_is_refused():
    with pytest.raises(FamilyRefused) as over:
        adapters.effective_tiers(combo("amount", [(2, 200_000)]), D(100_000))  # 100 %
    assert over.value.code == "combo_discount_over_max" and over.value.text
    with pytest.raises(FamilyRefused) as none:
        adapters.effective_tiers(combo("special_price", [(2, 200_000)]), D(100_000))  # 0 %
    assert none.value.code == "combo_price_not_below_value" and none.value.text


def test_combo_facts_refuse_a_bad_tier_instead_of_raising_a_bare_error():
    lines = [line("o1", 2, 50_000)]
    with pytest.raises(FamilyRefused):
        adapters.combo_facts(combo("amount", [(2, 150_000)]), fake_env(lines))


# -- Thời gian chạy Combo with the hour ---------------------------------------------------------


def test_combo_time_carries_the_hour():
    spec = combo(
        "pct",
        [(2, 5)],
        start=date(2026, 11, 11),
        start_hour=10,
        end=date(2026, 11, 12),
        end_hour=22,
    )
    assert spec.days == 2  # 36 hours -> 2 days
    assert combo("pct", [(2, 5)], start=date(2026, 11, 11), end=date(2026, 11, 14)).days == 4
    with pytest.raises(ValidationError):
        combo(
            "pct",
            [(2, 5)],
            start=date(2026, 11, 11),
            start_hour=10,
            end=date(2026, 11, 11),
            end_hour=9,
        )
    with pytest.raises(ValidationError):
        combo("pct", [(2, 5)], start_hour=10)  # an hour needs its date
    with pytest.raises(ValidationError):
        combo("pct", [(2, 5)], start=date(2026, 11, 11), start_hour=24)


# -- combo reach that cannot be measured stays empty (B.10) -------------------------------------


def unmeasured_facts(**kw):
    d = dict(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        per_use=D(4000),
        use_share_now=D("0.15"),
        near_share=D("0.3"),
        unit_price=D(50_000),
        reach=None,
    )
    d.update(kw)
    return ComboFacts(**d)


def test_unmeasured_combo_reach_is_cost_and_break_even_only():
    o = combo_option(combo("pct", [(2, 5), (3, 10)]), unmeasured_facts())
    assert all(d.basis == "not_estimable" for d in o.drivers)
    assert all(d.basis != "prior" for d in o.drivers)
    assert o.offers[0].use_share == Band(D("0.15"), D("0.15"), D("0.15"))
    r = run(base(), o, n=200)
    j = r.json()
    assert not r.estimable and j["basis_weak"] is False
    assert j["delta"]["profit"] is None
    # cost = the buyers who already qualify × the tier's discount over 30 days
    assert float(r.cost_total) == pytest.approx(255 * 0.15 * 4000)
    assert j["cost"]["break_even_orders"] is not None
    assert any("chưa ước tính được" in n for n in r.notes)
    assert not any("ước tính chung" in n for n in r.notes)


def test_measured_combo_reach_still_estimates():
    facts = unmeasured_facts(reach=b(0.1, 0.2, 0.3))
    o = combo_option(combo("pct", [(2, 5)]), facts)
    assert o.drivers[0].metric == "aov" and o.drivers[0].basis == "measured"
    assert run(base(), o, n=200).estimable


def test_combo_cost_per_use_when_no_order_reaches_a_tier_today():
    lines = [line(f"o{i}", 1, 50_000) for i in range(40)]  # nobody at tier 2 yet
    f = adapters.combo_facts(combo("pct", [(2, 10), (3, 20)]), fake_env(lines))
    assert f.use_share_now == 0
    # an order moving up to the lowest tier gets 2 × 50.000 × 10 %
    assert f.per_use == D(10_000)


# -- Mua kèm / Quà tặng: the offer cost is inside the OptionResult (A.9) ------------------------


def test_gift_offer_from_the_evaluator_certain_layer():
    certain = {"gift": {"cost_per_gift": 12_000, "qualifying_orders": 30, "total_orders": 120}}
    offer = adapters.gift_offer(certain)
    assert offer is not None
    assert offer.per_use == D(12_000) and offer.use_share.p50 == D("0.25")
    assert offer.label == "quà tặng"


def test_add_on_offer_follows_the_attach_lift():
    certain = {
        "main_orders": 100,
        "aov_now": 200_000,
        "attach_value_per_order": 50_000,  # add-on GMV per main order if every order took it
        "discount_per_attach_gmv": 0.2,  # 10.000đ discount per full attach
        "discount_cost_on_existing": 100_000,  # 10 attaches today
    }
    offer = adapters.add_on_offer(certain, b(0.0, 0.025, 0.05))
    assert offer is not None
    assert offer.per_use == D(10_000)
    assert offer.use_share.p10 == D("0.1")  # today's attaches
    # + AOV lift × AOV ÷ the add-on value: 2,5 % × 200.000 / 50.000 = 10 % more orders attach
    assert offer.use_share.p50 == D("0.2")


@pytest.mark.parametrize(
    "spec",
    [
        sp.AddOnSpec(kind="add_on", main_item_id="i1", addons=[sp.AddOn(item_id="j", pct=20)]),
        sp.GiftSpec(
            kind="gift",
            gift=sp.GiftItem(unit_cost=10_000),
            trigger=sp.GiftTrigger(type="buy_item", item_id="i1"),
        ),
    ],
)
def test_add_on_and_gift_results_carry_cost_and_break_even(spec):
    offer = OfferCost(D(10_000), b(0.2, 0.2, 0.2), None, "quà tặng")
    o = simple_option(spec, SimpleFacts(LiftEvidence(b(0.01, 0.03, 0.05), "shop"), offers=(offer,)))
    assert o.offers == (offer,)
    r = run(base(), o, n=300)
    assert r.cost_total > 0
    assert r.break_even_orders is not None
    j = r.json()
    assert j["cost"]["total"] > 0 and j["roi"]["value"] is not None


# -- the card's numbers: Δ tổng lợi nhuận headline, margin shift, ROI (B.4, B.6) ----------------


def test_wire_keys_carry_roi_and_margin():
    assert "roi" in WIRE_KEYS and "margin" in WIRE_KEYS
    o = combo_option(combo("pct", [(2, 5)]), unmeasured_facts(reach=b(0.1, 0.2, 0.3)))
    fb = replace(base(), margin_basis=MarginBasis(D(1_000_000), D(10_000_000), D(10_500_000)))
    r = run(fb, o, n=200)
    j = r.json()
    assert set(j) == set(WIRE_KEYS)
    d_gmv = float(r.likely.gmv - r.before.gmv)
    assert j["roi"]["value"] == pytest.approx(d_gmv / float(r.cost_total))
    assert j["roi"]["text"].startswith("ΔGMV / chi phí ")
    assert j["roi"]["metric_id"] == "card_return"
    m = j["margin"]
    # T1: profit / doanh thu thuc (the dashboard's), never / GMV
    assert m["before_pct"] == 10.0
    # on the card's horizon: m0 x R_before + Δ profit over R_after, R = GMV x net/GMV
    ratio = D(10_000_000) / D(10_500_000)
    r_before, r_after = r.before.gmv * ratio, r.likely.gmv * ratio
    after = (D("0.1") * r_before + r.likely.profit - r.before.profit) / r_after * 100
    assert m["after_pct"] == pytest.approx(float(after), abs=0.06)
    assert m["shift_pts"] == pytest.approx(m["after_pct"] - m["before_pct"])


def test_headline_is_total_profit_even_when_margin_falls():
    # a cheaper price: profit per order 20.000 -> 15.000 (margin down), orders +60 %
    facts = PriceFacts(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        profit_per_order_after=D(15_000),
        price_factor=D("0.9"),
        contribution_rate=D("0.3"),
        ctor=LiftEvidence(b(0.6, 0.6, 0.6), "product_history"),
    )
    spec = sp.PriceSpec(kind="price", item_id="i1", variations=[sp.VariationPrice(change_pct=-10)])
    fb = replace(base(), margin_basis=MarginBasis(D(1_000_000), D(10_000_000), D(10_500_000)))
    r = run(fb, price_option(spec, facts), n=1)
    j = r.json()
    assert r.likely is not None and r.before.profit is not None and r.likely.profit is not None
    # Δ tổng lợi nhuận = orders_after × ppo_after − orders_before × ppo_before
    ppo_after = r.likely.profit / r.likely.orders
    ppo_before = r.before.profit / r.before.orders
    total = r.likely.orders * ppo_after - r.before.orders * ppo_before
    assert j["delta"]["profit"]["value"] == pytest.approx(float(round(total)))
    assert j["delta"]["profit"]["value"] > 0
    assert j["margin"]["shift_pts"] < 0


def test_roi_is_none_without_cost_and_when_not_estimable():
    o = combo_option(combo("pct", [(2, 5)]), unmeasured_facts(use_share_now=D(0)))
    j = run(base(), o, n=50).json()
    assert j["roi"]["value"] is None


# -- J: stacking verified on a real ORY order (combo on top of the programme price; fees after) --


def test_combo_tier_applies_on_the_programme_price():
    # list 100.000 → Chương Trình Của Shop 78.100 (deal_price) → Mua 2 giảm 20 % = 124.960 for 2
    lines = [
        OrderLine("o1", "i1-sku", "i1", date(2026, 6, 6), 2, D(100_000), D(78_100)),
        *[
            OrderLine(f"o{i}", "i1-sku", "i1", date(2026, 6, 6), 1, D(100_000), D(78_100))
            for i in range(2, 6)
        ],
    ]
    f = adapters.combo_facts(combo("pct", [(2, 20)]), fake_env(lines))
    assert f.unit_price == D(78_100)
    assert f.per_use == D(156_200) - D(124_960)  # 31.240, not 20 % of 200.000
    # giá đặc biệt / số tiền convert against N × the programme price too
    got = adapters.effective_tiers(combo("special_price", [(2, 124_960)]), f.unit_price)
    assert round(got[0][1], 6) == D(20)


def test_combo_cost_is_net_of_the_fees_it_saves():
    # fees are on the post-combo item total: one đồng of discount costs (1 − fee rate)
    facts = unmeasured_facts(per_use=D(31_240), fee_rate=D("0.244"))
    o = combo_option(combo("pct", [(2, 20)]), facts)
    assert o.offers[0].per_use == D(31_240) * (1 - D("0.244"))


def test_combo_fee_rate_reads_the_products_fee_formulas():
    formula = SimpleNamespace(pct_rate_on_buyer_paid=D("0.244"))
    env = SimpleNamespace(
        schedule=lambda item: SimpleNamespace(
            formula_on=lambda d: formula if item == "i1" else None
        ),
        as_of=date(2026, 11, 11),
    )
    assert adapters.combo_fee_rate(env, ["i1"]) == D("0.244")
    assert adapters.combo_fee_rate(env, ["x"]) == 0  # no formula -> the gross discount
    assert adapters.combo_fee_rate(SimpleNamespace(), ["i1"]) == 0


# -- the dispatcher puts Mua kèm / Quà tặng cost into the option ---------------------------------


def _ctx(monkeypatch, certain, refusal=None):
    from juli_backend.services.shopee_builder import engine_families as ef
    from juli_backend.services.shopee_recommendations import evaluate as ev_mod

    monkeypatch.setattr(
        ef.translate,
        "to_variant",
        lambda spec, ctx: SimpleNamespace(
            variant={"change_kind": spec.kind, "items": ["i1"], "inputs": {}, "extra": {}}
        ),
    )
    monkeypatch.setattr(
        ev_mod, "evaluate", lambda env, cand: SimpleNamespace(certain=certain, refusal=refusal)
    )
    monkeypatch.setattr(
        ef.adapters,
        "lift_evidence",
        lambda kind, items, env, magnitude=None: LiftEvidence(b(0.0, 0.025, 0.05), "shop"),
    )
    return SimpleNamespace(env=SimpleNamespace())


def test_option_for_gift_carries_its_cost(monkeypatch):
    from juli_backend.services.shopee_builder.engine_families import option_for

    certain = {"gift": {"cost_per_gift": 12_000, "qualifying_orders": 30, "total_orders": 120}}
    spec = sp.GiftSpec(
        kind="gift",
        gift=sp.GiftItem(unit_cost=12_000),
        trigger=sp.GiftTrigger(type="buy_item", item_id="i1"),
    )
    o = option_for(spec, _ctx(monkeypatch, certain))
    assert o.offers and o.offers[0].per_use == D(12_000) and o.offers[0].label == "quà tặng"


def test_option_for_add_on_carries_its_cost(monkeypatch):
    from juli_backend.services.shopee_builder.engine_families import option_for

    certain = {
        "main_orders": 100,
        "aov_now": 200_000,
        "attach_value_per_order": 50_000,
        "discount_per_attach_gmv": 0.2,
        "discount_cost_on_existing": 100_000,
    }
    spec = sp.AddOnSpec(kind="add_on", main_item_id="i1", addons=[sp.AddOn(item_id="j", pct=20)])
    o = option_for(spec, _ctx(monkeypatch, certain))
    assert o.offers and o.offers[0].per_use == D(10_000)


def test_option_for_gift_without_a_cost_says_so(monkeypatch):
    from juli_backend.services.shopee_builder.engine_families import OFFER_COST_UNKNOWN, option_for

    spec = sp.GiftSpec(
        kind="gift",
        gift=sp.GiftItem(unit_cost=12_000),
        trigger=sp.GiftTrigger(type="buy_item", item_id="i1"),
    )
    o = option_for(spec, _ctx(monkeypatch, {}, refusal="gift_cost_unknown"))
    assert o.offers == () and o.note == OFFER_COST_UNKNOWN


# -- B.10 (owner, 2026-11-13): no combo history -> reach not estimable, not the E2 upper bound ---


def _one_unit_orders(n, bundle=D(0)):
    return [
        OrderLine(
            f"o{i}", "i1-sku", "i1", date(2026, 6, 6), 1, D(100_000), D(100_000), D(0), bundle
        )
        for i in range(n)
    ]


def test_a_shop_that_never_ran_a_combo_gets_cost_and_break_even_only():
    # every order holds one unit: E2 would call all of them "reaching" Mua 2 (an upper bound)
    f = adapters.combo_facts(combo("pct", [(2, 10)]), fake_env(_one_unit_orders(40)))
    assert f.reach is None
    o = combo_option(combo("pct", [(2, 10)]), f)
    assert o.drivers[0].basis == "not_estimable"
    assert "chưa chạy combo" in o.drivers[0].note


def _orders(prefix, day, ones, twos, bundle=D(0)):
    """``ones`` one-unit and ``twos`` two-unit orders of i1 at 100.000 on ``day`` (the two-unit
    lines carry ``bundle`` as their combo discount)."""
    out = [
        OrderLine(f"{prefix}1-{i}", "i1-sku", "i1", day, 1, D(100_000), D(100_000))
        for i in range(ones)
    ]
    return out + [
        OrderLine(f"{prefix}2-{i}", "i1-sku", "i1", day, 2, D(100_000), D(100_000), D(0), bundle)
        for i in range(twos)
    ]


BEFORE, DURING = date(2026, 6, 1), date(2026, 6, 10)


def test_combo_reach_is_the_rise_in_tier_share_while_the_shops_combo_ran():
    # 2026-11-15 (sample shop: ΔGMV +4,34 tr on +1,6 đơn): the near share counted every one-unit
    # order as buying a second unit (100 % take-up). With the shop's own combo run, the reach is
    # the rise in the share of orders at the tier: 10/40 = 25 % before, 20/40 = 50 % during
    lines = _orders("b", BEFORE, 30, 10) + _orders("d", DURING, 20, 20, bundle=D(20_000))
    f = adapters.combo_facts(combo("pct", [(2, 10)]), fake_env(lines))
    assert f.reach is not None and f.reach_note is None
    # se = sqrt(.5 × .5 / 40 + .25 × .75 / 40) = 0.104583; z90 × se = 0.134028
    assert f.reach.p50 == D("0.25")
    assert f.reach.p10 == pytest.approx(D("0.115972"), abs=D("0.000001"))
    assert f.reach.p90 == pytest.approx(D("0.384028"), abs=D("0.000001"))
    # the near share (every one-unit order, 50 of 80) is no longer the reach
    assert f.near_share == D("0.625") and f.reach.p50 < f.near_share
    o = combo_option(combo("pct", [(2, 10)]), f)
    assert o.drivers[0].basis == "measured"


def test_a_combo_run_that_moved_nobody_up_estimates_no_aov_lift():
    # the sample shop: 65 % of orders at a tier before its combo, 60 % while it ran
    lines = _orders("b", BEFORE, 30, 10) + _orders("d", DURING, 30, 10, bundle=D(20_000))
    f = adapters.combo_facts(combo("pct", [(2, 10)]), fake_env(lines))
    assert f.reach is not None and f.reach.p10 == 0 and f.reach.p50 == 0 and f.reach.p90 > 0
    o = combo_option(combo("pct", [(2, 10)]), f)
    assert o.drivers[0].lift.p50 == 0
    # the cost is the discount on the orders already at the tier (25 %), not on every order
    assert o.offers[0].use_share.p50 == D("0.25")


def test_a_combo_that_ran_the_whole_window_cannot_measure_its_reach():
    lines = _orders("d", DURING, 30, 10, bundle=D(20_000))
    f = adapters.combo_facts(combo("pct", [(2, 10)]), fake_env(lines))
    assert f.reach is None and f.reach_note == NOTE_COMBO_REACH
    assert combo_option(combo("pct", [(2, 10)]), f).drivers[0].basis == "not_estimable"


def test_the_combo_aov_lift_is_relative_to_the_base_it_moves():
    # 2026-11-15: the lift was reach × units × đơn giá ÷ the whole-basket AOV (other products
    # included) but multiplied the products' own GMV: ΔGMV per order must be reach × đơn giá
    lines = _orders("b", BEFORE, 30, 10) + _orders("d", DURING, 20, 20, bundle=D(20_000))
    f = replace(adapters.combo_facts(combo("pct", [(2, 10)]), fake_env(lines)), base_aov=D(80_000))
    o = combo_option(combo("pct", [(2, 10)]), f)
    assert o.drivers[0].lift.p50 == D("0.25") * D(100_000) / D(80_000)


# -- Phân loại / set: the set's own price and its cannibalisation (2026-11-15) -------------------


def test_a_set_takes_its_discount_from_the_orders_that_already_buy_that_many_single_units():
    lines = [
        OrderLine("a", "s1", "i1", BEFORE, 2, D(59_000), D(59_000)),  # one set
        OrderLine("b", "s1", "i1", BEFORE, 1, D(59_000), D(59_000)),  # under the set
        OrderLine("c", "s1", "i1", BEFORE, 3, D(59_000), D(59_000)),  # one set + one single
        OrderLine("d", "p3", "i1", BEFORE, 2, D(165_000), D(165_000)),  # pack variation: no
    ]
    offer = adapters.variation_set_offer(fake_env(lines), "i1", 2, D(10), {"p3": 3})
    assert offer is not None
    # 2 × 59.000 × 10 % on 2 of 4 orders (no fee formula in the fake: the gross discount)
    assert offer.per_use == D("11800.0") and offer.use_share.p50 == D("0.5")


def test_a_set_no_order_switches_to_has_no_cannibalisation_cost():
    lines = [OrderLine("b", "s1", "i1", BEFORE, 1, D(59_000), D(59_000))]
    assert adapters.variation_set_offer(fake_env(lines), "i1", 2, D(10), {}) is None


# -- Deal Sốc (add_on, gift): attach rate needs the main product's orders, not a funnel window --


def _deal_soc_ctx(n_orders):
    from types import SimpleNamespace

    lines = [SimpleNamespace(order_id=f"o{i}") for i in range(n_orders)]
    return SimpleNamespace(env=SimpleNamespace(lines_for=lambda items: lines))


def test_deal_soc_base_lifts_the_funnel_low_data_flag_with_enough_orders():
    from dataclasses import replace

    from juli_backend.services.shopee_builder.engine_families import integrate

    spec = sp.AddOnSpec(kind="add_on", main_item_id="i1", addons=[sp.AddOn(item_id="j", pct=20)])
    low = replace(base(), low_data=("aov", "ctor", "ctr"))
    ok = integrate.deal_soc_base(_deal_soc_ctx(12), spec, low)
    assert ok.low_data == ("ctr",)
    few = integrate.deal_soc_base(_deal_soc_ctx(3), spec, replace(base(), low_data=()))
    assert few.low_data == ("aov",)


def test_deal_soc_with_few_orders_says_why_with_its_own_reason_code():
    from dataclasses import replace

    from juli_backend.services.shopee_builder.engine.wire import result_json
    from juli_backend.services.shopee_builder.engine_families import common

    spec = sp.AddOnSpec(kind="add_on", main_item_id="i1", addons=[sp.AddOn(item_id="j", pct=20)])
    option = replace(
        simple_option(spec, SimpleFacts(LiftEvidence(b(0.01, 0.03, 0.05), "shop"))),
        note=common.NOTE_ATTACH_FEW_ORDERS,
    )
    out = result_json(run(replace(base(), low_data=("aov",)), option, n=200))
    assert out["estimable"] is False
    assert out["reason_code"] == "attach_few_orders"
    assert out["reason_text"] == "Sản phẩm chính chưa đủ 10 đơn để ước tính mua kèm."
