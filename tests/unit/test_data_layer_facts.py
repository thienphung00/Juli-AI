"""Data layer, Track FACT (batch-1124-c-data, decisions #62-#66): the stored daily facts.

Synthetic Shopee shop only (``tests.support.shopee_analytics``, SQLite, invented figures). Rows:
F1 (components = today's window figures, 7/30/90 d, shop + product), F2 / A7 / A9 (channel x
discount cells add up to the product row; TTLK kept against an ads overlay above the GMV), F3
(campaign days), F4 (``sums_across`` refuses product đơn -> shop đơn), F5 (version / fee stamp
triggers, idempotent, unchanged rows not rewritten), A1 (one AFF basis), A5 (product report
wins), A6 (each ads day once), A7 (affiliate source reconcile check).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    CampaignMetricsDaily,
    ProductChannelMetricsDaily,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.services.metrics import (
    COMPONENTS,
    Dim,
    InvalidSum,
    can_sum,
    check_sum,
    evaluate,
)
from juli_backend.services.metrics.allocation import PeriodValue, deoverlap_periods
from juli_backend.services.metrics.registry import METRIC_ALIASES, METRICS
from juli_backend.services.shopee_analytics import (
    affiliate_check,
    day_facts,
    loaders,
    materialize,
    service,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.ladder import affiliate_cost, ladder_of
from tests.support.shopee_analytics import (
    CUR_END,
    CUR_START,
    PREV_START,
    _daily,
    period_row,
    seed_shopee_shop,
)

COMPS = day_facts.COMPONENT_COLUMNS


async def _stored_sum(session, model, shop_id, start, end, item: str | None = None):
    cols = [func.sum(getattr(model, c)) for c in COMPS]
    q = select(*cols).where(model.shop_id == shop_id, model.day >= start, model.day <= end)
    if item is not None:
        q = q.where(model.item_id == item)
    row = (await session.execute(q)).one()
    return {c: (D(0) if v is None else D(v)) for c, v in zip(COMPS, row, strict=True)}


async def _window_view(session, shop_id, start, end):
    ctx = await loaders.load_context(session, shop_id)
    return await service.load_view(session, shop_id, ctx, Window(start, end))


# -- F1 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("days", [7, 30, 90])
async def test_f1_stored_components_equal_the_window_figures_shop_and_product(session, days):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    start = CUR_END - timedelta(days=days - 1)
    view = await _window_view(session, sid, start, CUR_END)
    want = day_facts.scope_components(view.pairs)
    got = await _stored_sum(session, ShopeeShopMetricsDaily, sid, start, CUR_END)
    for c in COMPS:
        assert got[c] == (want[c] or D(0)), c
    # the window's screen figures, from the summed stored components through the registry
    assert got["net_revenue"] == view.profit.buyer_paid
    assert got["affiliate_commission"] == (affiliate_cost(view.pairs) or D(0))
    ladder = ladder_of(view.pairs, ads_spend=D(0), other_marketing=D(0))
    assert evaluate("contribution", got).value == ladder.get("contribution").quantize(D(1))
    # product level
    for item, pairs in day_facts.pairs_by_product(view.pairs).items():
        want_p = day_facts.scope_components(pairs)
        got_p = await _stored_sum(session, ShopeeProductMetricsDaily, sid, start, CUR_END, item)
        for c in COMPS:
            assert got_p[c] == (want_p[c] or D(0)), (item, c)


async def test_f1_a_day_without_order_lines_has_no_components_not_zero(session):
    seeded = await seed_shopee_shop(session)
    t = ShopeeShopMetricsDaily
    day = PREV_START + timedelta(days=1)  # a shop_overview day with no order line
    row = (
        await session.execute(select(t).where(t.shop_id == seeded.shop_id, t.day == day))
    ).scalar_one()
    assert row.net_revenue is None and row.cogs is None and row.gmv is not None


# -- F2 / A7 / A9 ------------------------------------------------------------------------------


async def test_f2_channel_cells_add_up_to_each_product_day(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    p, c = ShopeeProductMetricsDaily, ProductChannelMetricsDaily
    products = (
        await session.execute(select(p).where(p.shop_id == sid, p.item_id != RESIDUAL_ITEM))
    ).scalars()
    checked = 0
    for row in products:
        cells = (
            (
                await session.execute(
                    select(c).where(c.shop_id == sid, c.day == row.day, c.item_id == row.item_id)
                )
            )
            .scalars()
            .all()
        )
        if not row.gmv and not row.orders:
            continue
        checked += 1
        assert sum((x.gmv for x in cells), D(0)) == row.gmv
        assert sum(x.orders for x in cells) == row.orders
        assert sum(x.units for x in cells) == row.units
        for col in ("net_revenue", "cogs", "fees", "offer_promo", "affiliate_commission"):
            want = getattr(row, col) or D(0)
            assert sum((getattr(x, col) or D(0) for x in cells), D(0)) == want, col
        assert {x.channel for x in cells} <= {"organic", "ads", "affiliate"}
    assert checked > 5
    # the affiliate line of the fixture (day 4, 1001) is TTLK, with its commission
    aff = (
        (await session.execute(select(c).where(c.shop_id == sid, c.channel == "affiliate")))
        .scalars()
        .all()
    )
    assert aff and sum((x.affiliate_commission or D(0) for x in aff), D(0)) > 0


@dataclass
class _Ln:
    order_id: str
    product_id: str
    order_value: D
    affiliate: bool = False
    shop_voucher_share: D = D(0)
    status: str = "delivered"
    qty: int = 1


@dataclass
class _Pb:
    revenue: D
    promo_discount: D = D(0)
    voucher: D = D(0)
    bundle: D = D(0)
    commission: D | None = None
    excluded_reason: str | None = None
    organic_contribution: D | None = D(10)
    contribution: D | None = D(10)
    cogs: D | None = D(5)
    vat_input_credit: D = D(0)
    packaging: D | None = D(0)
    fees_total: D | None = D(2)
    income_costs_total: D | None = D(0)


def _pair(order: str, value: int, *, aff: bool = False, promo: int = 0, comm: int | None = None):
    return (
        _Ln(order, "9", D(value), affiliate=aff),
        _Pb(
            D(value) - D(promo),
            promo_discount=D(promo),
            commission=None if comm is None else D(comm),
        ),
    )


def test_a7_ads_overlay_above_the_gmv_keeps_the_affiliate_orders_and_records_the_cap(monkeypatch):
    monkeypatch.setattr(day_facts, "counts_in_sales", lambda ln: True)
    pairs = [
        _pair("o1", 100, aff=True, comm=8),  # TTLK, no discount
        _pair("o2", 100, aff=True, promo=10, comm=8),  # TTLK, discounted
        _pair("o3", 150, promo=20),  # rest, discounted
        _pair("o4", 150),  # rest
    ]
    inp = day_facts.ChannelInput("9", D(500), 4, pairs, ads_gmv=D(900), ads_spend=D(60))
    rows = day_facts.channel_rows(inp, shop_id=None, day=date(2026, 11, 12), version="v")
    by = {(r["channel"], r["discounted"]): r for r in rows}
    aff = [r for r in rows if r["channel"] == "affiliate"]
    assert sum((r["gmv"] for r in aff), D(0)) == D(200)  # TTLK kept, first
    assert sum(r["orders"] for r in aff) == 2
    ads = [r for r in rows if r["channel"] == "ads"]
    assert sum((r["gmv"] for r in ads), D(0)) == D(300)  # capped at what TTLK leaves
    assert by[("ads", "without")]["capped_gmv"] == D(600)  # the cap that bites, recorded
    assert sum((r["gmv"] for r in rows), D(0)) == D(500)
    assert sum(r["orders"] for r in rows) == 4
    assert sum((r["ads_spend"] or D(0) for r in rows), D(0)) == D(60)
    # A9: with + without = the product total; discounted lines land on "with"
    assert by[("affiliate", "with")]["gmv"] == D(100)
    assert by[("affiliate", "without")]["gmv"] == D(100)
    with_ = sum((r["gmv"] for r in rows if r["discounted"] == "with"), D(0))
    without = sum((r["gmv"] for r in rows if r["discounted"] == "without"), D(0))
    assert with_ + without == D(500)
    assert sum((r["affiliate_commission"] or D(0) for r in rows), D(0)) == D(16)


def test_a9_gmv_the_lines_do_not_explain_is_unknown_never_guessed(monkeypatch):
    monkeypatch.setattr(day_facts, "counts_in_sales", lambda ln: True)
    inp = day_facts.ChannelInput("9", D(400), 3, [_pair("o1", 100)], ads_gmv=None, ads_spend=None)
    rows = day_facts.channel_rows(inp, shop_id=None, day=date(2026, 11, 12), version="v")
    unknown = [r for r in rows if r["discounted"] == "unknown"]
    assert sum((r["gmv"] for r in unknown), D(0)) == D(300)
    assert sum((r["gmv"] for r in rows), D(0)) == D(400)
    assert sum(r["orders"] for r in rows) == 3
    assert not [r for r in rows if r["channel"] == "ads"]  # no ads report: no ads cell


# -- F3 ----------------------------------------------------------------------------------------


def _camp(shop_id, day, segment, cost, gmv):
    return _daily(
        shop_id,
        day,
        "ads",
        segment,
        impressions=500,
        clicks=20,
        orders=2,
        gmv=gmv,
        dataset="ads_campaign_daily",
        order_type="placed",
        extra={"cost": cost, "ad_type": "product_auto", "daily_budget": 50_000},
    )


async def test_f3_campaign_days_equal_the_connector_report_and_skip_empty_campaigns(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    sid = seeded.shop_id
    d1, d2 = CUR_START + timedelta(days=1), CUR_START + timedelta(days=2)
    session.add_all(
        [
            _camp(sid, d1, "all", 0, 0),  # shop-level ROAS row: not a campaign
            _camp(sid, d1, "c1", 30_000, 120_000),
            _camp(sid, d1, "c2", 0, 0),  # neither spent nor sold: no row
            _camp(sid, d2, "c1", 20_000, 0),  # spent, sold nothing: a row
        ]
    )
    await session.flush()
    await materialize.backfill_shop(session, sid)
    t = CampaignMetricsDaily
    rows = (await session.execute(select(t).where(t.shop_id == sid))).scalars().all()
    assert {(r.day, r.campaign_id) for r in rows} == {(d1, "c1"), (d2, "c1")}
    assert sum((r.spend for r in rows), D(0)) == D(50_000)
    assert sum((r.gmv for r in rows), D(0)) == D(120_000)
    # a day before the first campaign day has no row (missing, never 0)
    assert not [r for r in rows if r.day < d1]
    assert all(r.derivation_version for r in rows)
    assert {r.daily_budget for r in rows} == {D(50_000)}


# -- F4 ----------------------------------------------------------------------------------------


def test_f4_every_component_declares_what_it_sums_over_and_the_refusal():
    assert all(isinstance(c.sums_across, frozenset) for c in COMPONENTS.values())
    with pytest.raises(InvalidSum) as excinfo:
        check_sum("orders", [Dim.day, Dim.item])
    assert excinfo.value.refused == frozenset({Dim.item})
    assert can_sum("orders", ["day", "channel", "discounted"])
    assert can_sum("gmv", list(Dim))
    assert not can_sum("line_orders", ["item"])
    assert not can_sum("contribution_products", ["campaign"])
    assert not can_sum("sale_fees", ["day"])  # a per-unit value sums over nothing


def test_a9_margin_before_marketing_is_bien_dong_gop_not_a_second_formula():
    assert METRIC_ALIASES["margin_before_marketing"] == "margin_contribution"
    assert "margin_before_marketing" not in METRICS
    comps = {
        "net_revenue_known": D(1000),
        "cogs": D(300),
        "packaging": D(10),
        "fees": D(100),
        "shipping_net": D(20),
        "ads_spend_known": D(200),
        "affiliate_commission_known": D(50),
        "other_marketing": D(0),
    }
    before = evaluate("margin_before_marketing", comps)
    assert before.value == evaluate("margin_contribution", comps).value == D("57.0")
    assert evaluate("margin", comps).value == D("32.0")  # Tổng quan / plan: after ads + AFF


def test_a1_the_profit_deducts_the_same_aff_component_the_aff_row_shows():
    assert "affiliate_commission" in METRICS["profit"].components or "affiliate_commission" in str(
        METRICS["profit"].formula
    )
    assert COMPONENTS["affiliate_commission"].sources  # one source: ladder.affiliate_cost
    comps = {k: D(0) for k in ("net_revenue_known", "cogs", "packaging", "fees", "shipping_net")}
    comps |= {"ads_spend_known": D(0), "other_marketing": D(0), "affiliate_commission_known": D(49)}
    assert evaluate("profit", comps).value == D(-49)


# -- F5 ----------------------------------------------------------------------------------------


async def _built(session, sid):
    t = ShopeeShopMetricsDaily
    return dict((await session.execute(select(t.day, t.built_at).where(t.shop_id == sid))).all())


async def test_f5_a_same_data_rerun_rewrites_no_row(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    before = await _built(session, sid)
    p = ShopeeProductMetricsDaily
    pbefore = dict((await session.execute(select(p.id, p.built_at).where(p.shop_id == sid))).all())
    await materialize.backfill_shop(session, sid)
    session.expunge_all()
    assert await _built(session, sid) == before
    assert (
        dict((await session.execute(select(p.id, p.built_at).where(p.shop_id == sid))).all())
        == pbefore
    )


async def test_f5_a_registry_version_bump_makes_every_day_stale_and_rebuilds_once(
    session, monkeypatch
):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    assert await materialize.outdated_days(session, sid) == []
    monkeypatch.setattr(materialize, "DERIVATION_VERSION", "2099-01-01.1")
    stale = await materialize.outdated_days(session, sid)
    assert stale == sorted(await _built(session, sid))
    assert await materialize.rebuild_outdated(session, sid, limit=1000) == len(stale)
    assert await materialize.outdated_days(session, sid) == []
    assert await materialize.rebuild_outdated(session, sid) == 0  # idempotent
    t = ShopeeShopMetricsDaily
    stamps = set((await session.execute(select(t.derivation_version))).scalars().all())
    assert stamps == {materialize.stamp_of(await loaders.load_context(session, sid))}
    assert next(iter(stamps)).startswith("2099-01-01.1/r") and len(next(iter(stamps))) <= 32


async def test_f5_a_fee_schedule_change_makes_the_days_stale(session, monkeypatch):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    monkeypatch.setattr(materialize, "fee_digest", lambda ctx: "feedf00d")
    assert len(await materialize.outdated_days(session, sid)) == len(await _built(session, sid))


async def test_f5_the_ingest_hook_rebuilds_only_the_days_it_was_given(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    before = await _built(session, sid)
    day = CUR_START + timedelta(days=2)
    t = ShopeeShopMetricsDaily
    row = (await session.execute(select(t).where(t.shop_id == sid, t.day == day))).scalar_one()
    row.gmv = D(1)  # the stored day differs from the raw data
    await session.flush()
    await materialize.after_ingest(
        session, sid, platform="shopee", dataset="shop_overview", start=day, end=day
    )
    session.expunge_all()
    after = await _built(session, sid)
    assert [d for d in before if after[d] != before[d]] == [day]


# -- A5 ----------------------------------------------------------------------------------------


async def test_a5_product_gmv_is_the_product_report_where_it_has_the_day(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    sid = seeded.shop_id
    day = CUR_START  # order lines: 1001 (G1) and 1002 (N1)
    session.add(
        _daily(sid, day, "total", "all", orders=2, gmv=180_000, dataset="item_performance",
               item_id="1001")
    )  # fmt: skip
    await session.flush()
    await materialize.backfill_shop(session, sid)
    p = ShopeeProductMetricsDaily
    rows = {
        r.item_id: r
        for r in (await session.execute(select(p).where(p.shop_id == sid, p.day == day))).scalars()
    }
    assert rows["1001"].gmv == D(180_000) and rows["1001"].orders == 2
    assert rows["1001"].source == day_facts.SPLIT_ITEM_REPORT
    shop = (
        await session.execute(
            select(ShopeeShopMetricsDaily.gmv).where(
                ShopeeShopMetricsDaily.shop_id == sid, ShopeeShopMetricsDaily.day == day
            )
        )
    ).scalar_one()
    assert sum((r.gmv for r in rows.values()), D(0)) == shop  # residual closes it, never hidden


# -- A6 ----------------------------------------------------------------------------------------


def test_a6_overlapping_report_windows_count_each_day_once():
    d = date(2026, 11, 12)
    got = deoverlap_periods(
        [
            PeriodValue(d, d, D(300_000)),
            PeriodValue(d, d + timedelta(days=2), D(300_000)),  # 12-14: same orders again
            PeriodValue(d + timedelta(days=4), d + timedelta(days=12), D(90_000)),  # 16-24
        ]
    )
    assert got[d] == D(300_000)
    assert got[d + timedelta(days=1)] == got[d + timedelta(days=2)] == D(0)
    assert sum(got.values(), D(0)) == D(300_000) + D(90_000)
    # a window that runs past the read: only its days inside are counted (10 000 a day)
    inside = [v for k, v in got.items() if k <= d + timedelta(days=11)]
    assert sum(inside, D(0)) == D(300_000) + D(80_000)
    assert d + timedelta(days=3) not in got  # no window covers 15/11: missing, never 0


async def test_a6_stored_product_ads_gmv_counts_each_day_once(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    sid = seeded.shop_id
    d = CUR_START + timedelta(days=1)
    for start, end in ((d, d), (d, d + timedelta(days=2))):
        session.add(
            period_row(sid, "ads_campaign_period", start, end, item_id="1003", order_type="placed",
                       stream="ads", segment="cx", gmv=D(60_000),
                       extra={"ads_expense": 9_000, "direct_sales": 50_000})
        )  # fmt: skip
    await session.flush()
    await materialize.backfill_shop(session, sid)
    p = ShopeeProductMetricsDaily
    got = (
        await session.execute(
            select(func.sum(p.ads_gmv)).where(
                p.shop_id == sid,
                p.item_id == "1003",
                p.day >= d,
                p.day <= d + timedelta(days=2),
            )
        )
    ).scalar_one()
    # the fixture's own group-campaign window (whole CUR week) adds its share; the cx windows
    # add 50 000 once, not 50 000 + 50 000
    fixture = (
        day_facts.ads_gmv_by_item(
            [day_facts.AdReportRow("cgroup1", "1003", CUR_START, CUR_END, D(60_000))], d
        )["1003"]
        * 3
    )
    assert D(got) == D(50_000) + fixture


# -- A7 reconcile check ------------------------------------------------------------------------


async def test_a7_reconcile_reports_days_where_a_report_sees_more_affiliate_orders(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    found = await affiliate_check.reconcile(session, seeded.shop_id, CUR_START, CUR_END)
    # order lines: one affiliate order (day 4); the traffic report says 1 TTLK đơn every day
    by_day = {f.day: f for f in found.traffic_days}
    assert CUR_START + timedelta(days=3) not in by_day  # 1 >= 1
    assert by_day[CUR_START].lines == 0 and by_day[CUR_START].report == 1
    assert len(found.traffic_days) == 6
    # the partner report (whole week, 2 đơn) vs the lines' 1 over the same days
    assert [(p.start, p.end, p.lines, p.report) for p in found.partner_periods] == [
        (CUR_START, CUR_END, 1, 2)
    ]
    assert not found.ok


def test_a7_reconcile_is_ok_when_the_lines_see_at_least_what_each_report_sees():
    res = affiliate_check.compare(
        lines={date(2026, 11, 1): 3, date(2026, 11, 2): 1},
        traffic={date(2026, 11, 1): 2, date(2026, 11, 2): 1},
        partner=[(date(2026, 11, 1), date(2026, 11, 2), 4)],
    )
    assert res.ok and res.traffic_days == [] and res.partner_periods == []


def test_a9_ads_and_organic_never_explain_the_same_line_twice(monkeypatch):
    monkeypatch.setattr(day_facts, "counts_in_sales", lambda ln: True)
    pairs = [_pair("o1", 300, promo=30), _pair("o2", 300)]
    inp = day_facts.ChannelInput("9", D(600), 2, pairs, ads_gmv=D(300), ads_spend=D(40))
    rows = day_facts.channel_rows(inp, shop_id=None, day=date(2026, 11, 12), version="v")
    by = {(r["channel"], r["discounted"]): r for r in rows}
    for ch in ("ads", "organic"):
        assert by[(ch, "with")]["gmv"] == by[(ch, "without")]["gmv"] == D(150)
    assert not [r for r in rows if r["discounted"] == "unknown"]
    assert sum(r["orders"] for r in rows) == 2
    assert sum((r["net_revenue"] or D(0) for r in rows), D(0)) == D(570)


def test_f4_a_report_total_segment_is_never_added_to_its_parts():
    from juli_backend.services.metrics.components import (
        InvalidSegmentSum,
        check_segments,
        one_segment_basis,
    )

    rows = [("all", 5), ("aff_live", 2), ("aff_video", 3)]
    assert one_segment_basis(rows, lambda r: r[0]) == [("all", 5)]
    assert one_segment_basis(rows[1:], lambda r: r[0]) == rows[1:]  # no total: the parts
    with pytest.raises(InvalidSegmentSum) as excinfo:
        check_segments(["all", "aff_live", "aff_video"])
    assert "aff_live" in str(excinfo.value)


async def test_a7_reconcile_reads_the_traffic_total_or_its_parts_never_both(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    sid = seeded.shop_id
    day = CUR_START + timedelta(days=3)  # the fixture's one affiliate order line (1 đơn)
    session.add_all(
        [
            _daily(sid, day, "affiliate", "aff_live", orders=1, gmv=20_000),
            _daily(sid, day, "affiliate", "aff_video", orders=0, gmv=30_000),
        ]
    )  # beside the fixture's "all" row of 1 đơn: all = live + video
    await session.flush()
    found = await affiliate_check.reconcile(session, sid, CUR_START, CUR_END)
    assert day not in {f.day for f in found.traffic_days}  # 1 line đơn >= 1, not >= 2


# -- contract §6 (QUERY gaps) ---------------------------------------------------------------


async def test_shop_channel_cells_add_up_to_the_shop_day_with_its_own_orders(session):
    from juli_backend.models.shopee_metrics import ShopChannelMetricsDaily

    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    s, c = ShopeeShopMetricsDaily, ShopChannelMetricsDaily
    days = (await session.execute(select(s).where(s.shop_id == sid))).scalars().all()
    for row in days:
        cells = (
            (await session.execute(select(c).where(c.shop_id == sid, c.day == row.day)))
            .scalars()
            .all()
        )
        assert sum((x.gmv for x in cells), D(0)) == row.gmv
        assert sum(x.orders for x in cells) == row.orders  # the shop's đơn, not Σ products
        for col in ("net_revenue", "cogs_known_gmv", "affiliate_commission"):
            assert sum((getattr(x, col) or D(0) for x in cells), D(0)) == (
                getattr(row, col) or D(0)
            ), col
    aff = (
        (await session.execute(select(c).where(c.shop_id == sid, c.channel == "affiliate")))
        .scalars()
        .all()
    )
    assert sum(x.orders for x in aff) == 1  # the fixture's one affiliate order


def test_a2_ads_spend_known_is_the_covered_gmv_share_of_the_spend():
    assert day_facts.ads_spend_known(D(100), D(60), D(200)) == D("30.00")
    assert day_facts.ads_spend_known(D(100), D(300), D(200)) == D("100.00")  # capped at 1
    assert day_facts.ads_spend_known(D(100), None, D(0)) == D("100.00")  # no sale: all of it
    assert day_facts.ads_spend_known(None, D(1), D(2)) is None


async def test_a2_known_costs_and_the_ads_funnel_are_stored_on_both_grains(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    s, p = ShopeeShopMetricsDaily, ShopeeProductMetricsDaily
    shop = (
        await session.execute(select(s).where(s.shop_id == sid, s.day == CUR_START))
    ).scalar_one()
    assert shop.affiliate_commission_known == shop.affiliate_commission  # A1: one basis
    assert shop.ads_spend_known == day_facts.ads_spend_known(
        shop.ads_spend, shop.cogs_known_gmv, shop.gmv
    )
    assert shop.ads_views == 2000 and shop.ads_clicks == 40  # the "trong đó Quảng cáo" overlay
    prod = (
        await session.execute(
            select(p).where(p.shop_id == sid, p.day == CUR_START, p.item_id == "1001")
        )
    ).scalar_one()
    # the fixture's group campaign: 1001's week window, de-overlapped to a day (1/7 each)
    assert prod.ads_views == round(1000 / 7) and prod.ads_clicks == round(30 / 7)
    assert prod.ads_gmv_direct == (D(240_000) / 7).quantize(D("0.01"))
    assert prod.ads_gmv_confirmed is None  # Shopee posts none per product: missing, not 0


async def test_a8_a_product_report_row_of_zeros_is_stored_as_zeros(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    sid = seeded.shop_id
    day = CUR_START
    session.add_all(
        [
            _daily(sid, day, "total", "all", orders=2, gmv=180_000, dataset="item_performance",
                   item_id="1001"),
            _daily(sid, day, "total", "all", orders=0, gmv=0, dataset="item_performance",
                   item_id="1003"),
        ]
    )  # fmt: skip
    await session.flush()
    await materialize.backfill_shop(session, sid)
    p, c = ShopeeProductMetricsDaily, ProductChannelMetricsDaily
    row = (
        await session.execute(select(p).where(p.shop_id == sid, p.day == day, p.item_id == "1003"))
    ).scalar_one()
    assert row.gmv == 0 and row.orders == 0  # 0đ, not "—"
    cells = (
        (
            await session.execute(
                select(c).where(c.shop_id == sid, c.day == day, c.item_id == "1003")
            )
        )
        .scalars()
        .all()
    )
    # the day was reported: cells exist (here the ads cell carries the day's ad spend), all 0đ
    assert cells and sum((x.gmv for x in cells), D(0)) == 0 and sum(x.orders for x in cells) == 0
    assert sum((x.ads_spend or D(0) for x in cells), D(0)) == (row.ads_spend or D(0))


def test_a8_a_reported_zero_day_with_no_spend_keeps_one_zero_cell():
    inp = day_facts.ChannelInput("9", D(0), 0, [], ads_gmv=None, ads_spend=None)
    rows = day_facts.channel_rows(inp, shop_id=None, day=date(2026, 11, 12), version="v")
    assert [(r["channel"], r["discounted"], r["gmv"]) for r in rows] == [
        ("organic", "without", D(0))
    ]


def test_a2_profit_deducts_the_known_ads_and_aff_cost_when_the_rows_carry_it():
    base = {k: D(0) for k in ("net_revenue_known", "cogs", "packaging", "fees", "shipping_net")}
    base |= {"net_revenue_known": D(1000), "other_marketing": D(0)}
    plain = base | {"ads_spend": D(200), "affiliate_commission": D(50)}
    assert evaluate("profit", plain).value == D(750)  # no known part: the plain cost (a ladder)
    stored = plain | {"ads_spend_known": D(120), "affiliate_commission_known": D(50)}
    assert evaluate("profit", stored).value == D(830)  # A2: only the covered orders' ads
    missing = plain | {"ads_spend_known": None}
    assert evaluate("profit", missing).value is None  # an explicit None stays missing
    assert "daily_budget" in COMPONENTS and not can_sum("daily_budget", ["item"])
