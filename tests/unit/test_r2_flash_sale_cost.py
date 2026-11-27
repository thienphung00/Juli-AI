"""Owner #98: a Flash Sale's cost = Σ over its variations (today's price − flash price) x the units
expected to sell in the slot -- never more units than the slot's quantity (suất). The expected
units are the engine's own after-orders in the slot's hours. Invented figures only."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.facts import LiftEvidence, PriceFacts
from juli_backend.services.shopee_builder.engine_families.families import price_option
from juli_backend.services.shopee_builder.outcome import with_discount_given
from tests.unit.test_engine_families import b, base


def flash(units: int, hours: int = 3) -> sp.FlashSaleSpec:
    return sp.FlashSaleSpec(
        kind="flash_sale",
        item_id="i1",
        units=units,
        slot_hours=hours,
        variations=[sp.VariationPrice(discount_pct=20)],
    )


def facts(cut: D | None = D(20_000), upo: D = D(1)) -> PriceFacts:
    return PriceFacts(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        profit_per_order_after=D(2_000),  # 18.000đ less profit per order (fees saved: 2.000đ)
        price_factor=D("0.8"),
        contribution_rate=D("0.3"),
        ctor=LiftEvidence(b(0.02, 0.06, 0.1), "product_history"),
        units_per_order=upo,
        orders_per_day=D("9.5"),
        flash_cut_per_order=cut,
    )


def test_the_cut_per_order_sums_each_variation_s_cut_times_its_units():
    lines = [
        SimpleNamespace(order_id="o1", sku="a", qty=2),
        SimpleNamespace(order_id="o2", sku="a", qty=1),
        SimpleNamespace(order_id="o2", sku="b", qty=1),
    ]
    rows = [
        {"sku": "a", "price_before": 100_000, "price_after": 80_000},
        {"sku": "b", "price_before": 50_000, "price_after": 45_000},
    ]
    # (20.000 x 3 units + 5.000 x 1 unit) / 2 orders
    assert adapters.flash_cut_per_order(lines, rows) == D(32_500)
    # a flash price above today's price is no cut
    up = [{"sku": "a", "price_before": 100_000, "price_after": 110_000}]
    assert adapters.flash_cut_per_order(lines[:1], up) == D(0)


def test_cap_not_binding_cost_is_the_cut_on_the_engine_s_slot_orders():
    r = run(base(), price_option(flash(units=100), facts()), seed=1, n=400)
    assert r.days == 1 and len(r.offers) == 1
    o = r.offers[0]
    # the slot is 3 of the day's 24 hours: its share of the engine's after-orders
    assert float(o.expected_uses) == pytest.approx(float(r.likely.orders) * 3 / 24, rel=1e-9)
    assert o.per_use == D(20_000)
    assert r.cost_total == o.total == o.expected_uses * D(20_000)
    assert o.expected_uses < 100


def test_cap_binding_never_more_units_than_the_slot():
    for upo in (D(1), D(2)):
        r = run(base(), price_option(flash(units=1), facts(upo=upo)), seed=1, n=400)
        o = r.offers[0]
        assert o.expected_uses * upo == 1  # one suất = 1 unit
        assert r.cost_total == D(20_000) / upo


def test_the_cut_counts_once_in_profit():
    """The offer carries the gross cut; the per-order profit keeps only the fees the lower price
    saves, so Δ profit at today's volume = − net cut on the slot's orders."""
    o = price_option(flash(units=100), facts())
    reach = o.offers[0].use_share.p50
    assert reach == D(3) / D(24)
    # 20.000 - 18.000 x reach (the old price effect) + 20.000 x reach (the cut moved to the offer)
    assert o.profit_per_order_after == D(20_000) + D(2_000) * reach


def test_no_cut_known_keeps_no_offer():
    o = price_option(flash(units=100), facts(cut=None))
    assert o.offers == ()


def test_the_card_reads_the_engine_s_cost():
    r = run(base(), price_option(flash(units=100), facts()), seed=1, n=200).json()
    card = {"change_kind": "flash_sale", "certain": {"discount_given": 999_999}}
    out, info = with_discount_given(r, card)
    assert info is not None and out is not None
    assert info["amount"] == r["cost"]["offers"][0]["total"]
    assert out["cost"]["discount_given"] == r["cost"]["offers"][0]["total"]
    assert out["cost"]["text"].startswith("Tiền giảm cho khách ~")


def test_the_builder_cost_line_is_the_engine_s_flash_cost():
    from juli_backend.services.shopee_builder.outcome import voucher_cost_from_result

    r = run(base(), price_option(flash(units=100), facts()), seed=1, n=200).json()
    money_layer = {"amount": 1, "period_days": 1, "label": "Lợi nhuận mất đi nếu số đơn không đổi"}
    cost = voucher_cost_from_result("flash_sale", money_layer, r)
    assert cost["amount"] == r["cost"]["total"] == r["cost"]["offers"][0]["total"]
    assert cost["source"] == "result"
