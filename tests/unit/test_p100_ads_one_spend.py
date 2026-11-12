"""P100 A.5 / B.5: one ad spend per day, charged to profit by day and known-cost share.

Pure functions only; synthetic figures. The per-day precedence is Connector day, then the daily
report, then the CSV period report spread over its days, then nothing (a day with no figure is
absent, never 0). The Tổng quan bridge adds up exactly and says what was charged.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_profit.ads_days import (
    SOURCE_CONNECTOR,
    SOURCE_DAILY_REPORT,
    SOURCE_PERIOD_SPREAD,
    DayAds,
    resolve_ad_days,
    source_counts,
)
from juli_backend.services.shopee_profit.ads_sources import AdWindow, resolve_ad_spend
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    known_cost_profit,
    shop_profit,
)
from tests.unit.test_p100b_one_shop_profit import _line, _pb

D = Decimal


def _day(spend: int, source: str, gmv: int = 0) -> DayAds:
    return DayAds(D(spend), D(gmv), D(0), source)


def test_each_day_takes_the_first_source_that_has_it_and_is_counted_once():
    connector = {date(2026, 11, 1): _day(100, SOURCE_CONNECTOR, 400)}
    report = {
        date(2026, 11, 1): _day(999, SOURCE_DAILY_REPORT),
        date(2026, 11, 2): _day(50, SOURCE_DAILY_REPORT, 100),
    }
    period = [AdWindow("c", date(2026, 11, 1), date(2026, 11, 4), D(400), gmv=D(800))]
    days = resolve_ad_days(connector, report, period, date(2026, 11, 1), date(2026, 11, 5))
    assert (
        days[date(2026, 11, 1)].spend == D(100)
        and days[date(2026, 11, 1)].source == SOURCE_CONNECTOR
    )
    assert (
        days[date(2026, 11, 2)].spend == D(50)
        and days[date(2026, 11, 2)].source == SOURCE_DAILY_REPORT
    )
    spread = days[date(2026, 11, 3)]
    assert spread.source == SOURCE_PERIOD_SPREAD and spread.spend == D(100) and spread.gmv == D(200)
    assert date(2026, 11, 5) not in days  # no source: no figure, never 0
    assert source_counts(days) == {
        SOURCE_CONNECTOR: 1,
        SOURCE_DAILY_REPORT: 1,
        SOURCE_PERIOD_SPREAD: 2,
    }


def test_the_period_spread_is_the_resolvers_pro_rata_share():
    windows = [
        AdWindow("c", date(2026, 10, 1), date(2026, 10, 30), D(3000), item_id="1"),
        AdWindow("c", date(2026, 10, 1), date(2026, 10, 30), D(600), item_id="2"),
    ]
    start, end = date(2026, 10, 10), date(2026, 10, 19)
    days = resolve_ad_days({}, {}, windows, start, end)
    assert sum(d.spend for d in days.values()) == resolve_ad_spend([], windows, start, end).total


def test_a_newer_period_report_answers_the_days_it_covers():
    windows = [
        AdWindow("c", date(2026, 10, 1), date(2026, 10, 10), D(1000)),
        AdWindow("c", date(2026, 10, 6), date(2026, 10, 15), D(2000)),
    ]
    days = resolve_ad_days({}, {}, windows, date(2026, 10, 6), date(2026, 10, 7))
    assert [d.spend for d in days.values()] == [D(200), D(200)]


def test_a_connector_day_with_no_spend_is_zero_not_missing():
    days = resolve_ad_days(
        {date(2026, 11, 1): _day(0, SOURCE_CONNECTOR)}, {}, [], date(2026, 11, 1), date(2026, 11, 2)
    )
    assert days[date(2026, 11, 1)].spend == D(0) and date(2026, 11, 2) not in days


def test_week_with_orders_on_two_days_charges_only_those_days_and_the_bridge_adds_up():
    """The Demo case: orders on 2 of 7 days, one known-cost; the whole week's ads were taken."""
    pairs = [
        (_line("o1", "A", 100_000, day=4), _pb(100_000, 40_000)),
        (_line("o2", "A", 300_000, day=4), _pb(300_000, None)),
        (_line("o3", "A", 100_000, day=5), _pb(100_000, 30_000)),
    ]
    sp = shop_profit(
        pairs, campaigns=[AdCampaign("c", D(70_000))], product_ad_spend={"A": D(21_000)}
    )
    daily = {date(2026, 11, d): D(10_000) for d in range(3, 10)}
    fig = known_cost_profit(sp, pairs, D(500_000), daily)
    # day 4: 10k x 100/400; day 5: 10k x 100/100; the five other days have no order data
    assert fig.ads_charged == D(2_500) + D(10_000)
    assert fig.ads_total == D(70_000)
    b = fig.json()["bridge"]
    assert b["product_profit"] - b["ads_unattributed"] - b["other_marketing"] == b["profit"]
    assert fig.profit == b["profit"] == D(70_000) - D(12_500)
    assert "12.500đ / tổng chi QC 70.000đ" in b["ads_label"]


def test_bridge_adds_up_in_whole_dong_when_the_parts_are_fractions():
    pairs = [(_line("o1", "A", 100_000, day=4), _pb(100_000, 40_000))]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", D(1_000))], product_ad_spend={"A": D(333)})
    fig = known_cost_profit(
        sp, pairs, D(100_000), {date(2026, 11, 4): D(1_000), date(2026, 11, 5): D(1_001)}
    )
    b = fig.json()["bridge"]
    assert isinstance(b["product_profit"], int) and isinstance(b["ads_unattributed"], int)
    assert b["product_profit"] - b["ads_unattributed"] - b["other_marketing"] == b["profit"]
