"""P98 W2-F: per-family drivers / sources / basis / cost, and every family through engine.run."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import (
    ALL_SOURCES,
    CARD_SOURCES,
    Band,
    FunnelBase,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import (
    FamilyExtras,
    FamilyRefused,
    common,
    option_for,
)
from juli_backend.services.shopee_builder.engine_families.facts import (
    AdsFacts,
    AdsNewCampaign,
    AffiliatePlan,
    ComboFacts,
    KolChoice,
    KolFacts,
    LiftEvidence,
    ListingComboFacts,
    PackEvidence,
    PriceFacts,
    SimpleFacts,
    VoucherFacts,
)
from juli_backend.services.shopee_builder.engine_families.families import (
    ads_option,
    affiliate_option,
    combo_option,
    listing_combo_option,
    price_option,
    simple_option,
    voucher_option,
)
from juli_backend.services.shopee_builder.engine_families.measure import (
    AdCampaignHist,
    AdDay,
    KolBeforeAfter,
    KolRates,
)


def b(a, m, c):
    return Band(D(str(a)), D(str(m)), D(str(c)))


def src(key, views, clicks, orders, gmv, profit):
    return SourceFunnel(key, D(views), D(clicks), D(orders), D(gmv), D(profit))


def base():
    return FunnelBase(
        "shop-1",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, 20_000_000, 4_000_000),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000),
            src("lien_ket", 10000, 400, 20, 2_000_000, 400_000),
            src("live", 5000, 250, 10, 1_000_000, 200_000),
            SourceFunnel("chenh_lech_nguon", None, None, D(5), D(500_000), D(100_000)),
        ),
        D("0.3"),
    )


def ctx():
    return SimpleNamespace(env=None)


# -- voucher -------------------------------------------------------------------------------------


def voucher_facts(**kw):
    d = dict(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        per_use=D(8000),
        qualifying_share=D("0.4"),
        raise_gap_per_order=D(10_000),
        below_share=D("0.6"),
        usage_rate=D("0.5"),
        near_share=D("0.3"),  # P98 E2: the orders within 20 % below the minimum
        reach_gap=D(12_000),
    )
    d.update(kw)
    return VoucherFacts(**d)


def voucher(**kw):
    d = dict(kind="voucher", discount_type="amount", value=8000, min_spend=120_000, usage_limit=50)
    d.update(kw)
    return sp.VoucherSpec(**d)


def test_voucher_min_spend_drivers_sources_cost():
    o = voucher_option(voucher(start=date(2026, 11, 1), end=date(2026, 11, 14)), voucher_facts())
    assert [d.metric for d in o.drivers] == ["aov", "ctor"]
    assert all(d.sources == ALL_SOURCES and d.basis == "prior" for d in o.drivers)
    assert o.duration_days == 14
    offer = o.offers[0]
    assert offer.per_use == D(8000) and offer.use_cap == D(50)
    # existing qualifying orders are included, then the near orders raised over the minimum
    # (too few orders to measure the reach: the tagged 0 / 20 / 50 % prior on them, E2)
    assert offer.use_share.p10 == D("0.4") * D("0.5")
    assert offer.use_share.p90 == (D("0.4") + D("0.5") * D("0.3")) * D("0.5")
    aov = o.drivers[0].lift
    assert aov.p10 == 0 and aov.p90 == D("0.5") * D("0.3") * D(12_000) / D(100_000)


def test_voucher_review_is_ctor_only_and_scopes():
    o = voucher_option(voucher(min_spend=0, value=5000), voucher_facts())
    assert [d.metric for d in o.drivers] == ["ctor"] and o.kind == "review_voucher"
    live = voucher_option(voucher(scope="livestream"), voucher_facts())
    assert all(d.sources == ("live",) for d in live.drivers)
    fol = voucher_option(voucher(scope="follower"), voucher_facts())
    assert all(d.sources == ALL_SOURCES for d in fol.drivers)
    assert common.NOTE_FOLLOWER in (fol.note or "")


def test_voucher_reduce_saves_into_profit_and_lowers_ctor():
    o = voucher_option(voucher(), voucher_facts(baseline_per_use=D(12_000)))
    assert [d.metric for d in o.drivers] == ["ctor"] and o.drivers[0].lift.p10 < 0
    assert o.profit_per_order_after == D(20_000) + D(4000) * D("0.4") * D("0.5")


def test_voucher_end_to_end():
    o = voucher_option(voucher(start=date(2026, 11, 1), end=date(2026, 11, 14)), voucher_facts())
    r = run(base(), o, n=600)
    assert r.estimable and r.basis == "prior" and r.likely and r.drivers == ("aov", "ctor")
    assert r.cost_total > 0 and r.json()["basis_weak"] is True
    assert_funnel(r)


def assert_funnel(r):
    for sc in (r.low, r.likely, r.high):
        assert sc is not None
        if sc.views and sc.clicks:
            assert sc.orders <= sc.clicks
        assert sc.gmv == pytest.approx(
            sum((row["gmv"] or 0) for row in sc.by_source.values()), rel=D("1e-6")
        )
        assert sc.orders == pytest.approx(
            sum((row["orders"] or 0) for row in sc.by_source.values()), rel=D("1e-6")
        )


# -- combo ---------------------------------------------------------------------------------------


def combo_spec():
    return sp.ComboSpec(
        kind="combo",
        item_ids=["i1"],
        discount_type="pct",
        tiers=[sp.ComboTier(qty=2, value=5), sp.ComboTier(qty=3, value=10)],
    )


def combo_facts():
    # P100-C (B.10): a combo estimates only with a measured reach (no 0 / 20 / 50 % prior)
    return ComboFacts(
        D(100_000),
        D(20_000),
        D(4000),
        D("0.15"),
        D("0.3"),
        D(50_000),
        reach=Band(D("0.05"), D("0.1"), D("0.15")),
    )


def test_combo_drivers_and_cost_on_every_tier_order():
    o = combo_option(combo_spec(), combo_facts())
    assert [d.metric for d in o.drivers] == ["aov", "ctor"]
    assert o.drivers[0].basis == "measured"
    assert all(d.sources == ALL_SOURCES for d in o.drivers)
    offer = o.offers[0]
    assert offer.per_use == D(4000)
    assert offer.use_share.p10 == D("0.15") + D("0.05")  # today's tier orders + who moves up
    assert offer.use_share.p90 == D("0.15") + D("0.15")


def test_combo_end_to_end():
    r = run(base(), combo_option(combo_spec(), combo_facts()), n=500)
    assert r.estimable and r.cost_total > 0
    assert_funnel(r)


# -- new combo listing ---------------------------------------------------------------------------


def listing_spec():
    return sp.ListingComboSpec(
        kind="listing_combo", title="Combo 2", price=180_000, stock=10, member_ids=["a", "b"]
    )


def lc_facts(pack=None):
    return ListingComboFacts(
        D(100_000), D(20_000), D("0.2"), D(200_000), D(180_000), D(21_000), pack
    )


def test_listing_combo_switch_moves_aov_not_orders_without_pack():
    o = listing_combo_option(listing_spec(), lc_facts())
    assert [d.metric for d in o.drivers] == ["aov"]
    assert common.NOTE_NO_PACK_EVIDENCE in (o.note or "")
    assert o.profit_per_order_after == D(21_000) and o.duration_days is None
    r = run(base(), o, n=300)
    assert r.json()["delta"]["orders"]["value"] == 0
    assert_funnel(r)


def test_listing_combo_extra_orders_only_from_matching_pack():
    pack = PackEvidence(D(30_000), 30, D("0.05"), D("0.04"), D(180_000), D(30_000))
    o = listing_combo_option(listing_spec(), lc_facts(pack))
    assert [d.metric for d in o.drivers] == ["aov", "views"]
    added = o.drivers[1].added
    assert o.drivers[1].sources == CARD_SOURCES and o.drivers[1].basis == "measured"
    assert added.views.p50 == D(30_000) and added.extra_share.p50 == 1
    r = run(base(), o, n=300)
    # 30.000 views x 5 % x 4 % = 60 orders
    assert r.json()["delta"]["orders"]["value"] == pytest.approx(60, rel=0.05)
    assert_funnel(r)


# -- price ---------------------------------------------------------------------------------------


def test_price_family_drivers_and_single_profit_effect():
    spec = sp.ProductDiscountSpec(
        kind="product_discount", item_id="i1", variations=[sp.VariationPrice(discount_pct=10)]
    )
    facts = PriceFacts(
        D(100_000),
        D(20_000),
        D(12_000),
        D("0.9"),
        D("0.3"),
        LiftEvidence(b(0.02, 0.06, 0.1), "product_history"),
    )
    o = price_option(spec, facts)
    assert [d.metric for d in o.drivers] == ["ctor", "aov"]
    assert o.drivers[0].basis == "product_history" and o.drivers[1].lift.p50 == D("-0.1")
    # profit_per_order_after carries the price effect as-is; the engine's AOV driver then moves
    # GMV only, so the price effect counts once (ADR-122 d.10)
    assert o.profit_per_order_after == D(12_000)
    r = run(base(), o, n=400)
    assert r.basis == "product_history" and r.drivers == ("ctor", "aov")
    assert_funnel(r)


# -- listing / basket / gift ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "metrics", "sources"),
    [
        (sp.TitleSpec(kind="title", item_id="i", title="x"), ["views", "ctr"], CARD_SOURCES),
        (
            sp.CoverSpec(
                kind="cover_image", item_id="i", overlay=sp.CoverOverlay(layout="banner_top")
            ),
            ["ctr"],
            CARD_SOURCES,
        ),
        (sp.PriceDisplaySpec(kind="price_display", item_id="i"), ["ctr"], CARD_SOURCES),
        (
            sp.DescriptionSpec(kind="description_first_line", item_id="i", first_line="x"),
            ["ctor"],
            ALL_SOURCES,
        ),
        (sp.HideSpec(kind="listing_hide", item_id="i"), ["views"], ALL_SOURCES),
        (sp.RelistSpec(kind="listing_relist", item_id="i"), ["views"], ALL_SOURCES),
        (
            sp.AddOnSpec(
                kind="add_on", main_item_id="i", addons=[sp.AddOn(item_id="j", price=1000)]
            ),
            ["aov"],
            ALL_SOURCES,
        ),
        (
            sp.VariationSetSpec(
                kind="variation_set",
                item_id="i",
                new_variations=[sp.NewVariation(name="Set 3", price=1000)],
            ),
            ["aov", "ctor"],
            ALL_SOURCES,
        ),
        (
            sp.GiftSpec(
                kind="gift",
                gift=sp.GiftItem(unit_cost=1000),
                trigger=sp.GiftTrigger(type="min_spend", amount=1),
            ),
            ["ctor"],
            ALL_SOURCES,
        ),
    ],
)
def test_simple_families_table_and_end_to_end(spec, metrics, sources):
    facts = SimpleFacts(LiftEvidence(b(0.01, 0.04, 0.08), "shop"))
    o = simple_option(spec, facts)
    assert [d.metric for d in o.drivers] == metrics
    assert all(d.sources == sources for d in o.drivers)
    # hiding a listing takes away all of its views: the product's own 30 days, not a lift model
    assert o.drivers[0].basis == ("product_history" if spec.kind == "listing_hide" else "shop")
    if len(o.drivers) == 2:
        assert o.drivers[1].basis == "prior"
    r = run(base(), o, n=300)
    assert r.estimable and list(r.drivers) == metrics
    assert_funnel(r)


# -- ads -----------------------------------------------------------------------------------------


def camp(
    key="c1",
    items=("i1",),
    spend=1_000_000,
    imp=500_000,
    clicks=15_000,
    orders=300,
    gmv=30_000_000,
    **kw,
):
    return AdCampaignHist(
        key,
        frozenset(items),
        "product_search",
        D(spend),
        D(imp),
        D(clicks),
        D(orders),
        D(gmv),
        **kw,
    )


def on_off_days(extra=3):
    days = [AdDay(False, D(5 + (i % 2)), D(0)) for i in range(10)]
    days += [AdDay(True, D(5 + extra + (i % 2)), D(10)) for i in range(10)]
    return tuple(days)


def new_campaign(**kw):
    d = dict(
        item_ids=("i1",), daily_budget=D(100_000), start=date(2026, 11, 10), end=date(2026, 11, 19)
    )
    d.update(kw)
    return AdsNewCampaign(**d)


def test_ads_measured_views_from_cpm_and_extra_share():
    facts = AdsFacts((camp(),), on_off_days(), D(30_000))
    o = ads_option(new_campaign(), facts)
    d = o.drivers[0]
    assert d.metric == "views" and d.sources == CARD_SOURCES and d.basis == "measured"
    # CPM = 1.000.000 / 500.000 x 1000 = 2.000 đ; spend 1.000.000 -> 500.000 views
    assert d.added.views.p50 == D(500_000)
    assert d.added.ctr == D("0.03") and d.added.ctor == D("0.02") and d.added.aov == D(100_000)
    assert D(0) < d.added.extra_share.p50 <= 1
    assert o.fixed_cost == D(1_000_000) and o.duration_days == 10
    r = run(base(), o, n=400)
    assert r.estimable and r.basis == "measured"
    assert_funnel(r)


def test_ads_roas_target_uses_historic_utilisation():
    hist = camp(daily_budget=D(100_000), days=10, roas_target=D("3.5"), spend=600_000)
    facts = AdsFacts((hist, camp("c2", ("zz",), spend=1_000_000)), on_off_days(), D(30_000))
    o = ads_option(new_campaign(roas_target=D("3.4")), facts)
    assert o.fixed_cost == D(1_000_000) * D("0.6")


def test_ads_not_estimable_without_on_off_history():
    o = ads_option(new_campaign(), AdsFacts((camp(),), (), D(30_000)))
    assert o.drivers[0].basis == "not_estimable"
    assert o.drivers[0].note == common.NOTE_ADS_NOT_ESTIMABLE
    assert o.fixed_cost == D(1_000_000)
    r = run(base(), o, n=100)
    assert not r.estimable and r.cost_total == D(1_000_000) and r.break_even_orders is not None
    r2 = run(base(), ads_option(new_campaign(), AdsFacts()), n=100)
    assert not r2.estimable  # no campaign at all: no general prior


def test_ads_falls_back_to_same_ad_type_shop_wide():
    facts = AdsFacts((camp(items=("other",)),), on_off_days(), D(30_000))
    o = ads_option(new_campaign(), facts)
    assert o.drivers[0].basis == "measured" and "cùng loại" in (o.note or "")


# -- affiliate -----------------------------------------------------------------------------------


def kol_facts(measured=True, cashback_rates=True):
    rates = {
        "k1": KolRates("k1", "kol_one", 30, D(20_000), D(800), D(40), D(4_000_000)),
        "cb": KolRates("cb", "accesstradevn", 30, D(10_000), D(400), D(20), D(2_000_000)),
    }
    ba = {"k1": KolBeforeAfter(14, 14, D(30), D(60), D(40))} if measured else {}
    return KolFacts(rates, ba, {"i1": D(30_000)}, D(40_000))


def test_affiliate_cost_exact_and_measured_extra_share():
    plan = AffiliatePlan(
        (KolChoice("k1", "kol_one", ("i1",), D(10), D(0), 2, D(20_000)),), duration_days=30
    )
    o = affiliate_option(plan, kol_facts())
    d = o.drivers[0]
    assert d.sources == ("lien_ket",) and d.basis == "measured"
    assert d.added.views.p50 == D(20_000) and d.added.ctr == D("0.04") and d.added.ctor == D("0.05")
    assert d.added.aov == D(100_000)
    # commission 10 % x 4.000.000 + 2 x 30.000 + 20.000 shipping
    assert o.fixed_cost == D(400_000) + D(60_000) + D(20_000)
    assert D(0) < d.added.extra_share.p50 <= 1
    r = run(base(), o, n=400)
    assert r.estimable
    assert_funnel(r)


def test_affiliate_unmeasured_is_not_estimable_with_exact_cost():
    plan = AffiliatePlan((KolChoice("k1", "kol_one", ("i1",), D(10), D(0), 1, D(10_000)),), 30)
    o = affiliate_option(plan, kol_facts(measured=False))
    assert o.drivers[0].basis == "not_estimable"
    assert o.drivers[0].note == common.NOTE_KOL_NOT_ESTIMABLE
    assert o.fixed_cost == D(400_000) + D(30_000) + D(10_000)
    r = run(base(), o, n=100)
    assert not r.estimable and r.break_even_orders is not None


def test_cashback_affiliate_extra_share_zero_and_no_samples():
    plan = AffiliatePlan((KolChoice("cb", "accesstradevn", ("i1",), D(5), D(0), 3, D(5000)),), 30)
    o = affiliate_option(plan, kol_facts(measured=False))
    assert o.drivers[0].basis == "measured" and o.drivers[0].added.extra_share.p90 == 0
    assert o.fixed_cost == D(5) / 100 * D(2_000_000)  # commission only, no samples
    assert common.CASHBACK_LABEL in (o.note or "")
    r = run(base(), o, n=200)
    assert r.json()["delta"]["orders"]["value"] == 0


# -- dispatcher ----------------------------------------------------------------------------------


def test_ads_edit_needs_its_campaign_history():
    spec = sp.AdsSpec(kind="ads", lever="budget", campaign_key="c", daily_budget=200_000)
    with pytest.raises(FamilyRefused) as e:
        option_for(spec, ctx())
    assert e.value.code == "no_campaign_report"


def test_dispatcher_routes_ads_and_affiliate_plans():
    o = option_for(
        new_campaign(), ctx(), FamilyExtras(ads=AdsFacts((camp(),), on_off_days(), D(1)))
    )
    assert o.kind == "ads_new_campaign"
    plan = AffiliatePlan((KolChoice("k1", "kol_one", ("i1",), D(10)),), 30)
    assert option_for(plan, ctx(), FamilyExtras(kol=kol_facts())).kind == "affiliate_sample"
    # P99: a commission rate without a KOL is cost + break-even only (extra orders measured only)
    from juli_backend.services.shopee_builder.engine_families.facts import AffiliateRateFacts
    from juli_backend.services.shopee_builder.engine_families.families import (
        affiliate_rate_option,
    )

    rate = sp.AffiliateSpec(kind="affiliate", item_id="i", commission_pct=5)
    o = affiliate_rate_option(rate, AffiliateRateFacts("i", D(600_000), 30, D(50_000), 2))
    assert o.kind == "affiliate_commission"
    assert [d.basis for d in o.drivers] == ["not_estimable"]
    assert o.fixed_cost == D("0.05") * D(600_000) + D(50_000)  # commission × GMV + samples
    r = run(base(), o, n=1)
    assert not r.estimable and r.cost_total == o.fixed_cost and r.break_even_orders is not None
    with pytest.raises(FamilyRefused):  # several products: the caller expands them first
        option_for(sp.AffiliateSpec(kind="affiliate", targets=["i", "j"], commission_pct=5), ctx())
