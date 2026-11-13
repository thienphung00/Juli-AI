"""P100 B.15: edits of a running Dịch vụ hiển thị campaign in Tự tạo phương án -- synthetic
campaigns, invented figures. CPA vs break-even CPA is the verdict, Δ total profit comes from the
incremental orders only, ad orders are adjusted by the shop's cancel rate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics.loaders import cancel_rate_of
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import (
    AdsEvaluation,
    AdShare,
    Band,
    FunnelBase,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import ads_edit, integrate, measure
from juli_backend.services.shopee_builder.engine_families.ads_edit import ads_edit_option
from juli_backend.services.shopee_builder.engine_families.facts import AdsEditFacts, ProductAdRow
from juli_backend.services.shopee_builder.engine_families.measure import (
    AdCampaignHist,
    AdDay,
    CampaignDay,
)

BE_CPA = D(50_000)  # profit per order before ads of the campaign's products


def camp(key="c1", spend=3_000_000, budget=150_000, roas=None, orders=100, **kw):
    """30 days: 100.000đ/day, 1.500.000 impressions, 30.000 clicks, 100 direct orders."""
    return AdCampaignHist(
        key,
        frozenset({"i1", "i2"}),
        "product_search",
        D(spend),
        D(1_500_000),
        D(30_000),
        D(orders),
        D(15_000_000),
        days=30,
        daily_budget=None if budget is None else D(budget),
        roas_target=roas,
        gmv=D(18_000_000),
        **kw,
    )


def on_off(organic_on=8, ad_on=4, off=10):
    """10 days with ads (8 organic + 4 ad orders) and 10 without (10): +2 of 4 -> share 50 %."""
    days = [AdDay(True, D(organic_on), D(ad_on)) for _ in range(10)]
    return tuple(days + [AdDay(False, D(off), D(0)) for _ in range(10)])


def row(campaign, item, spend, orders, gmv, days=30, imp=500_000, clicks=10_000):
    return ProductAdRow(
        campaign, item, D(spend), D(imp), D(clicks), D(orders), D(gmv), D(gmv), days
    )


ROWS = (
    row("c1", "i1", 600_000, 30, 3_000_000),
    row("c1", "i2", 400_000, 30, 3_000_000),
    row("c2", "i3", 300_000, 15, 1_500_000),
)


def facts(c=None, *, cancel=D("0.1"), days=None, budget=D(150_000), **kw):
    c = camp() if c is None else c
    return AdsEditFacts(
        campaign=c,
        name="Chiến dịch A",
        daily_budget=budget,
        product_rows=ROWS,
        days=on_off() if days is None else days,
        campaigns=kw.pop("campaigns", (c,)),
        profit_per_order_before_ads=kw.pop("ppo", BE_CPA),
        cancel_rate=cancel,
        **kw,
    )


def spec(**kw):
    kw.setdefault("campaign_key", "c1")
    return sp.AdsSpec(kind="ads", **kw)


def base():
    """The campaign's products over 30 days (profit after ads)."""
    return FunnelBase(
        "shop-1",
        "products",
        ("i1", "i2"),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            SourceFunnel(
                "the_san_pham_khac",
                D(2_000_000),
                D(60_000),
                D(600),
                D(90_000_000),
                D(12_000_000),
                AdShare(None, None, None, D(18_000_000), D(3_000_000)),
                D(600),
            ),
            SourceFunnel("chenh_lech_nguon", None, None, D(0), D(0), D(0), None, D(0)),
        ),
        D("0.3"),
    )


def evaluate(s, f):
    o = ads_edit_option(s, f)
    return o, run(base(), o, seed=1)


# -- today: CPA, break-even CPA, verdict, profit after ads --------------------------------------


def test_today_cpa_on_confirmed_orders_verdict_and_profit_after_ads():
    """100.000đ/day; 100 placed direct orders × (1 − 10 % huỷ) = 3 đơn/day -> CPA 33.333đ <
    break-even 50.000đ -> có lãi; profit after ads = 90 × (50.000 − 33.333) = 1.500.000đ."""
    o, r = evaluate(spec(lever="budget", daily_budget=150_000), facts())
    a = o.ads
    assert a is not None and a.spend_now == D(3_000_000) and a.orders_now == D(90)
    assert a.cpa_now == pytest.approx(D(3_000_000) / 90)
    j = r.json()["ads"]
    assert j["break_even_cpa"] == 50_000 and j["verdict"]["now"] == "co_lai"
    assert j["verdict_text"]["now"] == "có lãi"
    assert j["profit_after_ads"]["now"] == 1_500_000
    assert j["roas_shopee"]["now"] == pytest.approx(6.0)  # 18.000.000 ÷ 3.000.000, reference
    assert j["cancel_rate_pct"] == pytest.approx(10.0)


def test_the_verdict_is_lo_when_cpa_is_above_break_even():
    o, r = evaluate(spec(lever="budget", daily_budget=150_000), facts(ppo=D(20_000)))
    j = r.json()["ads"]
    assert j["verdict"]["now"] == "lo" and j["verdict_text"]["after"] == "lỗ"
    assert j["profit_after_ads"]["now"] == 90 * 20_000 - 3_000_000  # −1.200.000đ


def test_without_a_cancel_rate_the_placed_orders_are_used_and_said_so():
    o = ads_edit_option(spec(lever="budget", daily_budget=150_000), facts(cancel=None))
    assert o.ads is not None and o.ads.orders_now == pytest.approx(D(100))
    assert ads_edit.NOTE_NO_CANCEL_RATE in (o.note or "")


# -- budget: capped vs not capped ----------------------------------------------------------------


def test_budget_cut_below_what_an_uncapped_campaign_spends():
    """Not capped (100.000 of 150.000/day): a budget of 80.000 is the spend; 72 đơn after at the
    same CPA; Δ profit from the incremental half only: −9 × 50.000 + 600.000 = +150.000đ."""
    o, r = evaluate(spec(lever="budget", daily_budget=80_000), facts())
    a = o.ads
    assert a.spend_basis == "not_capped" and "thấp hơn mức chiến dịch thực chi" in a.spend_text
    assert a.spend_after == D(2_400_000) and a.orders_after == pytest.approx(D(72))
    assert o.fixed_cost == pytest.approx(D(-600_000))
    j = r.json()
    assert j["ads"]["incremental"]["orders_all"] == pytest.approx(-18)
    assert j["ads"]["incremental"]["orders_extra"] == pytest.approx(-9)
    assert j["ads"]["incremental"]["share"] == pytest.approx(50.0)
    assert j["delta"]["orders"]["value"] == pytest.approx(-9)  # not −18: incremental only
    assert j["delta"]["profit"]["value"] == pytest.approx(150_000, abs=1)
    assert "Chi phí giảm 600.000đ" in j["cost"]["text"]
    assert any("chi phí giảm" in p["text"] for p in j["build_up"])


def test_budget_raise_on_an_uncapped_campaign_does_not_raise_spend():
    o, r = evaluate(spec(lever="budget", daily_budget=300_000), facts())
    assert o.ads.spend_after == o.ads.spend_now and o.fixed_cost == 0
    assert "không làm tăng chi tiêu" in o.ads.spend_text
    assert r.json()["delta"]["orders"]["value"] == 0


def test_budget_raise_on_a_capped_campaign_spends_the_new_budget():
    """Capped: 100.000 of a 100.000 budget every day -> the new 150.000 is spent (the most it
    can), orders at the measured CPA; +45 ad orders, +22,5 incremental."""
    c = camp(budget=100_000)
    o, r = evaluate(spec(lever="budget", daily_budget=150_000), facts(c, budget=D(100_000)))
    a = o.ads
    assert a.spend_basis == "budget_capped" and "tiêu hết ngân sách" in a.spend_text
    assert a.spend_after == D(4_500_000) and a.orders_after == pytest.approx(D(135))
    assert o.fixed_cost == pytest.approx(D(1_500_000))
    assert r.json()["delta"]["orders"]["value"] == 22  # 22,5 shown as whole đơn
    assert r.json()["roi"]["value"] is not None


def test_budget_state_reads_the_campaigns_own_days():
    capped = [CampaignDay(D(100_000), D(100_000))] * 20
    free = [CampaignDay(D(120_000), D(200_000))] * 6
    s = measure.budget_state(D(3_320_000), 30, D(100_000), capped + free)
    assert s.capped and s.uncapped_rate == D(120_000) and s.running_days == 26
    open_ = measure.budget_state(D(2_000_000), 30, D(150_000), [CampaignDay(D(80_000), None)] * 25)
    assert not open_.capped and open_.uncapped_rate == D(80_000)


def test_unlimited_budget_on_a_capped_campaign_is_not_estimable():
    c = camp(budget=100_000)
    o, r = evaluate(spec(lever="budget", unlimited=True), facts(c, budget=D(100_000)))
    assert o.drivers[0].basis == "not_estimable" and not r.estimable
    assert o.ads.spend_after is None and "chưa đo được mức chi" in o.ads.spend_text
    assert r.json()["ads"]["cpa"]["after"] is None


def test_unlimited_budget_on_an_uncapped_campaign_keeps_its_rate():
    o = ads_edit_option(spec(lever="budget", unlimited=True), facts())
    assert o.ads.spend_after == o.ads.spend_now and o.drivers[0].basis == "measured"


# -- roas ----------------------------------------------------------------------------------------


def test_roas_target_spends_what_shopee_spent_at_a_similar_target():
    """Campaign c2 spent 60 % of its budget at ROAS 4,0: at 4,2 the edit spends 90.000/day."""
    hist = camp("c2", spend=2_700_000, budget=150_000, roas=D("4.0"))
    o = ads_edit_option(spec(lever="roas", roas_target=4.2), facts(campaigns=(camp(), hist)))
    a = o.ads
    assert a.spend_basis == "roas_history" and a.spend_after == D(2_700_000)
    assert a.orders_after == pytest.approx(D(81))  # at the measured CPA
    assert o.drivers[0].basis == "measured"


def test_roas_target_without_history_is_cost_and_break_even_only():
    o, r = evaluate(spec(lever="roas", roas_target=8), facts())
    assert o.drivers[0].basis == "not_estimable" and not r.estimable
    assert o.fixed_cost == D(1_500_000)  # tiêu hết 150.000/day: 50.000 more × 30
    assert r.break_even_orders is not None and r.cost_total == D(1_500_000)
    assert "Chưa có lịch sử" in o.ads.spend_text and o.ads.spend_after is None
    j = r.json()["ads"]
    assert j["verdict"]["now"] == "co_lai" and j["verdict"]["after"] is None


# -- products ------------------------------------------------------------------------------------


def test_remove_product_loses_its_measured_share():
    """i1 = 60 % of the spend, 50 % of the direct orders: after 40.000/day and 1,5 đơn/day ->
    CPA 26.667đ (from 33.333đ)."""
    o, r = evaluate(spec(lever="remove_product", item_id="i1"), facts())
    a = o.ads
    assert a.spend_basis == "product_rows" and "60%" in a.spend_text
    assert a.spend_after == pytest.approx(D(1_200_000))
    assert a.orders_after == pytest.approx(D(45))
    assert a.cpa_after == pytest.approx(D(1_200_000) / 45)
    assert r.estimable and r.json()["delta"]["orders"]["value"] == -22


def test_add_product_uses_its_own_past_ad_rates():
    """i3 ran in c2: 10.000đ/day, 15 direct orders in 30 days -> CPA 10.000 ÷ 0,45 = 22.222đ."""
    o = ads_edit_option(spec(lever="add_product", item_id="i3"), facts())
    a = o.ads
    assert a.spend_after - a.spend_now == pytest.approx(D(300_000))
    assert a.orders_after - a.orders_now == pytest.approx(D("13.5"))
    assert "đo trên chính sản phẩm này" in a.spend_text and o.drivers[0].basis == "measured"


def test_add_product_never_advertised_is_not_estimable_with_its_cost():
    o, r = evaluate(spec(lever="add_product", item_id="i9"), facts())
    assert o.drivers[0].basis == "not_estimable" and not r.estimable
    assert o.fixed_cost == D(1_500_000)  # the unused 50.000/day of the budget × 30
    assert "chưa từng chạy quảng cáo" in o.ads.spend_text


# -- incremental vs all ad orders ----------------------------------------------------------------


def test_incremental_share_counts_card_orders_with_vs_without_ads():
    assert measure.incremental_share(on_off()) == Band(D("0.5"), D("0.5"), D("0.5"))
    # ads add 4 orders and the organic ones stay: every ad order is extra
    assert measure.incremental_share(on_off(organic_on=10)).p50 == 1
    assert measure.incremental_share(on_off()[:3]) is None  # too few on days


def test_without_on_off_days_the_edit_is_cost_and_break_even_only():
    o, r = evaluate(spec(lever="budget", daily_budget=80_000), facts(days=()))
    assert (
        o.drivers[0].basis == "not_estimable" and o.drivers[0].note == ads_edit.NOTE_NO_INCREMENTAL
    )
    assert not r.estimable and r.json()["ads"]["cpa"]["after"] is not None
    assert r.json()["ads"]["incremental"]["orders_extra"] is None


def test_a_campaign_without_history_is_not_estimable_with_the_new_budget_as_cost():
    f = AdsEditFacts(campaign=None, name="x", cancel_rate=D(0))
    o, r = evaluate(spec(lever="budget", daily_budget=200_000), f)
    assert not r.estimable and o.fixed_cost == D(6_000_000) and o.ads is None


# -- several campaigns, base, cancel rate --------------------------------------------------------


def test_several_campaigns_add_up_with_weighted_break_even():
    one = ads_edit_option(spec(lever="budget", daily_budget=80_000), facts()).ads
    two = ads_edit_option(
        spec(lever="budget", daily_budget=80_000, campaign_key="c3"), facts(ppo=D(20_000))
    ).ads
    total = integrate._sum_ads([one, two])
    assert isinstance(total, AdsEvaluation)
    assert total.spend_now == one.spend_now + two.spend_now
    assert total.break_even_cpa == pytest.approx(D(35_000))
    assert integrate._sum_ads([one, None]) is None


def test_break_even_cpa_adds_the_ad_spend_back():
    """Stored profit is after ads: 12.000.000 ÷ 600 + 3.000.000 ÷ 600 = 25.000đ per order."""
    assert integrate.profit_per_order_before_ads(base()) == D(25_000)


def test_cancel_rate_from_placed_vs_confirmed_overview_days():
    def day(d, kind, orders):
        return SimpleNamespace(
            segment="all", day=date(2026, 10, d), order_type=kind, orders=orders, gmv=1, clicks=1
        )

    rows = [day(1, "placed", 100), day(1, "confirmed", 90), day(2, "placed", 50)]
    assert cancel_rate_of(rows) == D("0.1")  # day 2 has no confirmed row: left out
    assert cancel_rate_of([day(1, "confirmed", 90)]) is None
