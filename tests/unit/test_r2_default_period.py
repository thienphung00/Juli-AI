"""Owner #85 / #94: a screen opened without a chosen period opens on the newest 30 days whose
known-cost share passes the profit gate (70-100 %), stepping the end back one day at a time,
at most 30 days, and names the dates. A period the seller chose never moves. The search reads
only the stored day rows. Synthetic data only."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics import channel_split, materialize, metric_view, queries
from juli_backend.services.shopee_analytics.default_period import (
    AUTO,
    MAX_STEP_BACK_DAYS,
    pick_window,
)
from juli_backend.services.shopee_profit.shop_profit import known_cost_net_gmv
from tests.support.shopee_analytics import CUR_END, CUR_START, PREV_END, seed_shopee_shop

D = Decimal
ANCHOR = date(2026, 10, 31)


def _days(n: int, known_of=lambda d: D(100)):
    days = [ANCHOR - timedelta(days=i) for i in range(n)]
    return {d: (D(100), known_of(d)) for d in days}


def test_the_newest_passing_window_wins():
    assert pick_window(ANCHOR, _days(90)).window.end == ANCHOR
    # the last 5 days are unsettled (no known cost): 25/30 = 83 % passes at once
    late = _days(90, lambda d: D(0) if d > ANCHOR - timedelta(days=5) else D(100))
    assert pick_window(ANCHOR, late).moved_days == 0
    # the last 12 days unknown: 18/30 fails; 21/30 = 70.0 % passes three days back
    late = _days(90, lambda d: D(0) if d > ANCHOR - timedelta(days=12) else D(100))
    pick = pick_window(ANCHOR, late)
    assert pick.passed and pick.moved_days == 3
    assert pick.window.days == 30 and pick.window.end == ANCHOR - timedelta(days=3)


def test_bounded_and_falls_back_to_the_newest():
    never = _days(90, lambda d: D(10))
    pick = pick_window(ANCHOR, never)
    assert not pick.passed and pick.moved_days == 0 and pick.window.end == ANCHOR
    # a window passes only 50 days back: beyond the bound
    far = _days(120, lambda d: D(100) if d <= ANCHOR - timedelta(days=50) else D(0))
    assert MAX_STEP_BACK_DAYS == 30
    assert not pick_window(ANCHOR, far).passed
    assert pick_window(ANCHOR, far, max_back=60).passed


def test_a_row_without_the_key_is_unknown_never_zero():
    days = _days(90)
    days[ANCHOR] = (D(100), None)  # built before the known-cost day field (ROWS_VERSION 6)
    pick = pick_window(ANCHOR, days)
    assert pick.moved_days == 1  # every window holding that day is unknown
    days.pop(ANCHOR)
    days[ANCHOR] = (None, None)  # no order data that day: in no sum
    assert pick_window(ANCHOR, days).moved_days == 0


async def _rows(session, shop_id):
    return {
        r.day: r
        for r in (
            await session.execute(
                select(ShopeeShopMetricsDaily).where(ShopeeShopMetricsDaily.shop_id == shop_id)
            )
        ).scalars()
    }


async def test_stored_known_cost_gmv_is_the_gate_numerator(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    ctx, now, _ = await queries._views(
        session, seeded.shop_id, period="7d", month=None, start=None, end=None, as_of=CUR_END
    )
    rows = await _rows(session, seeded.shop_id)
    in_window = [r for d, r in rows.items() if CUR_START <= d <= CUR_END and r.orders is not None]
    known = sum((D(r.detail["known_cost_gmv"]) for r in in_window), D(0))
    gmv = sum((r.gmv for r in in_window), D(0))
    assert known == known_cost_net_gmv(now.pairs).quantize(D("0.01"))
    ov = await queries.overview(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert float((known * 100 / gmv).quantize(D("0.1"))) == ov["shop_profit"]["gmv_share_pct"]
    assert all(
        r.detail[materialize.ROWS_VERSION_KEY] == materialize.ROWS_VERSION for r in rows.values()
    )


async def test_screens_open_on_the_default_window_and_a_chosen_period_stays(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    rows = await _rows(session, seeded.shop_id)
    # the newest week is unsettled: no known cost from 1/10 on; the week before is all known
    for d, r in rows.items():
        r.detail = {**r.detail, "known_cost_gmv": str(r.gmv if d <= PREV_END else 0)}
    await session.flush()
    gmv = {d: r.gmv for d, r in rows.items() if r.orders is not None}
    assert len(set(gmv.values())) == 1  # equal days: 7 known of 7 + k days passes for k <= 3
    expect_to = date(2026, 10, 3)

    kw = {"period": AUTO, "as_of": CUR_END}
    ov = await queries.overview(session, seeded.shop_id, **kw)
    dp = ov["default_period"]
    assert dp["to"] == expect_to.isoformat() and dp["days"] == 30 and dp["moved_days"] == 4
    assert dp["max_back_days"] == 30
    # one period per screen: the whole view is the chosen window
    assert ov["period"]["window"] == {"from": dp["from"], "to": dp["to"], "days": 30}
    in_window = sum(
        (g for d, g in gmv.items() if date.fromisoformat(dp["from"]) <= d <= expect_to), D(0)
    )
    assert ov["shop_metrics"]["gmv"] == ov["kpi_strip"]["gmv"]["value"] == float(in_window)

    mx = await queries.matrix(session, seeded.shop_id, **kw)
    cs = await channel_split.channel_split(session, seeded.shop_id, **kw)
    mv = await metric_view.metric_view(session, seeded.shop_id, **kw)
    pp = await queries.product_page(session, seeded.shop_id, "1001", **kw)
    for body in (mx, cs, mv, pp):
        assert body["default_period"]["to"] == expect_to.isoformat()
    assert cs["to"] == expect_to.isoformat() and cs["days"] == 30

    # a chosen period is never moved and names no default
    chosen = await queries.overview(session, seeded.shop_id, period="30d", as_of=CUR_END)
    assert "default_period" not in chosen
    assert chosen["period"]["window"]["to"] == CUR_END.isoformat()
    chosen_cs = await channel_split.channel_split(
        session, seeded.shop_id, period="7d", as_of=CUR_END
    )
    assert "default_period" not in chosen_cs and chosen_cs["to"] == CUR_END.isoformat()
