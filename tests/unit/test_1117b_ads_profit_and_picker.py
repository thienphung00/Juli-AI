"""batch-1117b R11 / R12 / C4: one calculation. Synthetic data only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from juli_backend.services.shopee_analytics.catalog import UNMATCHED_LABEL, Catalog
from juli_backend.services.shopee_analytics.channel_split import partition_channels
from juli_backend.services.shopee_analytics.loaders import load_ad_days
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.ads_days import (
    SOURCE_CONNECTOR,
    SOURCE_DAILY_REPORT,
    DayAds,
    resolve_ad_days,
)
from juli_backend.services.shopee_profit.shop_profit import (
    NO_ORDER_DAYS_ADS_LABEL,
    AdCampaign,
    known_cost_profit,
    shop_profit,
)
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import _daily
from tests.unit.test_p100b_one_shop_profit import _line, _pb

# ---- R11 --------------------------------------------------------------------------------


def _fig(order_data_days=None):
    pairs = [(_line("o1", "A", 100_000, day=4), _pb(100_000, 40_000))]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", D(30_000))], product_ad_spend={})
    daily = {date(2026, 11, d): D(10_000) for d in (4, 5, 6)}  # 5 and 6: no orders
    return known_cost_profit(sp, pairs, D(100_000), daily, order_data_days)


def test_r11_ads_of_days_with_no_orders_are_charged_to_their_own_line():
    fig = _fig()
    b = fig.json()["bridge"]
    assert fig.ads_total == D(30_000)
    assert fig.ads_no_order_days == D(20_000)
    assert fig.ads_charged == D(30_000)  # = the spend of the days counted = all of it
    assert fig.profit == D(40_000) - D(30_000) == D(10_000)
    assert b["ads_no_order_days"] == 20_000
    assert b["ads_no_order_days_label"] == NO_ORDER_DAYS_ADS_LABEL
    assert (
        b["product_profit"] - b["ads_unattributed"] - b["other_marketing"] - b["ads_no_order_days"]
        == b["profit"]
    )
    # the no-order days are part of what was charged, never "on days with orders" only
    assert b["ads_label"].startswith("QC đã tính theo ngày: ")
    assert "ngày có đơn có chi phí" not in b["ads_label"]
    assert b["ads_label"].endswith("; gồm 20.000đ quảng cáo ngày không có đơn")


def test_r11_a_day_without_order_data_is_not_charged_missing_is_not_zero():
    covered = {date(2026, 11, 4), date(2026, 11, 5)}  # day 6: its order data never arrived
    fig = _fig(covered)
    assert fig.ads_no_order_days == D(10_000)
    assert fig.ads_charged == D(20_000) and fig.ads_total == D(30_000)
    assert fig.profit == D(40_000) - D(20_000)


def test_r11_unknown_cost_orders_day_stays_uncharged():
    pairs = [
        (_line("o1", "A", 100_000, day=4), _pb(100_000, None)),
        (_line("o2", "A", 100_000, day=5), _pb(100_000, 40_000)),
    ]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", D(30_000))], product_ad_spend={})
    daily = {date(2026, 11, d): D(10_000) for d in (4, 5, 6)}
    fig = known_cost_profit(sp, pairs, D(200_000), daily)
    assert fig.ads_charged == D(10_000) + D(10_000)  # day 5 + the zero-order day 6
    assert fig.ads_no_order_days == D(10_000)


# ---- R12 --------------------------------------------------------------------------------


def _day(spend: int, source: str) -> DayAds:
    return DayAds(D(spend), D(0), D(0), source, {})


def test_r12_the_report_wins_a_closed_day_and_the_connector_fills_the_rest():
    d1, d2, d3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
    connector = {d1: _day(100, SOURCE_CONNECTOR), d3: _day(300, SOURCE_CONNECTOR)}
    report = {d1: _day(150, SOURCE_DAILY_REPORT), d2: _day(200, SOURCE_DAILY_REPORT)}
    out = resolve_ad_days(connector, report, [], d1, d3, connector_until=d3)
    assert {d: (f.spend, f.source) for d, f in out.items()} == {
        d1: (D(150), SOURCE_DAILY_REPORT),
        d2: (D(200), SOURCE_DAILY_REPORT),
        d3: (D(300), SOURCE_CONNECTOR),
    }
    assert sum(f.spend for f in out.values()) == D(650)  # one spend per day


def test_r12_a_day_after_the_newest_connector_read_without_report_is_still_missing():
    d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
    out = resolve_ad_days({d1: _day(100, SOURCE_CONNECTOR)}, {}, [], d1, d2, connector_until=d1)
    assert d2 not in out


# ---- C4 ---------------------------------------------------------------------------------


def test_c4_unmatched_lines_are_never_called_unknown():
    cat = Catalog()
    assert cat.name("sku:unknown") == UNMATCHED_LABEL
    assert "unknown" not in cat.name("sku:unknown")
    assert Catalog.is_unmatched("sku:unknown") and not Catalog.is_unmatched("123")


def test_c4_channels_partition_the_product_gmv():
    ads, aff, org = partition_channels(D(32_090_000), D(10_570_000), D(12_120_000))
    assert (ads, aff, org) == (D(10_570_000), D(12_120_000), D(9_400_000))
    assert ads + aff + org == D(32_090_000)


def test_c4_an_overlay_above_the_gmv_is_capped_and_the_sum_stays_100_percent():
    ads, aff, org = partition_channels(D(100), D(80), D(50))
    assert (ads, aff, org) == (D(80), D(20), D(0))
    assert ads + aff + org == D(100)
    assert partition_channels(D(100), D(150), D(0)) == (D(100), D(0), D(0))
    assert partition_channels(D(100), None, D(10)) == (None, D(10), None)


def test_c4_builder_step1_case_ads_report_above_confirmed_gmv():
    """Tự tạo step 1 (channel-split/products): GMV 1,460,018 with an ads-report GMV of 3,907,290."""
    ads, aff, org = partition_channels(D(1_460_018), D(3_907_290), D(100_000))
    assert (ads, aff, org) == (D(1_460_018), D(0), D(0))
    assert ads + aff + org == D(1_460_018)


async def test_r12_a_report_day_without_any_cost_leaves_the_day_to_the_connector(session):
    """An export that holds only the "all" count row for a day (no ``ads_expense``) has no figure
    for it: the Connector's spend answers, never a 0 from the report (2026-11-18)."""

    shop = await make_shop(session, await make_user(session), platform="shopee")
    priced, empty = date(2026, 11, 2), date(2026, 11, 3)
    session.add_all(
        [
            _daily(
                shop.id,
                priced,
                "ads",
                "ads_shop",
                impressions=40,
                order_type="placed",
                extra={"ads_expense": 4000},
            ),
            _daily(
                shop.id, priced, "ads", "all", order_type="placed", extra={"l2_breakdown_count": 1}
            ),
            _daily(
                shop.id, empty, "ads", "all", order_type="placed", extra={"l2_breakdown_count": 0}
            ),
            *[
                _daily(
                    shop.id,
                    d,
                    "ads",
                    seg,
                    impressions=10,
                    clicks=1,
                    dataset="ads_campaign_daily",
                    order_type="placed",
                    extra={"cost": 9000} if seg != "all" else {},
                )
                for d in (priced, empty)
                for seg in ("all", "c1")
            ],
        ]
    )
    await session.commit()

    days = await load_ad_days(session, shop.id, Window(priced, empty))

    assert (days[priced].source, days[priced].spend) == (SOURCE_DAILY_REPORT, D(4000))
    assert (days[empty].source, days[empty].spend) == (SOURCE_CONNECTOR, D(9000))
