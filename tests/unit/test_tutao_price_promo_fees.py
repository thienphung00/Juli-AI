"""Tự tạo price / promotion estimates (prod check S2, 2026-11-15, "Nước rửa chén"):

1. Chương Trình Của Shop 10 % on ONE variation cost ~3× that variation's discount -- the discount
   per order of the priced variation was charged on every order of the product.
2. Giá +5 % on one variation gave a Δ lợi nhuận above +5 % × that variation's units -- the same
   per-order change was applied to every order of the product.
3. Flash Sale −15 % for 2 hours was priced as a whole day of discounted orders.
4. Re-priced lines (reported fees dropped by ``RecoEnv.lines_for``) were charged no phí dịch vụ,
   though the shop pays it: every Δ fee of a price change was too small.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics.fee_table import seed_schedule
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import Band
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.facts import LiftEvidence, PriceFacts
from juli_backend.services.shopee_builder.engine_families.families import price_option
from juli_backend.services.shopee_profit.fees import FeeComponent, FeeKind, FeeSchedule
from juli_backend.services.shopee_profit.income import FEE_SERVICE, LineIncome
from juli_backend.services.shopee_profit.order_profit import OrderLine
from juli_backend.services.shopee_recommendations.env import RecoEnv

AS_OF = date(2026, 11, 10)


def _band(a, m, c):
    return Band(D(str(a)), D(str(m)), D(str(c)))


def _facts(**kw):
    d = dict(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        profit_per_order_after=D(12_000),
        price_factor=D("0.9"),
        contribution_rate=D("0.3"),
        ctor=LiftEvidence(_band(0.04, 0.08, 0.12), "prior"),
    )
    d.update(kw)
    return PriceFacts(**d)


# -- 1 / 2: a change on some variations reaches only their orders ----------------------------


def _evaluation(rows, gmv_delta=None):
    certain = {"skus": rows}
    if gmv_delta is not None:
        certain["gmv_delta_same_volume"] = gmv_delta
    return SimpleNamespace(certain=certain)


ONE_VARIATION = {
    "sku": "A",
    "orders": 25,
    "price_before": 100_000,
    "price_after": 90_000,
    "profit_per_order_before": 20_000,
    "profit_per_order_after": 12_000,
}


def test_one_priced_variation_spreads_its_change_over_the_products_orders():
    # 25 of the product's 100 orders hold variation A; A's GMV 2.500.000 of 10.000.000 falls 10 %
    f = adapters.price_facts_from_evaluation(
        _evaluation([ONE_VARIATION], gmv_delta=-250_000),
        aov_now=D(100_000),
        contribution_rate=None,
        ctor=LiftEvidence(_band(0, 0, 0), "prior"),
        product_orders=100,
        covered_orders=25,
        product_gmv=D(10_000_000),
    )
    assert f.coverage == D("0.25")
    assert f.price_factor == D("0.975")  # the product's GMV −2,5 %, not A's −10 %
    assert f.profit_per_order == D(20_000)
    assert f.profit_per_order_after == D(18_000)  # −8.000 on a quarter of the orders
    assert f.discount_per_order == D(8_000)  # still the discount of one order holding A


def test_without_the_products_orders_the_facts_are_the_priced_variations_own():
    f = adapters.price_facts_from_evaluation(
        _evaluation([ONE_VARIATION]),
        aov_now=D(100_000),
        contribution_rate=None,
        ctor=LiftEvidence(_band(0, 0, 0), "prior"),
    )
    assert f.coverage == D(1) and f.price_factor == D("0.9")
    assert f.profit_per_order_after == D(12_000)


def _discount(**kw):
    return sp.ProductDiscountSpec(
        kind="product_discount",
        item_id="i1",
        variations=[sp.VariationPrice(variation_id="A", discount_pct=10)],
        **kw,
    )


def test_a_programme_on_one_variation_is_used_only_by_its_orders():
    facts = _facts(
        profit_per_order_after=D(18_000),
        price_factor=D("0.975"),
        discount_per_order=D(8_000),
        coverage=D("0.25"),
    )
    o = price_option(_discount(), facts)
    (offer,) = o.offers
    assert offer.per_use == D(8_000) and offer.use_share.p50 == D("0.25")
    # the discount leaves the per-order profit once: back to today's 20.000
    assert o.profit_per_order_after == D(20_000)
    ctor, aov = o.drivers
    assert ctor.lift.p50 == D("0.02")  # +8 % on a quarter of the buyers
    assert aov.lift.p50 == D("-0.025")


def test_a_price_rise_on_one_variation_moves_only_its_share_of_orders():
    price = sp.PriceSpec(
        kind="price", item_id="i1", variations=[sp.VariationPrice(variation_id="A", change_pct=5)]
    )
    o = price_option(
        price,
        _facts(
            profit_per_order_after=D(21_000),
            price_factor=D("1.0125"),
            ctor=LiftEvidence(_band(-0.1, -0.06, -0.02), "prior"),
            coverage=D("0.25"),
        ),
    )
    assert o.offers == () and o.profit_per_order_after == D(21_000)
    ctor, aov = o.drivers
    assert ctor.lift.p50 == D("-0.015")
    assert aov.lift.p50 == D("0.0125")


# -- 3: a Flash Sale slot sells for its hours ------------------------------------------------


def _flash(hours, units=1_000):
    return sp.FlashSaleSpec(
        kind="flash_sale",
        item_id="i1",
        units=units,
        slot_hours=hours,
        variations=[sp.VariationPrice(variation_id="A", discount_pct=15)],
    )


def test_a_two_hour_flash_slot_reaches_two_hours_of_the_days_orders():
    facts = _facts(price_factor=D("0.85"), units_per_order=D(1), orders_per_day=D(24))
    o = price_option(_flash(2), facts)
    assert o.duration_days == 1
    ctor, aov = o.drivers
    share = D(2) / D(24)
    assert ctor.lift.p50 == D("0.08") * share
    assert aov.lift.p50 == D("-0.15") * share
    # 20.000 → 12.000 on 2 of 24 hours of orders
    assert o.profit_per_order_after == D(20_000) - D(8_000) * share


def test_a_flash_slot_stops_at_its_units():
    # 24 orders a day, 2 units each: 12 hours would sell 24 units, the slot holds 6 (3 orders)
    facts = _facts(price_factor=D("0.85"), units_per_order=D(2), orders_per_day=D(24))
    o = price_option(_flash(12, units=6), facts)
    ctor, _ = o.drivers
    assert ctor.lift.p50 == D("0.08") * D(3) / D(24)


def test_a_flash_slot_with_no_orders_today_uses_its_share_of_the_hours():
    o = price_option(_flash(6), _facts(price_factor=D("0.85")))
    ctor, _ = o.drivers
    assert ctor.lift.p50 == D("0.08") * D("0.25")


# -- 4: the phí dịch vụ a shop pays is in the re-priced fees ----------------------------------


def _income(service):
    return LineIncome(
        fees=(("phi_co_dinh", D(10_500)), (FEE_SERVICE, D(service))),
        commission=D(0), net_shipping=D(0), return_shipping=D(0), refund=D(0),
        compensation=D(0), tax_withheld=D(0), seller_coin=D(0), trade_in=D(0), payout=None,
    )  # fmt: skip


def _env(lines, fees):
    """``fees``: a real ``FeeContext`` -- the shop's fee formulas and learned service rate now come
    from ``shopee_analytics`` (``fee_table``), not from the env's own reading of its lines."""
    return RecoEnv(
        ctx=None,
        view=SimpleNamespace(pairs=[(ln, None) for ln in lines], fees=fees),
        as_of=AS_OF,
    )


def _fees(service_rate=None):
    from juli_backend.services.shopee_analytics.catalog import Catalog
    from juli_backend.services.shopee_analytics.engine import build_fee_context

    return build_fee_context(["i1"], Catalog(), None, service_rate)


def _ln(order_id, income=None):
    return OrderLine(
        order_id=order_id, sku="A", product_id="i1", order_date=AS_OF, qty=1,
        original_price=D(100_000), deal_price=D(100_000), income=income,
    )  # fmt: skip


def test_an_enrolled_shops_service_fee_joins_the_formula_at_its_own_rate():
    env = _env([_ln("o1", _income(7_900)), _ln("o2", _income(7_900)), _ln("o3")], _fees(D("0.079")))
    assert env.service_fee_rate == D("0.079")
    formula = env.schedule("i1").formula_on(AS_OF)
    assert formula is not None
    service = [c for c in formula.components if c.code == FEE_SERVICE]
    assert len(service) == 1 and service[0].rate == D("0.079")
    # the category rate of an item with no category (default) + 6 % giao dịch + 7,9 % dịch vụ
    # (+ 3.000đ hạ tầng): the Δ fee rate of a price change is what the shop really pays
    default = seed_schedule(D("0.105")).formula_on(AS_OF)
    assert default is not None
    assert formula.pct_rate_on_buyer_paid == default.pct_rate_on_buyer_paid + D("0.079")
    (line,) = [ln for ln in env.lines_for(["i1"]) if ln.order_id == "o1"]
    assert line.income is None  # reported fees dropped: the formula above prices it
    fee = formula.fee(line).total
    assert fee == D(100_000) * formula.pct_rate_on_buyer_paid + 3_000


def test_a_shop_charged_no_service_fee_keeps_the_formula():
    fees = _fees(None)
    env = _env([_ln("o1", _income(0)), _ln("o2")], fees)
    assert env.service_fee_rate is None
    assert env.schedule("i1") is fees.schedule("i1")


def test_a_formula_that_already_has_the_service_fee_is_not_charged_twice():
    from juli_backend.services.shopee_analytics import fee_table

    (version,) = seed_schedule(D("0.105")).versions
    own = FeeComponent(FEE_SERVICE, FeeKind.PCT, rate=D("0.05"))
    schedule = FeeSchedule((type(version)(version.effective_from, (*version.components, own)),))
    out = fee_table.with_service_fee(schedule, D("0.079"))
    formula = out.formula_on(AS_OF)
    assert formula is not None
    assert [c.rate for c in formula.components if c.code == FEE_SERVICE] == [D("0.05")]


# -- the sample shop, through the builder's evaluate path --------------------------------------


async def test_sample_shop_price_and_promotion_estimates_stay_within_their_bounds(engine):
    """Nước rửa chén on the sample shop (END 2026-11-10): 61 of its 109 orders hold "500ml hương
    chanh" (105 units, 6.195.000đ). Pinned numbers after the fix (prod 2026-11-15 showed 995k,
    +299.919đ and a whole-day Flash Sale).

    Batch 1123-a: the learned phí dịch vụ rate is the service part of Phí Dịch Vụ (minus the
    3.000đ hạ tầng the formula already charges), 5,86 % here instead of the 7,9 % the old env
    reading took from the whole Phí Dịch Vụ (which charged the infrastructure fee twice). A lower
    fee rate means a discount saves less in fees, so the programme's cost rises by about
    0,0204 x the 619.500đ it discounts (+13k: 482.068 -> 495.124); the other figures move by
    the same fee-rate difference and are re-pinned from the run."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.sample_shop.catalog import PRODUCTS
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_builder.engine_families import integrate
    from tests.unit.test_sample_shop import END, NOW, _load
    from tests.unit.test_shopee_builder import S

    factory, report = await _load(engine)
    product = PRODUCTS[0]
    item, lemon = product.item_id, product.variations[0].model_id
    every = [v.model_id for v in product.variations]
    specs = {
        "programme_one": S(
            kind="product_discount",
            item_id=item,
            variations=[{"variation_id": lemon, "discount_pct": 10}],
        ),
        "price_one": S(
            kind="price", item_id=item, variations=[{"variation_id": lemon, "change_pct": 5}]
        ),
        "flash_2h": S(
            kind="flash_sale",
            item_id=item,
            units=100,
            slot_hours=2,
            variations=[{"variation_id": v, "discount_pct": 15} for v in every],
        ),
    }
    async with factory() as session:
        async with with_shop_scope(session, report.shop_id):
            ctx = await builder.build_context(
                session, report.shop_id, list(specs.values()), as_of=END, now=NOW
            )
            # batch 1123-e5: the generator states Phí Dịch Vụ = 7,9 % of the buyer-paid value plus
            # hạ tầng, with hạ tầng (3.000đ) as its own line, like a real file; the learner takes
            # Phí Dịch Vụ minus it, so 7,9 % (7,71 % over the pre-voucher price; was 5,86 %)
            assert ctx.env.service_fee_rate == D("0.0771")
            out = {
                name: integrate.evaluate(ctx, spec, str(report.shop_id))[0].result
                for name, spec in specs.items()
            }
    one, price, flash = out["programme_one"], out["price_one"], out["flash_2h"]
    assert one is not None and price is not None and flash is not None
    assert one.likely is not None and price.likely is not None and flash.likely is not None

    # 1. 10 % of the lemon variation's 30-day sales is 619.500đ gross; net of the fees it saves,
    # on its orders (+ the extra ones) it costs ~500k -- not the 1M of every order of the product
    assert one.days == 30
    assert float(one.cost_total) < 619_500
    # F2 (2026-11-16): the base is the adaptive window per metric, not the fixed 30 days
    assert float(one.cost_total) == pytest.approx(
        483_268, rel=0.02
    )  # was 495_124 at 5,86 %: 1123-e5 hạ tầng now sits inside Phí Dịch Vụ, so the rate is 7,71 %

    # 2. +5 % on 105 units × 59.000đ = 309.750đ gross: the price effect can never exceed it
    parts = {p.key: float(p.amount) for p in price.build_up}
    assert 0 < parts["price"] < 309_750
    d_profit = float(price.likely.profit or 0) - float(price.before.profit or 0)
    assert d_profit < 309_750
    assert d_profit == pytest.approx(
        147_788, rel=0.02
    )  # was 141_818 at 7,9 %: +5 % on 309.750đ pays 2,04 points less fee

    # 3. a 2-hour slot on one day: 2/24 of the day's 3,6 orders get the −15 %
    assert flash.days == 1
    d_flash = float(flash.likely.profit or 0) - float(flash.before.profit or 0)
    assert -10_000 < d_flash < 0
    assert d_flash == pytest.approx(-3_523, rel=0.05)
