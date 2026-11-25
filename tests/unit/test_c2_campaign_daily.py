"""C2 / C3: a campaign's figures are its own Connector days -- never a report stretched to the
shop's daily spend -- and the ad types are classified, not guessed. Synthetic numbers only."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics.channel_split import ad_report_by_class
from juli_backend.services.shopee_analytics.compute import allocate_ads, campaign_of
from juli_backend.services.shopee_analytics.loaders import (
    AdsDaily,
    AdsReports,
    AdsRow,
    PeriodChoice,
    ad_type_class,
    is_shop_plus,
)
from juli_backend.services.shopee_analytics.product_ads import (
    CampaignDayRow,
    ProductAdRule,
    ProductAdsInput,
    ReportRow,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine_families.measure import CampaignDay, budget_state
from juli_backend.services.shopee_profit.shop_profit import shop_profit

D = Decimal
START = date(2026, 10, 1)
END = date(2026, 10, 10)
W = Window(START, END)
OLD = (START - timedelta(days=20), END)  # 30 days, 10 of them in the window


def _days(n: int = 10) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def _row(spend, gmv=0, orders=0, *, name="Nhóm", ad_type="product_mpd", state="ongoing", **kw):
    vals = {
        "spend": D(spend),
        "gmv": D(gmv),
        "direct_gmv": D(gmv) / 2,
        "orders": D(orders),
        "clicks": D(10),
        "impressions": D(100),
    }
    return CampaignDayRow(**{**vals, **kw}, name=name, ad_type=ad_type, state=state)


def _input(rows, covered=None, reports=()):
    return ProductAdsInput(
        campaign_days={k: r.spend for k, r in rows.items()},
        covered_days=frozenset(_days() if covered is None else covered),
        report_rows=list(reports),
        day_rows=dict(rows),
        title_keys={r.name: k for (k, _), r in rows.items() if r.name},
    )


def _report(key, item, spend, gmv, period=OLD, name="Nhóm"):
    return AdsRow(
        name, key, item, D(spend), D(gmv), D(gmv) / 2, D(3), D(30), D(300), True, period
    )  # fmt: skip


def _reports(*rows, period=OLD):
    none = PeriodChoice((), "none", 0)
    if not rows:
        return AdsReports([], [], none, none)
    return AdsReports(list(rows), [], PeriodChoice((period,), "overlap", 10), none)


def _daily(spend, gmv=0, days=10):
    return AdsDaily(D(spend), D(gmv), D(0), {}, days, 10)


def _total(alloc):
    return sum((c.spend for c in alloc.ad_campaigns()), D(0))


def test_a_campaign_with_no_sales_reads_gmv_0_and_roas_0():
    rows = {("z", d): _row(100) for d in _days()}
    alloc = allocate_ads(
        W, _daily(1000), _reports(_report("z", "", 3000, 9000), _report("z", "1", 3000, 9000)),
        None, _input(rows, reports=[ReportRow("z", "1", *OLD, D(3000))]),
    )  # fmt: skip
    (c,) = alloc.campaigns
    assert (c.spend, c.gmv, c.direct_gmv, c.orders) == (D(1000), D(0), D(0), D(0))
    assert c.roas == 0 and c.roas_direct == 0 and c.source == "daily"
    assert c.products == {"1": D(1000)}


def test_two_campaigns_equal_their_day_rows_whatever_the_shop_total_is():
    rows = {("a", d): _row(100, 500, 2, name="A") for d in _days()}
    rows |= {("b", d): _row(10, 70, 1, name="B") for d in _days(4)}
    alloc = allocate_ads(
        W, _daily(5000), _reports(_report("a", "1", 9000, 9000, name="A")), None, _input(rows)
    )
    by = {c.key: c for c in alloc.campaigns}
    assert (by["a"].spend, by["a"].gmv, by["a"].orders) == (D(1000), D(5000), D(20))
    assert (by["b"].spend, by["b"].gmv, by["b"].orders) == (D(40), D(280), D(4))
    assert (by["a"].clicks, by["a"].impressions) == (D(100), D(1000))
    assert alloc.total_spend == D(5000) and alloc.remainder == D(3960)
    assert alloc.basis == "connector_daily" and alloc.scale == 1


def test_shop_plus_spend_is_the_remainder_not_a_campaign():
    rows = {("a", d): _row(100, 500, name="A") for d in _days()}
    rows |= {("s", d): _row(30, 10, name="S", ad_type="shop_manual") for d in _days()}
    alloc = allocate_ads(W, _daily(1300), _reports(), None, _input(rows))
    assert [c.key for c in alloc.campaigns] == ["a"]
    assert alloc.remainder == D(300) and alloc.total_spend == _total(alloc) == D(1300)


def test_uncovered_days_take_only_their_own_share_of_the_report():
    covered = _days(6)  # days 7..10 not read
    rows = {("a", d): _row(100, 500, 2, name="A") for d in covered}
    alloc = allocate_ads(
        W, _daily(1000), _reports(_report("old", "1", 300, 900, name="A")), None,
        _input(rows, covered),
    )  # fmt: skip
    (c,) = alloc.campaigns  # the report joins the campaign by its title
    assert c.key == "a" and c.source == "mixed" and c.report_keys == frozenset({"old"})
    assert c.spend == D(600) + D(300) * 4 / 30
    assert c.gmv == D(3000) + D(900) * 4 / 30
    assert alloc.basis == "daily_and_report" and "ước tính" in alloc.label
    assert campaign_of(alloc.campaigns, "old") is c  # a saved card may still carry the report's key


def test_the_connectors_own_key_beats_a_title_joined_report_of_the_same_campaign():
    covered = _days(6)
    rows = {("a", d): _row(100, name="A") for d in covered}
    alloc = allocate_ads(
        W, _daily(1000),
        _reports(_report("a", "1", 300, 900, name="A"), _report("old", "1", 300, 900, name="A")),
        None, _input(rows, covered),
    )  # fmt: skip
    assert alloc.campaigns[0].spend == D(600) + D(40)  # not counted twice


def test_estimated_parts_above_the_daily_total_give_a_negative_remainder():
    covered = _days(6)
    rows = {("a", d): _row(100, name="A") for d in covered}
    alloc = allocate_ads(
        W, _daily(610), _reports(_report("a", "1", 300, 900, name="A")), None, _input(rows, covered)
    )
    assert alloc.remainder == D(-30) and _total(alloc) == alloc.total_spend == D(610)


def test_shop_profit_ads_total_is_the_daily_total():
    rows = {("a", d): _row(100, 500, name="A") for d in _days()}
    alloc = allocate_ads(W, _daily(1234), _reports(), None, _input(rows))
    sp = shop_profit([], campaigns=alloc.ad_campaigns(), product_ad_spend=alloc.product_spend)
    assert sp.total_ad_spend == D(1234)


def test_the_product_rule_39_is_untouched():
    rows = {("a", d): _row(100, 500, name="A") for d in _days()}
    inp = _input(rows, reports=[ReportRow("a", "1", *OLD, D(60)), ReportRow("a", "2", *OLD, D(40))])
    alloc = allocate_ads(W, _daily(1000), _reports(), None, inp)
    assert alloc.product_spend == ProductAdRule(inp).window_spend(START, END)
    assert alloc.campaigns[0].products == {"1": D(600), "2": D(400)}


@pytest.mark.parametrize("gap", ["gmv", "direct_gmv", "orders", "clicks", "impressions"])
def test_a_count_missing_on_a_covered_day_is_none_not_zero(gap):
    rows = {("a", d): _row(100, 500, 2, name="A") for d in _days()}
    rows[("a", START)] = replace(rows[("a", START)], **{gap: None})
    (c,) = allocate_ads(W, _daily(1000), _reports(), None, _input(rows)).campaigns
    assert getattr(c, gap) is None and c.spend == D(1000)
    others = {"gmv", "direct_gmv", "orders", "clicks", "impressions"} - {gap}
    assert all(getattr(c, o) is not None for o in others)


def test_zero_spend_campaigns_are_hidden_unless_they_run_on_the_newest_day():
    rows = {("a", d): _row(100, name="A") for d in _days()}
    rows |= {("ended", d): _row(0, name="E", state="ended") for d in _days()}
    rows |= {("idle", d): _row(0, name="I") for d in _days()}
    rows |= {("was", d): _row(0, name="W") for d in _days(3)}  # ran, but not on the newest day
    alloc = allocate_ads(W, _daily(1000), _reports(), None, _input(rows))
    by = {c.key: c for c in alloc.campaigns}
    assert set(by) == {"a", "idle"}
    assert by["idle"].roas is None and by["idle"].running is True


def test_a_report_only_campaign_of_a_fully_read_window_spent_nothing():
    rows = {("a", d): _row(100, name="A") for d in _days()}
    alloc = allocate_ads(
        W, _daily(1000), _reports(_report("gone", "1", 300, 900, name="G")), None, _input(rows)
    )
    assert [c.key for c in alloc.campaigns] == ["a"]


def test_a_report_only_shop_keeps_its_own_prorated_figures_without_stretching():
    alloc = allocate_ads(
        W, _daily(500), _reports(_report("g", "1", 300, 900)), None, _input({}, ())
    )
    (c,) = alloc.campaigns
    assert (round(c.spend), round(c.gmv), c.source) == (D(100), D(300), "report")
    assert alloc.basis == "report_prorated"
    assert round(alloc.remainder) == D(400) and alloc.total_spend == D(500)  # the shop total stays


def test_no_campaign_at_all_leaves_the_daily_total_in_the_remainder():
    alloc = allocate_ads(W, _daily(70, 300), _reports(), None, None)
    assert alloc.campaigns == [] and alloc.remainder == alloc.total_spend == D(70)
    assert _total(alloc) == D(70)


def test_budget_rate_and_its_days_come_from_the_same_day_rows():
    days = [CampaignDay(D(100), D(1000))] * 8
    state = budget_state(D(99_999), 30, D(1000), days)
    assert state is not None and state.rate == D(100) and state.running_days == 8


# ---------------------------------------------------------------------------------------- C3


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("product_mpd", "product"), ("product_manual", "product"), ("product_gms", "product"),
        ("ads_product", "product"), ("ads_roas_custom", "product"), ("ads_auto_bid", "product"),
        ("ads_gmvmax_shop", "product"), ("gmv_max", "product"), ("PRODUCT_MPD", "product"),
        ("ads_shop", "shop_plus"), ("shop_manual", "shop_plus"), ("SHOP_auto", "shop_plus"),
        ("live_manual", "livestream"), ("ads_live", "livestream"), ("livestream", "livestream"),
        ("other", "unknown"), ("connector", "unknown"), ("all", "unknown"), ("3", "unknown"),
        ("", "unknown"), (None, "unknown"),
    ],
)  # fmt: skip
def test_ad_types_are_classified_and_never_guessed(raw, kind):
    assert ad_type_class(raw) == kind
    assert is_shop_plus(raw) is (kind == "shop_plus")


def test_the_total_is_the_sum_of_the_types():
    types = {
        "product_mpd": {"gmv": D(900), "orders": D(9), "spend": D(100)},
        "shop_manual": {"gmv": D(50), "orders": D(1), "spend": D(30)},
        "live_manual": {"gmv": D(20), "orders": D(1), "spend": D(7)},
        "mystery": {"gmv": D(5), "orders": D(1), "spend": D(2)},
    }
    by = ad_report_by_class(types)
    assert {k: v["spend"] for k, v in by.items()} == {
        "product": D(100), "shop_plus": D(30), "livestream": D(7), "unknown": D(2),
    }  # fmt: skip
    assert sum(v["spend"] for v in by.values()) == sum(t["spend"] for t in types.values())
    assert sum(v["gmv"] for v in by.values()) == sum(t["gmv"] for t in types.values())
