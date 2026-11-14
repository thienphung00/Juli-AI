"""P97 T4: the builder's table picker (D85.12), many-target cards (D85.13), ads levers (D85.17),
Combo khuyến mãi in Shopee's tiers (D85.15) and the new listing combo (D85.16). SQLite, synthetic
reco shop (``tests/support/shopee_reco``)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import multi
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import SpecRefused
from juli_backend.services.shopee_builder.translate import to_variant
from juli_backend.services.shopee_recommendations import (
    bundle_tiers,
    manual,
    plans,
    service,
    store,
    targets,
)
from juli_backend.services.shopee_recommendations.fill_queue import _card_targets
from tests.support.shopee_analytics import CUR_END, _src
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_builder import NOW, S, add_baskets, builder, one
from tests.unit.test_shopee_reco_plan import _USER_IDS, _actor


@pytest.fixture
async def shop(session):
    """Synthetic reco shop, owned here (no imported fixture, so no new lint suppression)."""
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)  # P98: the stored funnel
    await session.commit()
    return seeded


# ==================== picker

COLUMNS = (
    "category",
    "category_path",
    "margin_pct",
    "ctor_30d",
    "ctor_prev_30d",
    "ctor_down",
    "has_proposal",
    "in_ads",
    "in_kol",
)


async def test_every_row_has_the_filter_columns(session, shop):
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    assert out["products"]
    for row in out["products"]:
        for col in COLUMNS:
            assert col in row, col
        assert isinstance(row["has_proposal"], bool)
        assert isinstance(row["in_ads"], bool)
        assert isinstance(row["in_kol"], bool)


async def test_a_product_with_orders_has_a_margin_and_one_without_stays_unknown(session, shop):
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    sold = [r for r in out["products"] if r["orders_30d"] > 0 and r["has_cost"]]
    assert sold and all(r["margin_pct"] is not None for r in sold)
    unsold = [r for r in out["products"] if r["orders_30d"] == 0]
    assert all(r["margin_pct"] is None and r["ctor_down"] is None for r in unsold)


async def test_the_proposals_column_follows_the_cards_waiting_for_a_decision(session, shop):
    from juli_backend.models.shop_proposals import ShopProposal
    from tests.unit.test_shopee_builder import select

    rows = (await session.scalars(select(ShopProposal))).all()
    waiting = {p.item_id for p in rows if p.status in ("sent", "changes_requested") and p.item_id}
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    flagged = {r["item_id"] for r in out["products"] if r["has_proposal"]}
    assert flagged == waiting & {r["item_id"] for r in out["products"]}


# ==================== targets

DISCOUNT = {"kind": "product_discount", "discount_pct": 20}


async def rows(session, shop, **version):
    out = await one(session, shop, **version)
    assert out["ok"], out.get("refusal")
    return out, {r["id"]: r for r in out["targets"]}


def test_a_many_target_version_names_targets_xor_one_item():
    assert S(**DISCOUNT, targets=["1", "2"]).targets == ["1", "2"]
    for bad in (
        {**DISCOUNT, "targets": ["1"], "item_id": "2"},
        {**DISCOUNT, "targets": ["1", "1"]},
        {"kind": "product_discount", "targets": ["1"]},
        {"kind": "product_discount", "item_id": "1", "discount_pct": 10, "variations": []},
        {"kind": "affiliate", "commission_pct": 5},
        {"kind": "affiliate", "item_id": "1", "targets": ["2"], "commission_pct": 5},
    ):
        with pytest.raises(ValueError):
            S(**bad)
    assert sp.items_of(S(**DISCOUNT, targets=["1", "2"])) == ["1", "2"]
    assert multi.mode(S(**DISCOUNT, targets=["1", "2"])) == "sum"
    assert (
        multi.mode(S(kind="product_discount", item_id="1", variations=[{"discount_pct": 10}]))
        is None
    )


async def test_the_total_is_the_sum_of_the_targets_and_untick_recomputes(session, shop):
    both, by_id = await rows(session, shop, **DISCOUNT, targets=["1001", "1002"])
    assert both["targets_mode"] == "sum" and set(by_id) == {"1001", "1002"}
    assert both["fill"] == {"mode": "per_target", "targets": 2}
    assert both["title"].endswith("2 sản phẩm")
    # P98: the rows are their own results; the card is their column-wise sum (whole đồng each)
    total = sum(r["dgmv_p50"] for r in by_id.values())
    assert total == pytest.approx(both["delta"]["gmv"]["p50"], abs=2)
    alone = await one(
        session,
        shop,
        kind="product_discount",
        item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 20}],
    )
    assert by_id["1001"]["dgmv_p50"] == pytest.approx(alone["delta"]["gmv"]["p50"])
    # untick 1002: the card becomes 1001 alone
    one_left, left = await rows(session, shop, **DISCOUNT, targets=["1001"])
    assert set(left) == {"1001"}
    assert one_left["delta"]["gmv"]["p50"] == pytest.approx(alone["delta"]["gmv"]["p50"])
    assert one_left["delta"]["gmv"]["p50"] != both["delta"]["gmv"]["p50"]


async def test_a_target_without_cost_makes_the_card_profit_unknown_not_a_partial_sum(session, shop):
    both, by_id = await rows(session, shop, **DISCOUNT, targets=["1001", "1002"])
    profits = [r["dprofit_p50"] for r in by_id.values()]
    if any(p is None for p in profits):
        assert both["delta"]["profit"]["p50"] is None
    else:  # P98: every target's stored profit is known: the card is their sum, never partial
        assert both["delta"]["profit"]["p50"] == pytest.approx(sum(profits), abs=2)


async def test_a_floor_breach_is_flagged_on_its_target(session, shop):
    out, by_id = await rows(
        session, shop, kind="product_discount", discount_pct=60, targets=["1001", "1002"]
    )
    flagged = [i for i, r in by_id.items() if r["breach"]]
    assert flagged, by_id
    assert out["breach"] is True
    for i in flagged:
        assert by_id[i]["breaches"] and all(b["target"] == i for b in by_id[i]["breaches"])
        assert any(w["type"] == "floor" for w in out["warnings"])


async def test_a_target_that_cannot_be_priced_is_listed_with_its_reason(session, shop):
    out = await one(session, shop, **DISCOUNT, targets=["1001", "nope"])
    assert out["ok"]
    ids = {r["id"]: r for r in out["targets"]}
    assert ids["1001"]["ok"] and ids["nope"]["ok"] is False and ids["nope"]["refusal"]["message"]
    only_bad = await one(session, shop, **DISCOUNT, targets=["nope"])
    assert only_bad["ok"] is False


async def test_affiliate_commission_is_one_bulk_card(session, shop):
    out, by_id = await rows(
        session, shop, kind="affiliate", commission_pct=12, targets=["1001", "1002"]
    )
    assert set(by_id) == {"1001", "1002"}
    assert out["fill"] == {"mode": "bulk", "targets": 2}


async def test_a_voucher_over_a_product_list_is_one_voucher_with_a_row_per_product(session, shop):
    out = await one(
        session,
        shop,
        kind="voucher",
        scope="product",
        item_ids=["1001", "1002"],
        discount_type="amount",
        value=5000,
        min_spend=60_000,
    )
    assert out["ok"] and out["targets_mode"] == "joint"
    assert {r["id"] for r in out["targets"]} == {"1001", "1002"}
    assert out["fill"]["mode"] == "bulk" and "voucher chung" in out["targets_note"].lower()
    single = await one(
        session,
        shop,
        kind="voucher",
        scope="product",
        item_ids=["1001"],
        discount_type="amount",
        value=5000,
        min_spend=60_000,
    )
    assert "targets" not in single


async def test_choose_saves_one_card_that_carries_the_targets_and_replans_them(session, shop):
    from juli_backend.services.shopee_recommendations import plans
    from tests.unit.test_shopee_reco_plan import _USER_IDS, _actor

    _USER_IDS[shop.shop_id] = shop.user.id
    actor = manual.Actor("staff", shop.user.id, shop.user.id)
    spec = S(**DISCOUNT, targets=["1001", "1002"])
    saved = await builder.choose(
        session, shop.shop_id, [spec], 0, primary=False, acknowledge_breaches=True,
        actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    card = saved["card"]
    assert [t["id"] for t in card[targets.KEY]] == ["1001", "1002"]
    assert card["fill"] == {"mode": "per_target", "targets": 2}
    assert all(t["variant"]["change_kind"] == "product_discount" for t in card[targets.KEY])
    assert card["scope"]["product_ids"] == ["1001", "1002"]
    stored = await store.card_payload(session, shop.shop_id, __import__("uuid").UUID(saved["id"]))
    assert stored is not None and len(stored[targets.KEY]) == 2
    prop = await session.get(ShopProposal, __import__("uuid").UUID(saved["id"]))
    prop.status = "sent"
    await session.commit()
    plan = await plans.add_card(
        session, shop.shop_id, prop.id, actor=_actor(shop), now=NOW, acknowledge_breaches=True
    )
    agg = plan["aggregate"]
    assert agg["n_cards"] == 1 and {p["product_id"] for p in agg["products"]} == {"1001", "1002"}
    assert agg["cards"][0]["card_id"] == str(prop.id)
    # P98 W4-B / ADR-122 d.2: the plan reads the option result -- the same numbers the builder
    # showed for this version (the two targets' results added), per 30 days
    per30 = saved["outcome"]["result"]["per_30d"]
    assert agg["result_basis"] == "option_result"
    assert agg["dgmv_month"]["total"]["p50"] == pytest.approx(per30["gmv"], abs=1)
    # P99: the wire's Δ Đơn is at the card's precision (one decimal under 10 orders)
    # (and a whole order from 10 up, so the plan's unrounded figure sits within half an order)
    tol = 0.051 if abs(per30["orders"]) < 10 else 0.5
    assert agg["dorders_month"]["p50"] == pytest.approx(per30["orders"], abs=tol)


# ==================== ads


async def campaign(session, shop):
    camps = await builder.ads_campaigns(session, shop.shop_id, as_of=AS_OF, now=NOW)
    return camps["campaigns"][0]["campaign_key"]


async def ads(session, shop, **version):
    """P100 B.15: Ads edits are evaluated in the builder (no ``ads_edit_hidden`` any more); the
    translation checks Shopee's edit form."""
    spec = S(kind="ads", **version)
    shown = await one(session, shop, kind="ads", **version)
    assert (shown.get("refusal") or {}).get("code") != "ads_edit_hidden"
    ctx = await builder.build_context(session, shop.shop_id, [spec], as_of=AS_OF, now=NOW)
    try:
        return to_variant(spec, ctx)
    except SpecRefused as exc:
        return exc


async def test_a_budget_below_one_hundred_thousand_is_refused_with_shopees_wording(session, shop):
    key = await campaign(session, shop)
    low = await ads(session, shop, lever="budget", campaign_key=key, daily_budget=22_000)
    assert isinstance(low, SpecRefused) and low.code == "ads_budget_below_min"
    assert manual.refusal(low.code)["message"] == "Ngân sách tối thiểu: ₫100.000"
    ok = await ads(session, shop, lever="budget", campaign_key=key, daily_budget=100_000)
    assert ok.variant["change_kind"] == "ads_budget"


async def test_an_unlimited_budget_is_priced_without_an_invented_spend_rise(session, shop):
    key = await campaign(session, shop)
    v = await ads(session, shop, lever="budget", campaign_key=key, unlimited=True)
    assert v.variant["change_kind"] == "ads_budget"
    assert v.variant["inputs"]["unlimited"] is True and v.variant["inputs"]["daily_budget"] is None


def test_the_budget_lever_takes_a_budget_or_unlimited_not_both_not_neither():
    base = {"kind": "ads", "lever": "budget", "campaign_key": "c"}
    S(**base, daily_budget=100_000)
    S(**base, unlimited=True)
    for bad in ({}, {"daily_budget": 100_000, "unlimited": True}):
        with pytest.raises(ValidationError) as refused:
            S(**base, **bad)
        assert "budget" in str(refused.value)


def test_roas_is_system_or_custom_and_keywords_are_not_a_lever():
    base = {"kind": "ads", "lever": "roas", "campaign_key": "c"}
    S(**base, roas_mode="custom", roas_target=2.5)
    S(**base, roas_mode="system")
    with pytest.raises(ValidationError) as custom:
        S(**base, roas_mode="custom")
    with pytest.raises(ValidationError) as system:
        S(**base, roas_mode="system", roas_target=2.5)
    with pytest.raises(ValidationError) as keywords:
        S(kind="ads", lever="keywords", item_id="1", keywords=[{"keyword": "a", "bid": 1}])
    assert "roas" in str(custom.value) and "roas" in str(system.value)
    assert "lever" in str(keywords.value)


async def test_a_roas_above_shopees_hint_warns_and_a_preset_does_not(session, shop):
    key = await campaign(session, shop)
    high = await ads(session, shop, lever="roas", campaign_key=key, roas_target=5.0)
    hint = next(w for w in high.warnings if w["type"] == "ads_roas_above_hint")
    assert "≤ 3.5" in hint["message"]
    for preset in (2.5, 3.5):
        v = await ads(session, shop, lever="roas", campaign_key=key, roas_target=preset)
        assert not any(w["type"] == "ads_roas_above_hint" for w in v.warnings), preset
    over = await ads(session, shop, lever="roas", campaign_key=key, roas_target=4.5)
    assert any(
        w["type"] == "ads_roas_above_hint" for w in over.warnings
    )  # 4.5 is Shopee's preset yet above ≤ 3.5


async def test_the_system_roas_mode_is_a_lever_with_no_invented_target(session, shop):
    key = await campaign(session, shop)
    v = await ads(session, shop, lever="roas", campaign_key=key, roas_mode="system")
    assert v.variant["change_kind"] == "ads_roas_target"
    assert not any(w["type"] == "ads_roas_above_hint" for w in v.warnings)


async def test_a_second_roas_change_within_seven_days_warns(session, shop):
    key = await campaign(session, shop)
    first = await ads(session, shop, lever="roas", campaign_key=key, roas_target=3.0)
    assert not any(w["type"] == "ads_roas_second_change" for w in first.warnings)
    # the Connector saw the target at 2.5 three days before the window's last day, 3.0 since
    session.add(
        PlatformDailyMetric(
            shop_id=shop.shop_id,
            dataset="ads_campaign_daily",
            day=CUR_END - timedelta(days=3),
            item_id="",
            stream="ads",
            segment=key,
            order_type="placed",
            platform_source="Chiến dịch nhóm",
            impressions=Decimal(900),
            clicks=Decimal(25),
            orders=Decimal(2),
            gmv=Decimal(90_000),
            extra={"daily_budget": 30_000, "roi_two_target": 2.5, "cost": 12_000},
            confidence="high",
            **_src(),
        )
    )
    await session.commit()
    again = await ads(session, shop, lever="roas", campaign_key=key, roas_target=3.5)
    second = next(w for w in again.warnings if w["type"] == "ads_roas_second_change")
    assert "7 ngày" in second["message"] and "hỗ trợ hiệu suất" in second["message"]
    # the target has been 3.0 since long before: nothing changed in the week
    old = (
        await session.scalars(
            select(PlatformDailyMetric).where(
                PlatformDailyMetric.shop_id == shop.shop_id,
                PlatformDailyMetric.segment == key,
                PlatformDailyMetric.day == CUR_END - timedelta(days=3),
            )
        )
    ).one()
    old.day = CUR_END - timedelta(days=12)
    old.extra = {**old.extra, "roi_two_target": 3.0}
    await session.commit()
    calm = await ads(session, shop, lever="roas", campaign_key=key, roas_target=3.5)
    assert not any(w["type"] == "ads_roas_second_change" for w in calm.warnings)


async def test_many_campaigns_take_one_budget_and_the_dates_ride_on_the_version(session, shop):
    key = await campaign(session, shop)
    v = await ads(
        session, shop, lever="budget", campaign_keys=[key], daily_budget=150_000,
        start="2026-11-12", end="2026-11-18",
    )  # fmt: skip
    assert v.multi == "sum" and [t for t, _ in v.parts] == [key]


# ==================== combo

ITEMS = ["1001", "1002"]
TIERS = [{"qty": 2, "value": 5}, {"qty": 3, "value": 8}]


async def combo(session, shop, **over):
    base = {"kind": "combo", "item_ids": ITEMS, "discount_type": "pct", "tiers": TIERS}
    return await one(session, shop, **{**base, **over})


def test_tiers_read_as_shopee_words_them():
    t = bundle_tiers.Tier(2, bundle_tiers.D(5))
    assert bundle_tiers.tier_text("pct", t) == "Mua 2 sản phẩm để được giảm 5%"
    assert bundle_tiers.tier_text("amount", bundle_tiers.Tier(2, bundle_tiers.D(15000))) == (
        "Mua 2 sản phẩm để được giảm 15.000đ"
    )
    assert bundle_tiers.tier_text(
        "special_price", bundle_tiers.Tier(3, bundle_tiers.D(120000))
    ) == ("Mua 3 sản phẩm chỉ với giá 120.000đ")


async def test_a_combo_is_a_bundle_deal_over_a_product_list_with_tiers(session, shop):
    await add_baskets(session, shop)
    v = await combo(session, shop, name="Combo thử", purchase_limit=3)
    assert v["ok"] and v["change_kind"] == "bundle_deal" and v["card_kind"] == "bundle_deal"
    d = v["details"]
    assert d["products"] == 2 and [t["units"] for t in d["tiers"]] == [2, 3]
    assert d["tiers"][0]["text"] == "Mua 2 sản phẩm để được giảm 5%"
    assert all({r["item_id"] for r in t["items"]} == set(ITEMS) for t in d["tiers"])
    assert d["qualifying_orders"] > 0 and d["extra_cost_on_existing_orders"] > 0
    assert v["cost"]["amount"] >= d["extra_cost_on_existing_orders"]
    assert v["driver"]["target_metric"] == "aov" and v["break_even"]["applies"] is True
    notes = " ".join(w.get("message", "") for w in v["warnings"] if w["type"] == "note")
    assert "Giới hạn đặt hàng 3 combo" in notes  # named, not in the numbers


async def test_the_three_types_become_the_same_effective_percent_of_the_average_price(
    session, shop
):
    await add_baskets(session, shop)
    pct = await combo(session, shop, tiers=[{"qty": 2, "value": 10}])
    avg = pct["details"]["avg_unit_price"]
    amount = await combo(
        session, shop, discount_type="amount", tiers=[{"qty": 2, "value": 2 * avg * 0.1}]
    )
    special = await combo(
        session, shop, discount_type="special_price", tiers=[{"qty": 2, "value": 2 * avg * 0.9}]
    )
    for v in (amount, special):
        assert v["details"]["tiers"][0]["discount_pct"] == pytest.approx(10, abs=0.1)
    assert special["details"]["tiers"][0]["text"].startswith("Mua 2 sản phẩm chỉ với giá")


async def test_a_deep_tier_breaks_the_floor_on_its_product_and_warns(session, shop):
    await add_baskets(session, shop)
    v = await combo(session, shop, tiers=[{"qty": 2, "value": 70}])
    assert v["breach"] is True and any(w["type"] == "floor" for w in v["warnings"])
    tier = v["details"]["tiers"][0]
    assert tier["below_floor"] is True and any(r["below_floor"] for r in tier["items"])


async def test_a_product_without_orders_is_listed_but_prices_nothing(session, shop):
    refused = await combo(session, shop, item_ids=["1001", "9999"])
    assert refused["ok"] is False and refused["refusal"]["code"].startswith("item_unknown")


async def test_tiers_are_one_per_quantity_and_the_name_is_short():
    for bad in (
        {"tiers": [{"qty": 2, "value": 5}, {"qty": 2, "value": 8}]},
        {"name": "x" * 26},
        {"purchase_limit": 0},
    ):
        base = {"kind": "combo", "item_ids": ITEMS, "discount_type": "pct", "tiers": TIERS}
        with pytest.raises(ValueError) as refused:
            S(**{**base, **bad})
        assert refused.value.error_count() >= 1


async def test_a_saved_old_combo_is_marked_legacy_and_still_reads(session, shop):
    """A combo saved as a fixed basket (items x qty) keeps its kind and is marked legacy."""
    from juli_backend.services.shopee_recommendations.loader import load_env

    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    variant = {
        "label": "Combo cũ",
        "change_kind": "combo_multi",
        "items": ITEMS,
        "extra": {
            "combo_items": [{"item_id": "1001", "qty": 1}, {"item_id": "1002", "qty": 1}],
            "discount_type": "pct",
            "discount_value": 10,
        },
        "inputs": {"combo_target": "bundle_deal"},
    }
    card, why = manual.build_variant(env, variant, now=NOW)
    assert card is not None, why
    assert service.legacy_of(card)["code"] == "combo_basket"
    assert service.legacy_of({"change_kind": "bundle_deal"}) is None


async def test_the_plan_carries_a_tiers_combo_as_its_own_layer(session, shop):
    await add_baskets(session, shop)
    _USER_IDS[shop.shop_id] = shop.user.id
    actor = manual.Actor("staff", shop.user.id, shop.user.id)
    saved = await builder.choose(
        session, shop.shop_id,
        [S(kind="combo", item_ids=ITEMS, discount_type="pct", tiers=TIERS)], 0,
        primary=False, acknowledge_breaches=True, actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    prop = await session.get(ShopProposal, uuid.UUID(saved["id"]))
    prop.status = "sent"
    await session.commit()
    plan = await plans.add_card(session, shop.shop_id, prop.id, actor=_actor(shop), now=NOW)
    agg = plan["aggregate"]
    assert agg["added_cards"] == [str(prop.id)] and agg["joint_cards"] == []
    # P98 W4-B / ADR-122 d.2: the plan reads the option result the builder showed (per 30 days)
    per30 = saved["outcome"]["result"]["per_30d"]
    # P100-C (B.10): the seeded shop has too few orders to measure who moves up to a tier, so
    # the card is cost + break-even only; the plan says so instead of summing it as 0
    assert per30["gmv"] is None
    assert agg["dgmv_month"]["total"]["p50"] is None
    assert agg["dprofit_month"]["total"]["p50"] is None
    assert agg["totals_estimable"] is False
    assert agg["not_estimable_cards"] == [str(prop.id)]
    assert "chưa ước tính được" in agg["totals_note"].lower()
    # P99b: no money-layer certain figure beside the option results
    assert agg["dprofit_month"]["certain"] is None


# ==================== listing combo

LISTING = {
    "kind": "listing_combo",
    "title": "Combo găng tay + nước rửa chén",
    "price": 120_000,
    "stock": 40,
    "sku": "CB-01",
    "image_refs": ["anh-1.jpg"],
    "member_ids": ["1001", "1002"],
}


def test_the_spec_needs_two_distinct_members_a_price_and_a_stock():
    S(**LISTING)
    for bad in (
        {"member_ids": ["1001"]},
        {"member_ids": ["1001", "1001"]},
        {"price": 999},
        {"title": ""},
        {"image_refs": [f"{n}.jpg" for n in range(10)]},
        {"stock": -1},
    ):
        with pytest.raises(ValueError) as refused:
            S(**{**LISTING, **bad})
        assert refused.value.error_count() >= 1


async def test_the_estimate_comes_from_the_existing_baskets_and_states_the_assumption(
    session, shop
):
    await add_baskets(session, shop)  # four orders holding a 1001 and a 1002 line
    v = await one(session, shop, **LISTING)
    assert v["ok"] and v["change_kind"] == "listing_combo" and v["card_kind"] == "listing_combo"
    d = v["details"]
    assert d["existing_baskets"] >= 4 and "chưa có lịch sử bán" in d["assumption"]
    assert [m["item_id"] for m in d["members"]] == ["1001", "1002"]
    # P98 / ADR-122 d.7: no new orders -- the orders already holding both members switch (AOV and
    # lợi nhuận mỗi đơn change, measured from the order lines); no pack evidence for a bundle
    assert v["delta"]["orders"] == {"low": 0.0, "p50": 0.0, "high": 0.0}
    assert v["delta"]["orders_note"]
    assert "chưa có dữ liệu cho quy cách này" in v["result"]["notes"]
    gmv = v["delta"]["gmv"]
    assert gmv["low"] == gmv["p50"] == gmv["high"]
    assert v["basis"]["key"] == "measured"
    # a combo cheaper than its members lowers GMV by the basket difference
    per_basket = d["combo_price"] - d["value_now"]
    assert per_basket < 0 and gmv["p50"] < 0


async def test_without_a_basket_in_history_there_is_nothing_to_switch_and_it_says_so(session, shop):
    v = await one(session, shop, **{**LISTING, "member_ids": ["1001", "1003"]})
    assert v["ok"]
    if v["details"]["existing_baskets"] == 0:
        # P99: nothing to switch and no pack evidence: "chưa ước tính được", never an all-+0
        assert v["result"]["estimable"] is False
        assert v["delta"]["gmv"]["p50"] is None and v["delta"]["orders"]["p50"] is None
        assert any("chưa có dữ liệu cho quy cách này" in n for n in v["result"]["notes"])
        assert "Chưa có đơn nào" in v["details"]["assumption"]


async def test_a_combo_not_cheaper_than_its_members_changes_nothing(session, shop):
    await add_baskets(session, shop)
    v = await one(session, shop, **{**LISTING, "price": 900_000})
    assert v["ok"] and v["delta"]["gmv"]["p50"] == 0
    assert any("không có lý do chuyển sang combo" in w.get("message", "") for w in v["warnings"])


async def test_a_price_below_the_floor_warns_and_never_blocks(session, shop):
    await add_baskets(session, shop)
    v = await one(session, shop, **{**LISTING, "price": 50_000})
    assert v["ok"] and v["breach"] is True and any(w["type"] == "floor" for w in v["warnings"])


async def test_a_member_without_orders_is_refused(session, shop):
    v = await one(session, shop, **{**LISTING, "member_ids": ["1001", "nope"]})
    assert v["ok"] is False and v["refusal"]["code"].startswith("item_unknown")


async def test_it_is_a_card_the_plan_adds_with_its_own_layer_and_no_fill_page(session, shop):
    await add_baskets(session, shop)
    _USER_IDS[shop.shop_id] = shop.user.id
    actor = manual.Actor("staff", shop.user.id, shop.user.id)
    saved = await builder.choose(
        session, shop.shop_id, [S(**LISTING)], 0, primary=False, acknowledge_breaches=True,
        actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    card = saved["card"]
    assert card["change_kind"] == "listing_combo"
    sheet = card["execution_sheet"]
    assert (
        sheet["page"]["label"] == "Sản phẩm › Thêm sản phẩm" and sheet["page"]["verified"] is False
    )
    assert [s["field"] for s in sheet["steps"]][:2] == ["Tên listing", "Giá bán"]
    prop = await session.get(ShopProposal, uuid.UUID(saved["id"]))
    prop.status = "sent"
    await session.commit()
    plan = await plans.add_card(
        session, shop.shop_id, prop.id, actor=_actor(shop), now=NOW, acknowledge_breaches=True
    )
    agg = plan["aggregate"]
    assert agg["added_cards"] == [str(prop.id)]
    # P98 W4-B / ADR-122 d.2: the plan reads the option result the builder showed (per 30 days)
    per30 = saved["outcome"]["result"]["per_30d"]
    assert agg["dgmv_month"]["total"]["p50"] == pytest.approx(per30["gmv"], abs=1)


# P97 integration: T3's fill queue reads T4's many-target card rows (D85.13).


def test_item_rows_become_one_target_each_and_refused_rows_are_skipped() -> None:
    card = {
        "targets": [
            {"id": "11", "kind": "item"},
            {"id": "12", "kind": "item", "refusal": "below_floor"},
            {"id": "13", "kind": "item", "ok": True},
        ],
        "fill": {"mode": "per_target"},
    }
    assert _card_targets(card, "ads_edit") == [{"item_id": "11"}, {"item_id": "13"}]


def test_bulk_and_voucher_rows_become_one_product_list() -> None:
    rows = [{"id": "11", "kind": "item"}, {"id": "13", "kind": "item"}]
    assert _card_targets({"targets": rows, "fill": {"mode": "bulk"}}, "x") == [
        {"product_ids": ["11", "13"]}
    ]
    assert _card_targets({"targets": rows}, "voucher") == [{"product_ids": ["11", "13"]}]


def test_campaign_rows_carry_the_campaign_key_and_no_rows_means_the_card_scope() -> None:
    card = {"targets": [{"id": "k1", "kind": "campaign"}, {"id": "k2", "kind": "campaign"}]}
    assert _card_targets(card, "ads_edit") == [{"campaign_key": "k1"}, {"campaign_key": "k2"}]
    assert _card_targets({}, "voucher") == []


async def test_a_tiers_combo_sheet_has_only_text_steps(session, shop):
    """P100: the card page renders each step's before/after as text. The machine-readable
    `tiers` list ([{units, value}]) once became a step of its own and crashed the seller card
    (React #31 on ORY's JC-2611-0101); the "Mức ưu đãi N" lines already carry the tiers."""
    await add_baskets(session, shop)
    _USER_IDS[shop.shop_id] = shop.user.id
    actor = manual.Actor("staff", shop.user.id, shop.user.id)
    saved = await builder.choose(
        session, shop.shop_id,
        [S(kind="combo", item_ids=ITEMS, discount_type="pct", tiers=TIERS)], 0,
        primary=False, acknowledge_breaches=True, actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    sheet = saved["card"]["execution_sheet"]
    for step in sheet["steps"] + sheet["revert_steps"]:
        for side in ("before", "after"):
            assert not isinstance(step[side], (list, dict)), (step["field"], step[side])
    fields = [s["field"] for s in sheet["steps"]]
    assert "tiers" not in fields
    assert "Mức ưu đãi 1" in fields and "Mức ưu đãi 2" in fields


async def test_a_programme_price_not_below_today_is_refused_with_the_smallest_real_discount(
    session, shop
):
    """P100: %GIẢM is off Giá gốc (seed: list 100.000đ, buyers pay 90.000đ). 10% lands on today's
    price -- no discount at all -- yet the engine once modelled it as one (ORY: a deeper running
    programme made 10% a price RISE with a CTOR uplift and no cost). Refuse and name the floor."""
    v = await one(
        session, shop, kind="product_discount", item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 10}],
    )  # fmt: skip
    assert v["ok"] is False
    assert v["refusal"]["code"].startswith("discount_not_below_current:1001:90000:90000:")
    assert "90.000đ" in v["refusal"]["message"] and "11%" in v["refusal"]["message"]
    real = await one(
        session, shop, kind="product_discount", item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 20}],
    )  # fmt: skip
    assert real["ok"] is True
    assert real["cost"]["amount"] > 0  # the discount is a cost (B.11 / B.14)


async def test_the_variations_payload_names_the_price_paid_and_the_smallest_discount(session, shop):
    """P100 UI fix: the builder shows the floor before the round trip; it is the very figure
    the ``discount_not_below_current`` refusal names (list 100.000đ, buyers pay 90.000đ: 11%)."""
    out = await builder.product_variations(session, shop.shop_id, "1001", as_of=AS_OF, now=NOW)
    row = out["variations"][0]
    assert row["paid_price"] == 90_000 and row["min_discount_pct"] == 11
    refused = await one(
        session, shop, kind="product_discount", item_id="1001",
        variations=[{"variation_id": "", "discount_pct": 10}],
    )  # fmt: skip
    assert refused["refusal"]["code"].endswith(f":{row['min_discount_pct']}")
    assert all("paid_price" in r and "min_discount_pct" in r for r in out["variations"])
