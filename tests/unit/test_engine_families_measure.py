"""Pure measurement helpers: CPM, ad rates, on / off-day extra share, KOL rates, cashback names."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_builder.engine_families.measure import (
    AdCampaignHist,
    AdDay,
    KolBeforeAfter,
    ad_rates,
    incremental_share,
    is_cashback,
    kol_extra_share,
    spend_utilisation,
)


def camp(key, items, spend, imp, ad_type="product_search", **kw):
    return AdCampaignHist(
        key, frozenset(items), ad_type, D(spend), D(imp), D(imp) / 30, D(10), D(1_000_000), **kw
    )


def test_cpm_prefers_the_products_past_campaigns_and_gives_a_band():
    cs = [
        camp("a", ["i1"], 100_000, 100_000),
        camp("b", ["i1"], 300_000, 100_000),
        camp("c", ["z"], 10, 1000),
    ]
    r = ad_rates(cs, ["i1"], "product_search")
    assert r.scope == "product" and r.campaigns == 2
    assert (r.cpm_low, r.cpm_mid, r.cpm_high) == (D(1000), D(2000), D(3000))
    assert r.ctr == D(1) / 30


def test_cpm_falls_back_to_ad_type_then_none():
    cs = [camp("c", ["z"], 200_000, 100_000)]
    assert ad_rates(cs, ["i1"], "product_search").scope == "shop_ad_type"
    assert ad_rates(cs, ["i1"], "shop_ads") is None
    assert ad_rates([], ["i1"], "product_search") is None


def test_spend_utilisation_from_similar_roas_only():
    cs = [camp("a", ["i"], 700_000, 1, daily_budget=D(100_000), days=10, roas_target=D("3.5"))]
    assert spend_utilisation(cs, D("3.2")) == D("0.7")
    assert spend_utilisation(cs, D("5")) is None


def test_incremental_share_measured_and_clamped():
    days = [AdDay(False, D(5 + i % 2)) for i in range(8)]
    days += [AdDay(True, D(5 + i % 2), D(6)) for i in range(8)]
    s = incremental_share(days)
    assert s.p10 <= s.p50 <= s.p90 and s.p50 == 1  # organic flat on ad days: all 6 ad orders extra
    flat = [AdDay(False, D(5), D(0)) for _ in range(6)] + [
        AdDay(True, D(0), D(5)) for _ in range(6)
    ]
    assert incremental_share(flat).p50 == 0  # ads only replaced organic orders
    assert incremental_share(days[:3] + days[8:12]) is None  # too few off days
    assert incremental_share([AdDay(False, D(1))] * 6 + [AdDay(True, D(2), D(0))] * 6) is None


def test_kol_extra_share_needs_days_and_orders():
    m = KolBeforeAfter(14, 14, D(30), D(60), D(40))
    s = kol_extra_share(m)
    assert s.p10 <= s.p50 <= s.p90 and s.p50 == D(30) / 40
    assert kol_extra_share(KolBeforeAfter(3, 14, D(1), D(60), D(40))) is None
    assert kol_extra_share(KolBeforeAfter(14, 14, D(30), D(60), D(0))) is None
    assert kol_extra_share(None) is None


@pytest.mark.parametrize(
    ("handle", "expected"),
    [
        ("accesstradevn", True),
        ("AccessTradeVN", True),
        ("shopbackvn_abc", True),
        ("shopbackvn_", True),
        ("kol_review_01", False),
        ("accesstradevn2", True),
        ("mylittleshop", False),
    ],
)
def test_cashback_by_name(handle, expected):
    assert is_cashback(handle) is expected
