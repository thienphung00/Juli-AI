"""Track P (decisions #42-#44): one profit basis on a card -- Lợi nhuận đóng góp, before ads AND
affiliate. Synthetic numbers only (an analogue of the owner's min-spend voucher card)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_builder.engine import engine
from juli_backend.services.shopee_builder.engine.contract import (
    AddedTraffic,
    AdsEvaluation,
    Band,
    DriverEffect,
    FunnelBase,
    MarginBasis,
    OfferCost,
    OptionInput,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.wire import result_json
from juli_backend.services.shopee_builder.engine_families import integrate

START, END = date(2026, 10, 1), date(2026, 10, 30)  # 30 days: a 30-day card has scale 1
AOV = D(123868)
RATE = D("0.276")  # contribution before ads and affiliate ÷ GMV
ORDERS = D(40)


def point(x: str | D) -> Band:
    v = D(x)
    return Band(v, v, v)


def _stored_base(after_ads_profit: D | None = D(1000)) -> FunnelBase:
    """A product base whose STORED profit is after ads (the old basis): ``on_contribution``
    replaces it."""
    src = SourceFunnel(
        "the_san_pham_khac",
        D(4000),
        D(400),
        ORDERS,
        ORDERS * AOV,
        after_ads_profit,
        profit_orders=D(30),
    )
    return FunnelBase("s", "products", ("p",), START, END, (src,), None, days=30, profit_days=20)


def _base() -> FunnelBase:
    return funnel.on_contribution(_stored_base(), RATE)


def _run(option: OptionInput, base: FunnelBase | None = None):
    return engine.run(base or _base(), option, seed=1, n=1)


def test_the_base_is_contribution_on_every_order_one_rate() -> None:
    b = _base()
    s = b.sources[0]
    assert s.profit == RATE * ORDERS * AOV  # the stored after-ads 1.000đ is gone
    assert s.profit_orders == ORDERS  # the measured rate stands for every order (D6)
    assert b.contribution_rate == RATE
    assert integrate.profit_per_order(b) == RATE * AOV
    # the ads break-even CPA is the same per-order figure (no spend added back on top)
    assert integrate.profit_per_order_before_ads(b) == integrate.profit_per_order(b)
    assert funnel.on_contribution(_stored_base(), None).sources[0].profit is None


def test_owner_voucher_example_extra_orders_and_cost_on_one_rate() -> None:
    """The owner's card: +1,64 orders at the contribution per order (≈ 34.200đ) against the
    voucher cost on every qualifying order: Δ ≈ −700đ (it showed −50.244đ on the after-ads
    profit per order)."""
    ppo = float(RATE * AOV)
    extra = 1.64
    cost = extra * ppo + 700.0
    share = cost / 5000.0 / float(ORDERS + D("1.64"))
    option = OptionInput(
        "min_spend_voucher",
        "Mã Giảm Giá · đơn tối thiểu",
        (DriverEffect("ctor", ("the_san_pham_khac",), "measured", lift=point("0.041")),),
        30,
        offers=(OfferCost(D(5000), point(D(repr(share))), None, "voucher"),),
    )
    r = _run(option)
    assert r.likely is not None and r.likely.profit is not None and r.before.profit is not None
    d_orders = float(r.likely.orders - r.before.orders)
    d_profit = float(r.likely.profit - r.before.profit)
    assert d_orders == pytest.approx(extra)
    assert d_profit == pytest.approx(-700.0, abs=1.0)
    extra_part = next(p for p in r.build_up if p.key == "extra_orders")
    assert float(extra_part.amount) == pytest.approx(extra * ppo, abs=1.0)


def test_the_aov_effect_is_valued_at_the_same_rate() -> None:
    option = OptionInput(
        "bundle_deal",
        "Combo",
        (DriverEffect("aov", ("the_san_pham_khac",), "measured", lift=point("0.10")),),
        30,
    )
    r = _run(option)
    assert r.likely is not None and r.likely.profit is not None and r.before.profit is not None
    d_gmv = r.likely.gmv - r.before.gmv
    assert float(r.likely.profit - r.before.profit) == pytest.approx(float(d_gmv * RATE))


def test_a_new_campaign_counts_its_spend_once() -> None:
    """D2b: added ad orders at the contribution per order (before ads) minus the new spend; the
    profit per order is never already net of today's ad cost."""
    ppo = RATE * AOV
    added = AddedTraffic(point(1000), D("0.1"), D("0.05"), AOV, point(1), ppo)
    option = OptionInput(
        "ads_new_campaign",
        "Quảng cáo mới",
        (DriverEffect("views", ("the_san_pham_khac",), "measured", added=added),),
        30,
        fixed_cost=D(100000),
    )
    r = _run(option)
    assert r.likely is not None and r.likely.profit is not None and r.before.profit is not None
    # 1000 views x 10 % x 5 % = 5 orders
    assert float(r.likely.orders - r.before.orders) == pytest.approx(5.0)
    want = 5 * float(ppo) - 100000
    assert float(r.likely.profit - r.before.profit) == pytest.approx(want, abs=1.0)


def test_lợi_nhuận_sau_quảng_cáo_stands_on_the_same_contribution() -> None:
    """#43 Q5: the ads card keeps "Lợi nhuận sau quảng cáo" = ad orders x break-even CPA −
    spend, with the break-even CPA = the card's own contribution per order."""
    b = _base()
    be = integrate.profit_per_order_before_ads(b)
    ev = AdsEvaluation(
        "budget", "c", 30, "not_capped", "", D(300000), D(400000), D(12), D(15),
        D(1), D(1), be,
    )  # fmt: skip
    assert be is not None
    assert ev.profit_after_ads(ev.spend_now, ev.orders_now) == 12 * be - 300000


def _margin_base() -> FunnelBase:
    # doanh thu thực = 90 % of GMV on the scope's covered lines
    return funnel.on_contribution(
        FunnelBase(
            "s",
            "products",
            ("p",),
            START,
            END,
            _stored_base().sources,
            None,
            margin_basis=MarginBasis(RATE * ORDERS * AOV, ORDERS * AOV * D("0.9"), ORDERS * AOV),
        ),
        RATE,
    )


def test_fewer_orders_lowers_profit_with_the_margin_flat() -> None:
    option = OptionInput(
        "title",
        "Tên sản phẩm",
        (DriverEffect("ctor", ("the_san_pham_khac",), "measured", lift=point("-0.10")),),
        30,
    )
    j = result_json(_run(option, _margin_base()))
    assert j["delta"]["profit"]["value"] < 0
    assert j["delta"]["profit"]["basis"] == "contribution"
    m = j["margin"]
    assert m["metric_id"] == "margin_contribution"
    assert m["before_pct"] == pytest.approx(float(RATE / D("0.9") * 100), abs=0.05)
    assert m["shift_pts"] == pytest.approx(0.0, abs=0.05)


def test_a_voucher_can_add_profit_while_the_margin_falls() -> None:
    option = OptionInput(
        "min_spend_voucher",
        "Mã Giảm Giá",
        (DriverEffect("ctor", ("the_san_pham_khac",), "measured", lift=point("0.30")),),
        30,
        offers=(OfferCost(D(5000), point("1"), None, "voucher"),),
    )
    j = result_json(_run(option, _margin_base()))
    assert j["delta"]["profit"]["value"] > 0
    assert j["margin"]["shift_pts"] < 0  # each order now carries the voucher
