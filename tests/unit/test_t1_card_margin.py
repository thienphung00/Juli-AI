"""T1 (batch 1119): the card's margin is profit / doanh thu thuc, the dashboard's own margin.

Synthetic shops only. Net revenue is ``buyer_paid`` (covered); the dashboard's function is
``shop_profit.scope_margin_pct``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.sample_shop import content_specs
from juli_backend.services.shopee_builder.engine.contract import (
    FunnelBase,
    MarginBasis,
    OptionResult,
    Scenario,
)
from juli_backend.services.shopee_builder.engine.wire import _margin
from juli_backend.services.shopee_builder.engine_families.integrate import (
    margin_basis,
    sum_results,
)
from juli_backend.services.shopee_profit.fees import FeeComponent, FeeFormula, FeeKind, FeeSchedule
from juli_backend.services.shopee_profit.income import LineIncome
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_profit.shop_profit import scope_margin_pct, shop_profit
from juli_backend.services.shopee_recommendations import config

DAY = date(2026, 10, 15)
SCHEDULE = FeeSchedule(
    (FeeFormula(date(2026, 1, 1), (FeeComponent("commission", FeeKind.PCT, rate=D("0.10")),)),)
)


def scen(gmv: int, profit: int | None) -> Scenario:
    return Scenario(None, None, D(10), D(gmv), None if profit is None else D(profit), D(0))


def result(before: Scenario, likely: Scenario | None, basis: MarginBasis | None) -> OptionResult:
    return OptionResult(
        kind="x",
        label="x",
        days=30,
        horizon="duration",
        drivers=(),
        estimable=likely is not None,
        basis="not_estimable",
        before=before,
        low=None,
        likely=likely,
        high=None,
        build_up=(),
        cost_total=D(0),
        break_even_orders=None,
        break_even_aov=None,
        margin_basis=basis,
    )


# net = 0.94 x GMV; covered profit 188.000 on net 940.000 -> 20,0 %
BASIS = MarginBasis(profit=D(188_000), net_revenue=D(940_000), gmv=D(1_000_000))


def test_t1_1_before_margin_is_profit_over_net_revenue_not_gmv():
    m = _margin(result(scen(1_000_000, 0), scen(1_000_000, 0), BASIS))
    assert m["before_pct"] == 20.0  # 188.000 / 940.000; over GMV it would be 18,8


def test_t1_2_after_margin_uses_after_gmv_times_the_before_net_gmv_ratio():
    # +20 % GMV, +50.000 profit: after = (188.000 + 50.000) / (1.200.000 x 0,94) = 21,1 %
    m = _margin(result(scen(1_000_000, 10_000), scen(1_200_000, 60_000), BASIS))
    assert m["after_pct"] == 21.1
    assert m["shift_pts"] == pytest.approx(21.1 - 20.0)


@pytest.mark.parametrize(
    "basis",
    [
        None,
        MarginBasis(D(1), D(0), D(100)),
        MarginBasis(D(1), D(-5), D(100)),
        MarginBasis(None, D(100), D(100)),
    ],
)
def test_t1_3_no_net_revenue_or_profit_means_no_margin_never_a_gmv_fallback(basis):
    m = _margin(result(scen(1_000_000, 100_000), scen(1_100_000, 150_000), basis))
    assert m == {"before_pct": None, "after_pct": None, "shift_pts": None}


def test_not_estimable_card_keeps_only_the_before_margin():
    m = _margin(result(scen(1_000_000, 0), None, BASIS))
    assert m["before_pct"] == 20.0 and m["after_pct"] is None and m["shift_pts"] is None


def _shop():
    def ol(oid, sku, item, price):  # a shop voucher takes 6 % off: net = 0,94 x GMV
        return OrderLine(oid, sku, item, DAY, 1, D(price), D(price), D(price) * D("0.06"))

    lines = [ol("o1", "S1", "P1", 100_000), ol("o2", "S2", "P2", 200_000)]
    costs = {"S1": SkuCost("S1", D(30_000), D(0)), "S2": SkuCost("S2", D(60_000), D(0))}
    pairs = profit_lines(lines, costs, schedule=SCHEDULE)
    return shop_profit(pairs, campaigns=[], product_ad_spend={})


@pytest.mark.parametrize("items", [(), ("P1",), ("P1", "P2")])
def test_t1_4_card_margin_equals_the_dashboard_margin_on_the_same_scope(items):
    sp = _shop()
    assert sp.buyer_paid_covered != sp.gmv  # net is not GMV here
    basis = margin_basis(sp, items)
    m = _margin(result(scen(int(basis.gmv), 0), scen(int(basis.gmv), 0), basis))
    dash = scope_margin_pct(sp, items)
    assert dash is not None and m["before_pct"] == float(dash)
    assert m["after_pct"] == float(dash)  # nothing changed: the same margin after


def test_basis_is_none_without_covered_revenue():
    sp = _shop()
    assert margin_basis(sp, ("unknown",)) is None


def test_several_targets_add_the_basis_up():
    a = result(scen(100, 1), scen(110, 2), BASIS)
    both = sum_results([a, a], "x")
    assert both.margin_basis == MarginBasis(D(376_000), D(1_880_000), D(2_000_000))
    assert sum_results([a, replace(a, margin_basis=None)], "x").margin_basis is None


def test_funnel_base_defaults_to_no_basis():
    fields = FunnelBase.__dataclass_fields__
    assert fields["margin_basis"].default is None
    assert SimpleNamespace  # keep import used


def test_sample_title_spec_uses_the_one_title_limit():
    spec, _ = content_specs.title_spec(0)
    assert spec["inputs"]["max_chars"] == config.MAX_TITLE_CHARS == 120


def _income(payout):
    z = D(0)
    return LineIncome((), z, z, z, z, z, z, z, z, D(payout))


def test_only_the_sale_is_in_net_revenue_and_in_the_covered_gmv():
    """Owner rule: refunded / returned / cancelled / undelivered goods are not doanh thu thuc.
    One order of each status plus one normal order: R and the covered GMV are the normal one's."""
    S = OrderStatus
    lines = [OrderLine("ok", "S1", "P1", DAY, 1, D(100_000), D(100_000), D(6_000))]
    # the refund statuses carry a settlement row (they cost its deduction), so they are in the
    # profit base; cancelled and in transit are outside it
    for i, st in enumerate(
        (S.REFUNDED_ACCEPTED, S.REFUNDED_NOT_RECEIVED, S.RETURNED, S.CANCELLED, S.IN_TRANSIT)
    ):
        lines.append(
            OrderLine(
                f"x{i}", "S1", "P1", DAY, 1, D(70_000), D(70_000), status=st, income=_income(-5_000)
            )
        )
    pairs = profit_lines(lines, {"S1": SkuCost("S1", D(30_000), D(1_000))}, schedule=SCHEDULE)
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    normal_net, normal_gmv = D(94_000), D(100_000)
    p = sp.products["P1"]
    assert sp.buyer_paid == p.buyer_paid == normal_net
    assert sp.buyer_paid_covered == p.buyer_paid_covered == normal_net
    assert sp.gmv_covered == p.gmv_covered == normal_gmv
    # headline GMV is unchanged: it still counts cancelled and in-transit orders (not refunds)
    assert sp.gmv == p.gmv == normal_gmv + 2 * D(70_000)
    b = margin_basis(sp, ())
    assert b is not None and (b.net_revenue, b.gmv) == (normal_net, normal_gmv)
