"""R1 (owner 2026-11-25): Lợi nhuận ròng and what derives from it (margin, ROI) are shown only
when the known-cost orders are 70-100 % of the period's GMV; otherwise "—" (None). One gate
(``shop_profit.gate_profit``, applied in ``shared.shop_profit_of``) feeds every reader. Stored
day rows written before the in-transit fix show "—". Synthetic data only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.exports import collect, profit_bridge
from juli_backend.services.shopee_analytics import channel_split, shared
from juli_backend.services.shopee_profit.order_profit import OrderStatus
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    gate_profit,
    known_cost_profit,
    shop_profit,
    stored_day_profit_trusted,
)
from tests.unit.test_c1_in_transit_ads import ZERO, _pair


def _fig(known_gmv, shop_gmv):
    pairs = [_pair("o1", known_gmv, 4, known_gmv // 4)]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", ZERO)], product_ad_spend={})
    return known_cost_profit(sp, pairs, None if shop_gmv is None else Decimal(shop_gmv))


@pytest.mark.parametrize(
    ("known", "shop", "share", "shown"),
    [
        (699_000, 1_000_000, "69.9", False),
        (700_000, 1_000_000, "70.0", True),
        (1_000_000, 1_000_000, "100.0", True),
        (1_001_000, 1_000_000, "100.1", False),
    ],
)
def test_gate_range_is_70_to_100_inclusive(known, shop, share, shown):
    fig = _fig(known, shop)
    assert fig.gmv_share_pct == Decimal(share)
    assert fig.profit is not None  # the raw figure exists
    out = gate_profit(fig)
    assert (out.profit is not None) is shown
    assert (out.margin_pct is not None) is shown
    assert (out.product_profit is not None) is shown
    assert out.withheld is (not shown)
    assert out.json()["bridge"]["profit"] == (out.json()["profit"])
    assert out.orders == fig.orders and out.gmv == fig.gmv  # the coverage stays


def test_unknown_share_keeps_today_unless_no_known_orders():
    assert gate_profit(_fig(1_000_000, None)).profit is not None  # reported, not gated
    none = known_cost_profit(
        shop_profit([], campaigns=[AdCampaign("c", ZERO)], product_ad_spend={}), [], None
    )
    assert gate_profit(none).profit is None


def _view(known_gmv, shop_gmv, in_transit=False):
    pairs = [_pair("o1", known_gmv, 4, known_gmv // 4)]
    if in_transit:
        pairs.append(_pair("o2", 50_000, 5, status=OrderStatus.IN_TRANSIT))
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", ZERO)], product_ad_spend={})
    return SimpleNamespace(
        profit=sp,
        pairs=pairs,
        metrics=SimpleNamespace(gmv=Decimal(shop_gmv), orders=1),
        data=SimpleNamespace(
            ads_daily=SimpleNamespace(spend_by_day={}), totals=SimpleNamespace(basis="daily")
        ),
        # b370e528: the profit gate reads whether ad spend is known at all; here it is (0đ)
        ads=SimpleNamespace(known_spend=Decimal(0)),
        coverage=None,
        gmv_from_totals=False,
    )


def test_one_figure_across_readers_below_70():
    view = _view(600_000, 1_000_000)
    fig = shared.shop_profit_of(view)
    assert fig.profit is None and shared.shop_profit_raw(view).profit is not None
    fields = shared.shop_profit_fields(view)
    assert fields["profit"] is None and fields["margin_pct"] is None
    assert fields["shop_profit"]["profit"] is None
    bridge = profit_bridge.profit_bridge(view)
    assert bridge.profit is None and bridge.margin_pct is None
    assert bridge.revenue > 0 and bridge.cogs > 0  # the reconciliation lines stay raw
    assert bridge.known_gmv_share_pct == 60.0
    # the label keeps the coverage words
    assert fig.label == "trên 1 đơn có chi phí, 60,0 % GMV"


def test_one_figure_across_readers_in_range():
    view = _view(800_000, 1_000_000)
    p = shared.shop_profit_of(view).profit
    assert p is not None
    assert shared.shop_profit_fields(view)["profit"] == float(p)
    assert profit_bridge.profit_bridge(view).profit == float(p)


def test_channel_split_kpis_withhold_shop_profit_margin_and_roi(monkeypatch):
    view = _view(600_000, 1_000_000)
    base = SimpleNamespace(total=lambda key: Decimal(1_000_000) if key == "gmv" else Decimal(3))
    monkeypatch.setattr(channel_split, "total_base", lambda b, platform: b)
    kpis = channel_split._kpis(view, base, None)
    assert kpis["profit"] is None and kpis["margin_pct"] is None and kpis["roi"] is None
    assert kpis["gmv"] == 1_000_000  # GMV stays


def test_stored_day_with_in_transit_orders_is_not_trusted():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 900_000, 5, status=OrderStatus.IN_TRANSIT),
    ]
    assert stored_day_profit_trusted(pairs, date(2026, 11, 4), 100_000)
    assert not stored_day_profit_trusted(pairs, date(2026, 11, 5), 900_000)
    assert stored_day_profit_trusted(pairs, date(2026, 11, 20))  # no line: a zero-order day
    # known share of the day's GMV outside 70-100 %
    low = [_pair("a", 600_000, 6, 100_000), _pair("b", 400_000, 6)]
    assert not stored_day_profit_trusted(low, date(2026, 11, 6), 1_000_000)
    assert stored_day_profit_trusted(low, date(2026, 11, 6), 1_000_000, check_share=False)


def test_theo_ngay_wrong_day_shows_dash():
    """The export's "Theo ngày": stored profit = -ads of an all-in-transit day -> None."""
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 900_000, 5, status=OrderStatus.IN_TRANSIT),
    ]
    view = SimpleNamespace(pairs=pairs)
    wrong = SimpleNamespace(profit=Decimal(-60_000), gmv=Decimal(900_000))
    good = SimpleNamespace(profit=Decimal(30_000), gmv=Decimal(100_000))
    assert collect._stored_day_profit(view, wrong, date(2026, 11, 5)) is None
    assert collect._stored_day_profit(view, wrong, date(2026, 11, 5), product=True) is None
    assert collect._stored_day_profit(view, good, date(2026, 11, 4)) == 30_000.0
    assert collect._stored_day_profit(view, None, date(2026, 11, 4)) is None


async def test_seeded_shop_below_70_is_dash_on_every_screen(session, monkeypatch):
    """The seeded shop knows 57 % of its 7-day GMV: Tổng quan, Sản phẩm and Kế hoạch all show
    "—" for the profit and the margin while GMV and đơn stay."""
    from juli_backend.services.shopee_analytics import materialize, queries
    from juli_backend.services.shopee_recommendations import config, plan_aggregate, plan_base
    from juli_backend.services.shopee_recommendations.loader import load_env
    from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

    seeded = await seed_shopee_shop(session, rules=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    kw = {"period": "7d", "as_of": CUR_END}
    ov = await queries.overview(session, seeded.shop_id, **kw)
    mx = await queries.matrix(session, seeded.shop_id, **kw)
    env = await load_env(session, seeded.shop_id, as_of=CUR_END)
    assert env is not None
    base = plan_base.base_json(env)
    today = plan_aggregate._today(env, None)
    frozen = plan_aggregate._today(env, base)
    assert ov["shop_profit"]["gmv_share_pct"] < 70
    for fig in (ov["shop_profit"], mx["shop_profit"], today["shop_profit"], base["shop_profit"]):
        assert fig["profit"] is None and fig["margin_pct"] is None
        assert fig["orders"] > 0 and fig["bridge"]["profit"] is None
    assert ov["profit"]["profit_vnd"] is None and ov["profit"]["margin_pct"] is None
    assert ov["kpi_strip"]["profit"]["value"] is None
    assert ov["shop_metrics"]["profit"] is None and ov["shop_metrics"]["margin_pct"] is None
    for row in (today, frozen, base):
        assert row["profit_30d"] is None and row["margin_pct"] is None
    assert today["gmv_30d"] > 0 and ov["kpi_strip"]["gmv"]["value"] > 0
