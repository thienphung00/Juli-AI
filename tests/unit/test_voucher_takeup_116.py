"""Owner #116: a min-spend voucher's uses and its AOV lift from ONE take-up per shop and ONE
upgrader draw (invented figures, fake env, no DB).

* the take-up u is measured once per shop on the orders that used any shop voucher, else a
  labelled prior -- never 1;
* the upgraders are a share rho of the near orders (within 20 % below the minimum), they always
  use the voucher (rho x near, never x u), never more than the near orders;
* in each scenario the upgraders' added spend and their uses come from the same draw;
* a percent voucher's cap applies per order.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import FunnelBase
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import adapters, common, families
from juli_backend.services.shopee_profit.order_profit import OrderLine
from tests.unit.test_funnel_engine import src

MINS = (150_000, 200_000, 250_000, 350_000)


def _line(order: str, value: int, voucher: int = 0) -> OrderLine:
    return OrderLine(
        order, f"{order}-s", "i1", date(2026, 10, 5), 1, D(value), D(value), D(voucher)
    )


def _env(lines, vouchers=()):
    pairs = [
        (ln, SimpleNamespace(contribution=ln.order_value * D("0.2"), excluded_reason=None))
        for ln in lines
    ]
    return SimpleNamespace(
        lines_for=lambda items: lines,
        view=SimpleNamespace(pairs=pairs),
        usage_rate=None,
        vouchers=list(vouchers),
    )


def _shop(seed: int, n: int = 400, takeup: float = 0.4, voucher_from: int = 150_000):
    """``n`` orders around 170.000đ; a share ``takeup`` of those at / over ``voucher_from`` carry
    a shop voucher."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        v = int(rng.lognormvariate(12.05, 0.45) // 1000 * 1000)
        used = v >= voucher_from and rng.random() < takeup
        out.append(_line(f"o{i}", v, 10_000 if used else 0))
    return out


def _base(lines) -> FunnelBase:
    n = len({ln.order_id for ln in lines})
    gmv = float(sum(ln.order_value for ln in lines))
    return FunnelBase(
        "shop-x",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (src("the_san_pham_khac", 100_000, 8000, n, gmv, gmv * 0.2),),
        D("0.3"),
    )


def _amount(minimum: int, value: int = 15_000, **kw) -> sp.VoucherSpec:
    return sp.VoucherSpec(
        kind="voucher", discount_type="amount", value=value, min_spend=minimum, **kw
    )


# -- 1. one take-up per shop ---------------------------------------------------------------------


def test_takeup_is_one_per_shop_measured_on_voucher_orders():
    lines = _shop(1)
    env = _env(lines)
    facts = [adapters.voucher_facts(_amount(m), env) for m in MINS]
    assert len({f.usage_rate for f in facts}) == 1  # the same u for every minimum
    assert all(f.takeup_basis == "measured" for f in facts)
    used = [ln for ln in lines if ln.shop_voucher_share > 0]
    floor = min(ln.order_value for ln in used)
    qualifying = [ln for ln in lines if ln.order_value >= floor]
    assert facts[0].usage_rate == D(len(used)) / len(qualifying)


def test_takeup_qualifies_on_the_shops_own_voucher_minimum_when_known():
    lines = _shop(2)
    env = _env(lines, [SimpleNamespace(min_spend=D(150_000))])
    f = adapters.voucher_facts(_amount(200_000), env)
    used = sum(1 for ln in lines if ln.shop_voucher_share > 0)
    qualifying = sum(1 for ln in lines if ln.order_value >= 150_000)
    assert f.usage_rate == D(used) / qualifying and f.takeup_basis == "measured"


def test_too_few_voucher_orders_is_the_labelled_prior_never_one():
    # 60 orders over the minimum, only 5 carry a voucher: below the threshold
    lines = [_line(f"h{i}", 250_000, 10_000 if i < 5 else 0) for i in range(60)]
    lines += [_line(f"l{i}", 50_000) for i in range(40)]
    f = adapters.voucher_facts(_amount(200_000), _env(lines))
    assert common.TAKEUP_MIN_VOUCHER_ORDERS > 5
    assert f.usage_rate == common.TAKEUP_PRIOR and f.takeup_basis == "prior"
    assert f.usage_rate < 1
    # no voucher at all in the window: the prior too
    none = [_line(f"h{i}", 250_000) for i in range(60)]
    g = adapters.voucher_facts(_amount(200_000), _env(none))
    assert g.usage_rate == common.TAKEUP_PRIOR and g.takeup_basis == "prior"


def test_takeup_basis_is_in_the_result_evidence():
    lines = _shop(3)
    spec = _amount(200_000)
    opt = families.voucher_option(spec, adapters.voucher_facts(spec, _env(lines)))
    r = run(_base(lines), opt, n=200)
    offer = r.json()["cost"]["offers"][0]
    assert offer["takeup"]["basis"] == "measured"
    assert 0 < offer["takeup"]["rate"] < 1
    few = [_line(f"h{i}", 250_000) for i in range(60)]
    opt2 = families.voucher_option(spec, adapters.voucher_facts(spec, _env(few)))
    r2 = run(_base(few), opt2, n=200)
    assert r2.json()["cost"]["offers"][0]["takeup"] == {
        "basis": "prior",
        "rate": float(common.TAKEUP_PRIOR),
    }


# -- 2. upgraders: rho x near, always users, never above the near orders -------------------------


def test_upgraders_are_rho_of_the_near_orders_and_always_use_it():
    lines = _shop(4)
    spec = _amount(200_000)
    f = adapters.voucher_facts(spec, _env(lines))
    opt = families.voucher_option(spec, f)
    offer = opt.offers[0]
    # the orders already qualifying use it at the shop's take-up
    assert offer.use_share.p10 == offer.use_share.p50 == f.qualifying_share * f.usage_rate
    up = offer.upgrade
    assert up is not None and up.cap == f.near_share
    lo, mid, hi = common.REACH  # the prior rho band, P10 / P50 / P90
    assert (up.share.p10, up.share.p50, up.share.p90) == (
        lo * f.near_share,
        mid * f.near_share,
        hi * f.near_share,
    )
    assert up.share.p90 <= f.near_share
    assert up.added == f.reach_gap
    aov = next(d for d in opt.drivers if d.metric == "aov")
    assert aov.upgrade_of == 0 and aov.basis == "prior"


def test_the_floor_never_lifts_the_upgrade_driver():
    lines = _shop(5)
    spec = _amount(200_000)
    opt = families.voucher_option(spec, adapters.voucher_facts(spec, _env(lines)))
    assert common.floor_prior_drivers(opt).drivers == opt.drivers


# -- 3. one shared draw: GMV and uses agree ------------------------------------------------------


@pytest.mark.parametrize("seed", [11, 12, 13])
@pytest.mark.parametrize("minimum", MINS)
def test_upgrader_gmv_is_upgraders_times_their_added_spend(seed, minimum):
    lines = _shop(seed)
    spec = _amount(minimum)
    f = adapters.voucher_facts(spec, _env(lines))
    opt = families.voucher_option(spec, f)
    # the AOV driver only (no CTOR change): every extra đồng is an upgrader's
    opt = replace(opt, drivers=tuple(d for d in opt.drivers if d.metric == "aov"))
    if not opt.drivers:
        pytest.skip("no near orders")
    r = run(_base(lines), opt, n=1000, seed=seed)
    for col in (r.low, r.likely, r.high):
        assert col is not None and col.orders == pytest.approx(r.before.orders)
    per = opt.offers[0].per_use
    for col in (r.low, r.likely, r.high):
        uses = col.offer_cost / per  # no usage limit: the column's uses
        upgraders = uses - col.orders * f.qualifying_share * f.usage_rate
        assert upgraders >= D("-1e-6")
        assert float(col.gmv - r.before.gmv) == pytest.approx(
            float(upgraders * f.reach_gap), rel=1e-6, abs=1e-3
        )


# -- 4. percent cap per order --------------------------------------------------------------------


def test_percent_voucher_caps_each_order():
    lines = [_line("a", 100_000), _line("b", 150_000), _line("c", 300_000), _line("d", 50_000)]
    spec = sp.VoucherSpec(
        kind="voucher", discount_type="pct", value=10, min_spend=100_000, max_value=20_000
    )
    f = adapters.voucher_facts(spec, _env(lines))
    # min(10 %, 20.000đ) per order: 10.000, 15.000, 20.000 -> 15.000 (not 10 % of the mean)
    assert f.per_use == D(15_000)
    assert f.max_discount is not None
    assert (f.max_discount.binding_orders, f.max_discount.qualifying_orders) == (1, 3)


# -- 5. invariants over several bases ------------------------------------------------------------


@pytest.mark.parametrize("seed", [21, 22, 23, 24])
def test_voucher_invariants_over_bases(seed):
    lines = _shop(seed)
    base = _base(lines)
    env = _env(lines)
    uses_by_min = []
    for minimum in MINS:
        spec = _amount(minimum)
        f = adapters.voucher_facts(spec, env)
        assert f.takeup_basis == "measured"
        opt = families.voucher_option(spec, f)
        r = run(base, opt, n=1000, seed=seed)
        uses = float(r.offers[0].expected_uses)
        orders = float(r.likely.orders)
        q, near, u = float(f.qualifying_share), float(f.near_share), float(f.usage_rate)
        # never more uses than the horizon's orders at / near the minimum
        assert uses <= orders * (q + near) + 1e-6
        for col in (r.low, r.likely, r.high):
            col_uses = float(col.offer_cost / opt.offers[0].per_use)
            o = float(col.orders)
            # qualifying users + upgraders (never more than the near orders)
            assert col_uses <= o * (q * u + near) + 1e-6
            assert col_uses >= o * q * u - 1e-6
        uses_by_min.append(uses)
    # the shop's take-up measured (about 40 %): a higher minimum -> fewer uses
    assert uses_by_min == sorted(uses_by_min, reverse=True)
