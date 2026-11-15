"""Adapters: facts from order lines and from the evaluators' certain layer (fake env, no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_profit.order_profit import OrderLine


def line(order, qty, price, item="i1"):
    return OrderLine(order, f"{item}-sku", item, date(2026, 10, 5), qty, D(price), D(price))


def fake_env(lines, usage_rate=None):
    pairs = [
        (ln, SimpleNamespace(contribution=ln.order_value * D("0.2"), excluded_reason=None))
        for ln in lines
    ]
    return SimpleNamespace(
        lines_for=lambda items: lines, view=SimpleNamespace(pairs=pairs), usage_rate=usage_rate
    )


LINES = [line("o1", 1, 50_000), line("o2", 2, 50_000), line("o3", 1, 50_000), line("o4", 4, 50_000)]


def test_voucher_facts_count_existing_qualifying_orders():
    spec = sp.VoucherSpec(
        kind="voucher", discount_type="pct", value=10, min_spend=100_000, max_value=15_000
    )
    f = adapters.voucher_facts(spec, fake_env(LINES))
    assert f.qualifying_share == D("0.5") and f.below_share == D("0.5")
    assert f.aov_now == D(100_000)
    assert f.raise_gap_per_order == D(25_000)
    assert f.per_use == D(15_000)  # 10 % of 150.000 capped at 15.000
    assert f.profit_per_order == D(20_000)


def test_combo_facts_use_share_includes_orders_already_at_a_tier():
    spec = sp.ComboSpec(
        kind="combo",
        item_ids=["i1"],
        discount_type="pct",
        tiers=[sp.ComboTier(qty=2, value=10), sp.ComboTier(qty=4, value=20)],
    )
    f = adapters.combo_facts(spec, fake_env(LINES))
    assert f.use_share_now == D("0.5")  # o2 (2 units) and o4 (4 units)
    assert f.near_share == D("0.5")  # o1, o3 hold 1 unit, one under tier 2
    assert f.per_use == (D(100_000) * D("0.1") + D(200_000) * D("0.2")) / 2


def test_listing_combo_facts_switching_orders_hold_all_members():
    lines = [line("o1", 1, 50_000, "a"), line("o1", 1, 30_000, "b"), line("o2", 1, 50_000, "a")]
    spec = sp.ListingComboSpec(
        kind="listing_combo", title="t", price=70_000, stock=1, member_ids=["a", "b"]
    )
    f = adapters.listing_combo_facts(spec, fake_env(lines), None)
    assert f.switch_share == D("0.5") and f.value_now == D(80_000) and f.new_price == D(70_000)


def test_price_facts_from_evaluation_weights_by_orders():
    ev = SimpleNamespace(
        certain={
            "skus": [
                {
                    "orders": 30,
                    "price_before": 100,
                    "price_after": 90,
                    "profit_per_order_before": 20,
                    "profit_per_order_after": 12,
                },
                {
                    "orders": 10,
                    "price_before": 200,
                    "price_after": 200,
                    "profit_per_order_before": 40,
                    "profit_per_order_after": 40,
                },
            ]
        }
    )
    f = adapters.price_facts_from_evaluation(
        ev, aov_now=D(150), contribution_rate=D("0.3"), ctor=None
    )
    assert f.price_factor == (D(30) * D("0.9") + D(10)) / 40
    assert f.profit_per_order == D(25) and f.profit_per_order_after == D(19)


def test_lift_evidence_basis_and_band_from_prediction():
    env = SimpleNamespace(calibration={}, sim=None, response_by_item={}, response_shop=None)
    ev = adapters.lift_evidence("title", ["i1"], env)
    assert ev.basis == "prior" and ev.band.p10 <= ev.band.p50 <= ev.band.p90


# -- min-spend voucher take-up (fix: not every order uses the voucher) ----------------------------


def _vline(order, price, voucher=0):
    return OrderLine(
        order, f"{order}-sku", "i1", date(2026, 10, 5), 1, D(price), D(price), D(voucher)
    )


def _shop(n_high, n_near, n_low, voucher_on_high=0):
    lines = [_vline(f"h{i}", 120_000, 10_000 if i < voucher_on_high else 0) for i in range(n_high)]
    lines += [_vline(f"n{i}", 90_000) for i in range(n_near)]
    lines += [_vline(f"l{i}", 30_000) for i in range(n_low)]
    return lines


def _voucher_spec():
    return sp.VoucherSpec(kind="voucher", discount_type="amount", value=10_000, min_spend=100_000)


def test_takeup_measured_from_the_shops_own_order_lines():
    # 40 orders over the minimum, 10 carry a shop voucher -> 25 % take-up, not 100 %
    from juli_backend.services.shopee_builder.engine_families import families

    lines = _shop(40, 10, 50, voucher_on_high=10)
    f = adapters.voucher_facts(_voucher_spec(), fake_env(lines))
    assert f.usage_rate == D("0.25")
    opt = families.voucher_option(_voucher_spec(), f)
    use_mid = opt.offers[0].use_share.p50
    assert use_mid > f.qualifying_share * D("0.25") and use_mid < f.qualifying_share
    assert f.qualifying_share == D("0.4")


def test_cost_scales_with_qualifying_share_not_all_orders():
    from juli_backend.services.shopee_builder.engine_families import families

    few = families.voucher_option(
        _voucher_spec(), adapters.voucher_facts(_voucher_spec(), fake_env(_shop(10, 0, 90)))
    )
    many = families.voucher_option(
        _voucher_spec(), adapters.voucher_facts(_voucher_spec(), fake_env(_shop(60, 0, 40)))
    )
    assert few.offers[0].use_share.p50 == D("0.1")
    assert many.offers[0].use_share.p50 == D("0.6")


def test_no_near_threshold_orders_means_no_reach():
    from juli_backend.services.shopee_builder.engine_families import families

    f = adapters.voucher_facts(_voucher_spec(), fake_env(_shop(30, 0, 70)))
    assert f.near_share == D(0) and f.reach.p90 == D(0)
    opt = families.voucher_option(_voucher_spec(), f)
    # the use share stays at today's qualifying share: no order is moved up
    assert opt.offers[0].use_share.p90 == f.qualifying_share


def test_usage_limit_caps_the_cost():
    from juli_backend.services.shopee_builder.engine_families import families

    spec = sp.VoucherSpec(
        kind="voucher", discount_type="amount", value=10_000, min_spend=100_000, usage_limit=5
    )
    opt = families.voucher_option(spec, adapters.voucher_facts(spec, fake_env(_shop(60, 0, 40))))
    assert opt.offers[0].use_cap == D(5)


def test_card_lift_follows_near_orders_and_agrees_with_builder():
    from juli_backend.services.shopee_recommendations.evaluate import (
        VoucherRule,
        _voucher_lift_scale,
    )

    rule = VoucherRule(min_spend=D(100_000), amount=D(10_000))
    c = SimpleNamespace(voucher_cost_scenario=D(100_000), used_scenario=D(10), usage_limit=None)
    none_near = _voucher_lift_scale(_shop(60, 0, 40), rule, c, D(10))[0]
    with_near = _voucher_lift_scale(_shop(60, 10, 30), rule, c, D(10))[0]
    assert none_near == 0  # every qualifying order only costs, nothing is moved up
    assert with_near > 0
    capped_c = SimpleNamespace(voucher_cost_scenario=D(100_000), used_scenario=D(10), usage_limit=5)
    assert _voucher_lift_scale(_shop(60, 10, 30), rule, capped_c, D(10))[0] == with_near / 2
    # builder: the share of orders moved is the same near share the card uses
    f = adapters.voucher_facts(_voucher_spec(), fake_env(_shop(60, 10, 30)))
    assert f.near_share == D("0.1")
