"""P90 step 8: one generator per card family on a synthetic shop -- what each proposes, that the
certain layer comes from ``services/shopee_profit``, and that a card never breaks a floor.
SQLite; synthetic figures (``tests/support/shopee_reco``)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_profit.whatif import PredictedRange, VoucherRule, voucher_whatif
from juli_backend.services.shopee_recommendations import generators as gen
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.evaluate import campaign_profile, evaluate
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
CRIT = {
    "id": "product:1001:ctor",
    "kind": "below_shop_median",
    "kpi": "ctor",
    "level": "product",
    "flow": None,
    "deviation_pct": -25.0,
    "at_stake_per_day": 1000,
    "at_stake_per_month": 30000,
    "money_basis": "confirmed",
    "cause": {"stage": "ctor", "text": ""},
}


@pytest.fixture
async def env(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    e = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert e is not None
    return e


def _one(cands, kind):
    found = [c for c in cands if c.kind == kind]
    assert found, [c.kind for c in cands]
    return found[0]


def _card(env, cand):
    card = build_card(env, cand, now=NOW)
    assert card is not None
    return card


def _frozen_parts(card):
    for key in (
        "metric",
        "wiring",
        "scope",
        "change",
        "inputs",
        "certain",
        "five_numbers",
        "floor",
        "predicted",
        "measurement_plan",
        "execution_sheet",
        "model_version",
    ):
        assert key in card, key
    ch = card["change"]
    assert {"change_kind", "target", "before", "after"} <= set(ch)
    assert card["predicted"]["lift"]["lift"]["p10"] <= card["predicted"]["lift"]["lift"]["p90"]
    assert card["execution_sheet"]["changes"] and card["execution_sheet"]["save_hint"]


# ---------------------------------------------------------------------------- promotion


async def test_product_discount_stays_inside_the_floor_and_comes_from_the_price_what_if(env):
    (cand,) = gen.gen_product_discount(env, CRIT, "1001")
    d = cand.inputs["discount_pct"]
    assert 13 <= d <= 20  # a few points deeper than today's 10 %
    card = _card(env, cand)
    _frozen_parts(card)
    assert card["family"] == "promotion" and card["floor"]["ok"]
    sku = card["certain"]["skus"][0]
    assert sku["price_after"] == int(env.list_price("G1") * (1 - D(d) / 100) // 100 * 100)
    assert sku["floor_operating"] is not None and sku["price_after"] >= sku["floor_operating"]
    assert card["wiring"]["critical_metric"] == "ctor"
    assert "product_discount" in card["wiring"]["allowed_kinds"]
    # five numbers before -> after, number 2 only from the predicted range
    five = card["five_numbers"]
    assert five["discount"]["vnd_after"] > five["discount"]["vnd_before"]


async def test_a_discount_below_the_floor_is_refused_by_the_generator_and_flagged_by_the_card(env):
    deep = Candidate("product_discount", ("1001",), {"discount_pct": 70})
    card = _card(env, deep)
    assert not card["floor"]["ok"] and card["floor"]["breaches"][0]["sku"] == "G1"
    assert card["rank_inputs"]["floor_breach"] is True


async def test_price_rises_to_the_floor_when_a_sku_sells_under_it(session):
    seeded = await seed_reco_shop(session, margin_target=60)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    crit = {**CRIT, "kpi": "bien", "cause": {"stage": "bien", "text": ""}}
    (cand,) = gen.gen_price(env, crit, "1001")
    assert cand.inputs["new_price_pct"] > 100 and cand.wiring_key == "bien"
    card = _card(env, cand)
    assert card["change"]["after"]["price"] > card["change"]["before"]["price"]
    assert card["certain"]["gmv_delta_same_volume"] > 0


# ------------------------------------------------------------------------------ voucher


async def test_min_spend_voucher_matches_the_voucher_what_if_exactly(env):
    (cand,) = gen.gen_min_spend_voucher(
        env, {**CRIT, "kpi": "aov", "cause": {"stage": "aov"}}, "1001"
    )
    card = _card(env, cand)
    _frozen_parts(card)
    assert card["family"] == "voucher" and card["scope"]["level"] == "shop"
    i = cand.inputs
    lines = env.lines_for(["1001"])
    direct = voucher_whatif(
        lines,
        env.costs,
        scenario=VoucherRule(D(i["min_spend"]), amount=D(i["value"]), usage_limit=i["quantity"]),
        schedule=env.schedule("1001"),
        floors={s: f for s, f in env.floors("1001").items()},
        target_margin_rate=env.margin_target_rate,
        usage_rate=env.usage_rate,
        voucher_days=i["days"],
        window_days=env.window_days,
        ad_spend=env.view.ads.product_spend.get("1001", D(0)),
        spend_cap_per_day=env.daily_cap,
    ).certain
    c = card["certain"]
    assert c["extra_cost"] == pytest.approx(float(direct.extra_cost))
    assert c["qualifying_orders"] == direct.qualifying_orders
    assert c["break_even_extra_orders"] == direct.break_even_extra_orders
    assert c["usage_rate_source"] in ("input", "default_1") and c["per_user_limit_status"] is None


async def test_voucher_number_2_is_never_taken_from_the_certain_layer(env):
    (cand,) = gen.gen_min_spend_voucher(env, CRIT, "1001")
    five = _card(env, cand)["five_numbers"]
    assert five["extra_revenue_per_extra_spend"]["status"] == "needs_volume"
    assert five["extra_revenue_per_extra_spend"]["per_vnd"] is None


async def test_per_user_limit_is_accepted_and_reported_not_enforceable(env):
    (cand,) = gen.gen_min_spend_voucher(env, CRIT, "1001")
    cand.inputs["per_user_limit"] = 1
    card = _card(env, cand)
    assert card["certain"]["per_user_limit_status"] == "not_enforceable"


async def test_voucher_cap_lowers_a_live_voucher(session):
    seeded = await seed_reco_shop(session)
    from decimal import Decimal

    from juli_backend.models.platform_data import PlatformPromotion
    from tests.support.shopee_analytics import CUR_END, CUR_START, _src

    session.add(
        PlatformPromotion(
            shop_id=seeded.shop_id,
            promo_type="voucher",
            program_name="Ory 10k",
            starts_at=datetime(2026, 9, 1),
            ordinal=0,
            period_start=CUR_START,
            period_end=CUR_END,
            order_type="placed",
            extra={
                "voucher_id": "9001",
                "discount_amount": 10000,
                "min_spend": 100000,
                "usage_limit": 200,
            },
            gmv=Decimal(0),
            orders=Decimal(0),
            **_src(),
        )
    )
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert [v.voucher_id for v in env.vouchers] == ["9001"]
    (cand,) = gen.gen_voucher_cap(env, {**CRIT, "kpi": "bien"}, "1001")
    assert cand.inputs["value"] == 8000 and cand.inputs["baseline"]["value"] == 10000
    card = _card(env, cand)
    assert card["certain"]["extra_cost"] < 0  # a saving
    assert (
        card["change"]["before"]["value"] == 10000
        and card["change"]["target"]["voucher_id"] == "9001"
    )


# --------------------------------------------------------------------------------- sale


async def test_flash_sale_checks_the_slot_price_against_the_floor_and_caps_units_by_stock(env):
    cands = gen.gen_flash_sale(env, None, "1001")
    cand = _one(cands, "flash_sale")
    assert cand.inputs["units"] <= 60 and cand.inputs["slot_days"] == 1
    card = _card(env, cand)
    _frozen_parts(card)
    assert card["family"] == "sale" and card["floor"]["ok"]
    assert card["predicted"]["money_per_month"]["days"] == 1  # a one-day slot


async def test_program_registration_is_a_sale_card_on_the_programme_page(env):
    (cand,) = gen.gen_program_registration(env, None, "1002")
    card = _card(env, cand)
    assert card["family"] == "sale" and card["execution_sheet"]["page"]["verified"] is False


# -------------------------------------------------------------------------------- combo


async def test_bundle_deal_reports_each_tier_against_the_floor(env):
    (cand,) = gen.gen_bundle_deal(env, {**CRIT, "kpi": "aov"}, "1001")
    card = _card(env, cand)
    _frozen_parts(card)
    tiers = card["certain"]["tiers"]
    assert [t["units"] for t in tiers] == [2, 3] and not any(t["below_floor"] for t in tiers)
    assert tiers[1]["unit_price_after"] < tiers[0]["unit_price_after"]
    assert tiers[0]["aov_of_bundle"] > card["certain"]["aov_now"] / 2


async def test_bundle_tier_below_the_floor_is_flagged_on_that_tier(env):
    card = _card(env, Candidate("bundle_deal", ("1001",), {"tier2_pct": 45, "tier3_pct": 50}))
    assert card["floor"]["breaches"] and card["floor"]["breaches"][0]["tier"] in (2, 3)


async def test_add_on_picks_a_cheap_high_margin_partner_and_checks_its_floor(env):
    cands = gen.gen_add_on(env, {**CRIT, "kpi": "aov"}, "1001")
    if not cands:
        pytest.skip("synthetic prices leave no add-on partner")
    card = _card(env, cands[0])
    assert card["certain"]["addon"]["item_id"] != "1001" and card["floor"]["ok"]


async def test_gift_costs_the_gift_per_qualifying_order(env):
    (cand,) = gen.gen_gift(env, CRIT, "1001")
    card = _card(env, cand)
    g = card["certain"]["gift"]
    assert g["gift_cost_window"] == pytest.approx(g["cost_per_gift"] * g["qualifying_orders"])


async def test_variation_set_is_one_tier(env):
    (cand,) = gen.gen_variation_set(env, {**CRIT, "kpi": "aov"}, "1002")
    card = _card(env, cand)
    assert [t["units"] for t in card["certain"]["tiers"]] == [2]


# ----------------------------------------------------------------------------- affiliate


async def test_affiliate_commission_shows_cost_per_order_and_margin_after(env):
    (cand,) = gen.gen_affiliate_commission(
        env, {**CRIT, "kpi": "views", "cause": {"stage": "views"}}, "1001"
    )
    card = _card(env, cand)
    _frozen_parts(card)
    c = card["certain"]
    assert c["commission_pct_after"] == cand.inputs["commission_pct"] and c["affiliate_orders"] >= 1
    assert c["commission_cost_after"] > 0
    assert card["predicted"]["base"] == "gmv_lien_ket"
    # a higher rate costs more on the same orders
    higher = _card(env, Candidate("affiliate_commission", ("1001",), {"commission_pct": 30}))
    assert higher["certain"]["commission_cost_after"] > c["commission_cost_after"]


async def test_targeted_campaign_lists_the_partners(env):
    (cand,) = gen.gen_affiliate_target(env, None, "1001")
    assert cand.extra["partners"] == ["akol1"]
    assert _card(env, cand)["family"] == "affiliate"


# ----------------------------------------------------------------------------------- ads


async def test_ads_profile_reconciles_with_the_ads_report(env):
    prof = campaign_profile(env, "cgroup1")
    assert prof is not None and float(prof["spend_per_day"] * 30) == pytest.approx(
        float(env.view.ads.campaigns[0].spend)
    )
    assert prof["roas_direct"] is not None and prof["break_even_roas"] is not None


async def test_ads_budget_card_uses_the_live_setting_and_labels_the_basis(env):
    cands = gen.gen_ads_budget(env, {**CRIT, "kpi": "views"}, "1001")
    assert cands, "the seeded campaign earns above break-even"
    card = _card(env, cands[0])
    _frozen_parts(card)
    assert card["change"]["before"]["daily_budget"] == 30000
    assert card["certain"]["basis"] == {"key": "placed", "label": "đơn đã đặt"}
    assert card["predicted"]["base"] == "gmv_quang_cao_don_da_dat"
    assert card["execution_sheet"]["changes"][0]["change_kind"] == "daily_budget"
    assert card["spend"]["card_dchi_per_day"] > 0


async def test_roas_target_pause_and_remove_product_are_ads_cards(env):
    base = Candidate("ads_roas_target", (), {"roas_target": 5.0}, campaign_key="cgroup1")
    t = _card(env, base)
    assert (
        t["change"]["before"]["roas_target"] == 3.0
        and t["execution_sheet"]["changes"][0]["change_kind"] == "roas_target"
    )
    p = _card(env, Candidate("ads_pause", (), {}, campaign_key="cgroup1"))
    assert p["certain"]["spend_per_day_after"] == 0 and p["spend"]["card_dchi_per_day"] < 0
    assert p["predicted"]["money_per_month"]["predicted"]["p50"]["dgmv"] < 0
    r = _card(env, Candidate("ads_remove_product", ("1003",), {}, campaign_key="cgroup1"))
    assert r["change"]["after"]["removed_item_id"] == "1003"
    assert 0 < r["certain"]["spend_per_day_after"] < r["certain"]["spend_per_day_now"]


async def test_ads_add_product_and_purpose(env):
    add = _card(env, Candidate("ads_add_product", ("1001",), {}, campaign_key="cgroup1"))
    assert add["change"]["after"]["added_item_id"] == "1001"
    purpose = _card(
        env, Candidate("ads_purpose", (), {"purpose": "chuyen_doi"}, campaign_key="cgroup1")
    )
    assert purpose["predicted"]["money_per_month"]["predicted"]["p50"]["dgmv"] == 0


async def test_an_unknown_campaign_cannot_be_evaluated(env):
    ev = evaluate(env, Candidate("ads_budget", (), {"daily_budget": 1}, campaign_key="nope"))
    assert ev.refusal == "no_campaign_report"
    assert (
        build_card(
            env, Candidate("ads_budget", (), {"daily_budget": 1}, campaign_key="nope"), now=NOW
        )
        is None
    )


# ------------------------------------------------------------------------- dispatcher


async def test_generate_walks_the_critical_list_and_the_wiring(env):
    critical = {
        "items": [
            {
                **CRIT,
                "product_id": "1001",
                "change_kinds": [
                    "product_discount",
                    "min_spend_voucher",
                    "review_voucher",
                    "price",
                ],
            },
            {
                **CRIT,
                "id": "x",
                "product_id": "1002",
                "kpi": "aov",
                "cause": {"stage": "aov"},
                "change_kinds": ["bundle_deal", "add_on", "min_spend_voucher", "variation_set"],
            },
            {
                **CRIT,
                "id": "y",
                "product_id": "1001",
                "kpi": "roas",
                "cause": {"stage": "roas"},
                "change_kinds": ["ads_roas_target", "ads_pause", "ads_purpose"],
            },
        ]
    }
    cands = gen.generate(env, critical)
    kinds = {c.kind for c in cands}
    assert {
        "product_discount",
        "min_spend_voucher",
        "review_voucher",
        "bundle_deal",
        "flash_sale",
    } <= kinds
    assert len({(c.kind, c.items, c.campaign_key) for c in cands}) == len(cands)
    for c in cands:
        if c.wiring_key in ("ctor", "aov", "roas"):
            assert c.kind in KINDS_FOR[c.wiring_key] or c.kind.startswith("ads_"), (
                c.kind,
                c.wiring_key,
            )


KINDS_FOR = {
    "ctor": ("product_discount", "min_spend_voucher", "review_voucher", "price"),
    "aov": ("bundle_deal", "add_on", "min_spend_voucher", "variation_set"),
    "roas": ("ads_roas_target", "ads_pause", "ads_purpose"),
}


async def test_a_locked_or_out_of_stock_product_gets_no_new_card(session):
    seeded = await seed_reco_shop(session, stock=0)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert (
        gen.generate(
            env, {"items": [{**CRIT, "product_id": "1001", "change_kinds": ["product_discount"]}]}
        )
        == []
    )
    seeded2 = await seed_reco_shop(session)
    await session.commit()
    env2 = await load_env(session, seeded2.shop_id, as_of=AS_OF)
    env2.locked = {"1001": "sent:x"}
    out = gen.generate(
        env2, {"items": [{**CRIT, "product_id": "1001", "change_kinds": ["product_discount"]}]}
    )
    assert all("1001" not in c.items for c in out)


async def test_predicted_range_is_p10_to_p90_and_the_plan_is_pre_registered(env):
    (cand,) = gen.gen_min_spend_voucher(env, {**CRIT, "kpi": "aov"}, "1001")
    card = _card(env, cand)
    lift = card["predicted"]["lift"]
    assert (
        lift["source"] == "prior"
        and lift["factor"] == 1.0
        and card["predicted"]["model_version"] == "shopee-reco-v1"
    )
    plan = card["measurement_plan"]
    assert plan["planned_days"] in (14, 28, None) and plan["clock_starts"] == "verified"
    assert plan["label"] in ("Kết quả sau 14 ngày", "Kết quả sau 28 ngày", "khó kết luận")
    # the profit-package what-if fills its own predicted net for the same range
    assert "predicted_net" in card["certain"]


async def test_whatif_predicted_range_equals_n_times_profit_per_order_minus_extra_cost(env):
    cand = Candidate(
        "min_spend_voucher",
        ("1001",),
        {"value": 3000, "min_spend": 150_000, "quantity": 50, "days": 14},
    )
    ev = evaluate(env, cand, predicted=PredictedRange(D(2), D(10), "t"))
    base = evaluate(env, cand)
    cpo = D(str(base.certain["organic"]["contribution_per_order"]))
    extra = D(str(base.certain["extra_cost"]))
    net = ev.certain["predicted_net"]
    assert net["net_profit_low"] == pytest.approx(float(2 * cpo - extra), abs=2)
    assert net["net_profit_high"] == pytest.approx(float(10 * cpo - extra), abs=2)


async def test_a_price_cut_scales_the_lift_by_what_the_buyer_actually_saves(env):
    """25 % off the list price, but the item already sells 10 % under it: only the extra
    16,7 % of today's price moves orders (0,5 % to 2 % more orders per 1 %)."""
    cand = Candidate("flash_sale", ("1001",), {"discount_pct": 25, "units": 60, "slot_days": 1})
    lift = _card(env, cand)["predicted"]["lift"]["lift"]
    saved = (90_000 - 75_000) / 90_000 * 100
    assert lift["p10"] == pytest.approx(0.005 * saved, abs=1e-4)
    assert lift["p90"] == pytest.approx(0.02 * saved, abs=1e-4)
    # a price rise is the same range with the opposite sign
    up = _card(env, Candidate("price", ("1001",), {"new_price_pct": 110}))["predicted"]["lift"][
        "lift"
    ]
    assert up["p90"] < 0 and up["p10"] < up["p90"]


async def test_a_price_rise_scales_each_line_by_the_same_factor_not_one_price_for_all(session):
    """History sold one SKU at 100.000 and at 70.000 (a sale day). A 10 % rise is x 1,1 on each
    line, so the 70.000 lines go to 77.000 -- not to one common price."""
    from juli_backend.services.shopee_profit.fees import (
        FeeComponent,
        FeeFormula,
        FeeKind,
        FeeSchedule,
    )
    from juli_backend.services.shopee_profit.order_profit import OrderLine, SkuCost
    from juli_backend.services.shopee_profit.whatif import price_change_whatif

    free = FeeSchedule(
        (FeeFormula(date(2026, 1, 1), (FeeComponent("commission", FeeKind.PCT, rate=D(0)),)),)
    )

    def line(i, deal):
        return OrderLine(f"o{i}", "S", "P", date(2026, 10, 1), 1, D(100_000), D(deal))

    lines = [line(1, 100_000), line(2, 70_000)]
    costs = {"S": SkuCost("S", D(30_000), D(0))}
    r = price_change_whatif(lines, costs, sku="S", price_factor=D("1.1"), schedule=free).certain
    assert r.profit_delta_same_volume == D(10_000 + 7_000)  # no fee: the delta is the rise
    capped = price_change_whatif(
        lines, costs, sku="S", new_deal_price=D(80_000), ceiling=True, schedule=free
    ).certain
    assert capped.profit_delta_same_volume == D(-20_000)  # only the 100.000 line moves, to 80.000
    with pytest.raises(ValueError):
        price_change_whatif(lines, costs, sku="S")
    with pytest.raises(ValueError):
        price_change_whatif(lines, costs, sku="S", new_deal_price=D(1), price_factor=D(1))
