"""R1 round 2 (owner 2026-11-25): the gate covers EVERY profit level (gộp, đóng góp, ròng, their
margins, ROI) and every product with its own known share; the share is on Shopee's confirmed
basis (GMV after the seller-borne voucher); a product's contribution counts whole known orders.
Synthetic data only."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics import channel_split
from juli_backend.services.shopee_analytics.catalog import RawItem, build_catalog
from juli_backend.services.shopee_analytics.engine import resolve_costs, to_shop_lines
from juli_backend.services.shopee_analytics.rules_view import ProfitRules
from juli_backend.services.shopee_profit import shop_profit as sp
from tests.unit.test_c1_in_transit_ads import ZERO, _pair
from tests.unit.test_shopee_analytics_pure import _raw

D = Decimal


def _line(order, product, value, contribution=None, day=4):
    ln, pb = _pair(order, value, day, contribution)
    return replace(ln, product_id=product), pb


def _profit(pairs):
    return sp.shop_profit(pairs, campaigns=[sp.AdCampaign("c", ZERO)], product_ad_spend={})


def test_share_is_on_the_confirmed_basis_after_the_seller_voucher():
    ln, pb = _pair("o1", 1_000_000, 4, 300_000)
    ln = replace(ln, shop_voucher_share=D(6_000))
    pairs = [(ln, pb)]
    fig = sp.known_cost_profit(_profit(pairs), pairs, D(994_000))  # Shopee GMV is after the voucher
    assert fig.gmv_share_pct == D("100.0")
    assert sp.gate_profit(fig).profit is not None  # was 100.6 % -> hidden


@pytest.mark.parametrize(("known", "shown"), [(699_000, False), (700_000, True), (1_000_000, True)])
def test_product_gate_uses_the_products_own_known_share(known, shown):
    pairs = [_line("k", "A", known, known // 4)]
    if known < 1_000_000:
        pairs.append(_line("u", "A", 1_000_000 - known))
    pp = sp.product_profits(pairs, {})["A"]
    assert (sp.product_profit_shown(pp) is not None) is shown
    assert (sp.product_margin_pct_shown(pp) is not None) is shown


def test_product_contribution_counts_whole_known_orders():
    # order o1 has an A line (known) and a B line (unknown): the whole order is out of both
    pairs = [
        _line("o1", "A", 500_000, 100_000),
        _line("o1", "B", 500_000),
        _line("o2", "A", 500_000, 200_000),
    ]
    pp = sp.product_profits(pairs, {})["A"]
    assert pp.contribution == D(200_000)
    assert pp.buyer_paid_covered == D(500_000)


def _view(known, shop):
    pairs = [_line("o1", "A", known, known // 4)]
    return SimpleNamespace(
        profit=_profit(pairs),
        pairs=pairs,
        metrics=SimpleNamespace(gmv=D(shop), orders=1),
        data=SimpleNamespace(
            ads_daily=SimpleNamespace(spend_by_day={}), totals=SimpleNamespace(basis="daily")
        ),
        coverage=None,
        gmv_from_totals=False,
        window=SimpleNamespace(days=7),
        costs=SimpleNamespace(cogs_is_real=lambda sku: True),
    )


def test_every_shop_level_is_withheld_below_70():
    view = _view(600_000, 1_000_000)
    base = SimpleNamespace(total=lambda key: D(1_000_000) if key == "gmv" else D(3))
    kpis = channel_split._kpis(view, base, None)
    for key in (
        "profit", "gross_profit", "contribution", "margin_gross_pct",
        "margin_contribution_pct", "margin_pct", "roi",
    ):  # fmt: skip
        assert kpis[key] is None, key
    assert kpis["gmv"] == 1_000_000 and kpis["cost_ads"] is not None


def test_export_profit_sheet_levels_are_dashes_when_withheld():
    from openpyxl import Workbook

    from juli_backend.services.exports import profit_bridge
    from juli_backend.services.exports import tong_quan_xlsx as tq

    def levels(known):
        bridge = profit_bridge.profit_bridge(_view(known, 1_000_000))
        data = SimpleNamespace(
            product_name=None, shop_name="s", platform="shopee", start=date(2026, 11, 1),
            end=date(2026, 11, 7), prev_start=date(2026, 10, 25), prev_end=date(2026, 10, 31),
            now=SimpleNamespace(offer_cost=None),
        )  # fmt: skip
        wb = Workbook()
        tq._profit(wb, data, bridge)
        ws = wb[tq.SHEET_PROFIT]
        rows = {c.value: ws.cell(c.row, 2).value for c in ws["A"] if c.value}
        return bridge, rows

    bridge, rows = levels(600_000)
    assert bridge.withheld and bridge.revenue > 0 and bridge.cogs > 0  # the lines stay
    assert rows[tq.GROSS_LABEL] == tq.DASH and rows[tq.CONTRIBUTION_LABEL] == tq.DASH
    assert rows[tq.PROFIT_LABEL] == tq.DASH and rows[tq.MARGIN_LABEL] == tq.DASH
    bridge, rows = levels(800_000)
    assert not bridge.withheld and str(rows[tq.GROSS_LABEL]).startswith("=")


def test_a_stored_day_with_no_costed_order_is_not_a_profit_for_the_measure():
    from juli_backend.services.shopee_recommendations import running

    wrong = SimpleNamespace(profit=D(-60_000), orders=3, buyer_paid_known=None)
    fine = SimpleNamespace(profit=D(30_000), orders=3, buyer_paid_known=D(100_000))
    assert running.stored_day_profit(wrong) is None
    assert running.stored_day_profit(fine) == 30_000.0


def test_pack_variations_sharing_one_sku_cost_3x_5x_10x():
    catalog = build_catalog([RawItem("11", "", "Găng", None, "G1", None)])
    raws = [
        _raw(i, variation_id=f"v{n}", variation_name=f"Combo {n}", sku="G1", item_id="sku:G1")
        for i, n in enumerate((3, 5, 10), 1)
    ]
    rules = ProfitRules(sku_cost={"G1": D(10_000)}, pack_count={"11:v5": 5})
    lines = to_shop_lines(raws, catalog, rules)
    costs = resolve_costs(lines, rules)
    by_pack = {sl.pack_count: costs.by_key[sl.cost_key].cogs for sl in lines}
    assert by_pack == {3: D(30_000), 5: D(50_000), 10: D(100_000)}
    assert datetime and date  # imports used by the fixtures above


def test_a_products_share_counts_orders_on_the_way_and_never_cancelled_ones():
    """Shopee's confirmed GMV has the orders on the way, no cancelled one; so has the share."""
    from juli_backend.services.shopee_profit.order_profit import OrderStatus
    from juli_backend.services.shopee_profit.shop_profit import (
        product_known_share_pct,
        shop_profit,
        stored_day_profit_trusted,
    )
    from tests.unit.test_c1_in_transit_ads import _pair

    known = _pair("o1", 100_000, 4, 40_000)
    gone = _pair("c1", 100_000, 4, status=OrderStatus.CANCELLED)
    moving = _pair("t1", 100_000, 4, status=OrderStatus.IN_TRANSIT)

    def share(pairs):
        pp = shop_profit(pairs, campaigns=[], product_ad_spend={}).products["A"]
        return product_known_share_pct(pp)

    assert share([known, gone]) == 100
    assert share([known, moving]) == 50
    assert stored_day_profit_trusted([known, gone], known[0].order_date)
