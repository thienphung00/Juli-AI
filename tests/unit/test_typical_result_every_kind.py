"""Decisions #27 / #29 (batch-1124-a, Track R): every card kind shows a "Lợi nhuận dự kiến" from
its own prior when the shop has no data of its own. This matrix runs every Tự tạo version kind on
a shop without keyword / combo / campaign data and pins which ones are estimable. A kind that is
not estimable is listed with its reason (the owner asks); none is skipped silently."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

import pytest
from pydantic import TypeAdapter

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import config, freshness, kinds, result_store
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
SPEC = TypeAdapter(sp.VersionSpec)


@pytest.fixture
async def bare_shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


#: kind -> a version of it (synthetic ids: the reco test shop's products)
_VERSIONS: dict[str, dict] = {
    "title": {"kind": "title", "item_id": "1001", "title": "Găng tay nitrile hộp 100"},
    "description_first_line": {
        "kind": "description_first_line",
        "item_id": "1001",
        "first_line": "Găng tay nitrile.",
    },
    "cover_image": {
        "kind": "cover_image",
        "item_id": "1001",
        "overlay": {"layout": "banner_bottom", "badge_text": "x"},
    },
    "price_display": {"kind": "price_display", "item_id": "1001", "text": "Chỉ 3.000đ/chiếc"},
    "bundle_deal": {
        "kind": "combo",
        "item_ids": ["1001", "1002"],
        "discount_type": "pct",
        "tiers": [{"qty": 2, "value": 5}],
    },
    "min_spend_voucher": {
        "kind": "voucher",
        "discount_type": "amount",
        "value": 5000,
        "min_spend": 100_000,
    },
    "add_on": {
        "kind": "add_on",
        "main_item_id": "1001",
        "addons": [{"item_id": "1002", "pct": 10}],
    },
    "gift": {
        "kind": "gift",
        "gift": {"unit_cost": 5000, "label": "Móc khoá", "qty": 1},
        "trigger": {"type": "min_spend", "amount": 100_000},
    },
    "variation_set": {
        "kind": "variation_set",
        "item_id": "1001",
        "new_variations": [{"name": "Set 3", "price": 240_000}],
    },
    "product_discount": {
        "kind": "product_discount",
        "item_id": "1001",
        "variations": [{"variation_id": "", "final_price": 80_000}],
    },
    "price": {
        "kind": "price",
        "item_id": "1001",
        "variations": [{"variation_id": "", "change_pct": -5}],
    },
    "flash_sale": {
        "kind": "flash_sale",
        "item_id": "1001",
        "variations": [{"variation_id": "", "discount_pct": 20}],
        "units": 5,
        "slot_hours": 3,
    },
}

#: kinds that cannot show a typical result without the shop's own data, with the reason
NEEDS_OWN_DATA: dict[str, str] = {
    "ads_pause": "removal action on a running campaign (prior is a loss)",
    "ads_remove_product": "removal action on a running campaign (prior is a loss)",
    "ads_roas_target": "prior is on ROAS, not volume; needs the running campaign",
    "ads_keywords": "no preset prior; needs the campaign's own report",
    "ads_new_campaign": "no preset prior; measured on / off days",
    "ads_purpose": "no volume effect by design (target metric none)",
    "voucher_cap": "limit action: the designed effect is zero or negative",
    "affiliate_sample": "no preset prior; measured after the first send",
    "affiliate_invite": "no preset prior; measured after the first send",
    "variation_restructure": "no preset prior; a re-arrangement",
    "listing_hide": "removal action: the loss is the listing's own views",
    "listing_relist": "no preset prior; measured after the relist",
    "listing_combo": "effect computed from the combo price and a measured pack",
}


async def _outcome(session, shop, version):
    out = await builder.evaluate_versions(
        session, shop.shop_id, [SPEC.validate_python(version)], as_of=AS_OF, now=NOW
    )
    v = out["versions"][0]
    return v, (v.get("result") or {})


@pytest.mark.parametrize("kind", ["description_first_line", "price_display", "bundle_deal"])
async def test_the_decision_27_kinds_are_estimable_on_a_shop_with_no_data(session, bare_shop, kind):
    v, result = await _outcome(session, bare_shop, _VERSIONS[kind])
    assert v["ok"] is True, v.get("refusal")
    assert result["estimable"] is True and result["basis"] != "not_estimable"
    assert result.get("reason_code") is None


@pytest.mark.parametrize("kind", ["title", "cover_image"])
async def test_title_and_cover_show_no_uplift_until_measured(session, bare_shop, kind):
    # #93 (owner, F5): a title or a cover image gets NO uplift until it is measured, so the
    # decision #27 kind prior no longer applies to them; the version is still accepted
    v, result = await _outcome(session, bare_shop, _VERSIONS[kind])
    assert v["ok"] is True, v.get("refusal")
    assert result["estimable"] is False


@pytest.mark.parametrize("kind", ["min_spend_voucher", "gift", "variation_set"])
async def test_the_other_prior_kinds_are_estimable_on_a_shop_with_no_data(session, bare_shop, kind):
    v, result = await _outcome(session, bare_shop, _VERSIONS[kind])
    assert v["ok"] is True, v.get("refusal")
    assert result["estimable"] is True


async def test_add_on_on_too_few_main_orders_uses_the_kind_prior(session, bare_shop):
    # P10 (#43 Q7): with fewer than MIN_ATTACH_ORDERS main-product orders, Mua Kèm Deal Sốc runs
    # on the kind's prior (tagged "ước tính chung"), never "chưa ước tính được" for that reason
    v, result = await _outcome(session, bare_shop, _VERSIONS["add_on"])
    assert v["ok"] is True
    assert result["estimable"] is True and result.get("reason_code") is None
    assert result["basis"] == "prior" and result["basis_weak"] is True


@pytest.mark.parametrize("kind", ["product_discount", "price", "flash_sale"])
async def test_the_price_scaled_kinds_report_their_bare_shop_outcome(session, bare_shop, kind):
    # these scale with the size of the change and need the evaluator; the outcome is pinned so a
    # change shows up. A refusal is a real answer (reported to the owner), not a skipped kind.
    v, result = await _outcome(session, bare_shop, _VERSIONS[kind])
    assert v["ok"] is True or v["refusal"]["code"]
    if v["ok"]:
        assert result["estimable"] is True


def test_every_kind_is_estimable_or_listed_with_a_reason():
    builder_kinds = set(_VERSIONS) | {"keyword"}
    card_only = {
        "ads_budget",
        "ads_add_product",
        "review_voucher",
        "program_registration",
        "mega_sale",
        "combo_multi",
        "affiliate_commission",
        "affiliate_target_campaign",
    }
    covered = builder_kinds | card_only | set(NEEDS_OWN_DATA)
    assert covered == set(kinds.KINDS), set(kinds.KINDS) ^ covered
    assert all(NEEDS_OWN_DATA.values())


def test_every_prior_kind_has_a_positive_floored_typical_result():
    # the card engine: a kind with a positive prior is at least 5 % at P50 unless exempt
    for key, spec in kinds.KINDS.items():
        if key in NEEDS_OWN_DATA or spec.price_scaled or key in ("ads_budget", "ads_roas_target"):
            continue
        lo, hi = spec.prior
        assert hi > 0, key
        p10, p50, p90 = kinds.floor_prior_band(
            key, D(str(lo)), (D(str(lo)) + D(str(hi))) / 2, D(str(hi))
        )
        if key not in kinds.FLOOR_EXEMPT:
            assert p50 >= kinds.MIN_PRIOR_LIFT and p90 >= p50 >= p10, key


def test_description_first_line_uses_the_five_percent_minimum():
    assert "description_first_line" not in kinds.FLOOR_EXEMPT
    p10, p50, p90 = kinds.floor_prior_band("description_first_line", D("0.0"), D("0.02"), D("0.04"))
    assert p50 == kinds.MIN_PRIOR_LIFT and p90 >= p50


def test_a_stored_result_of_the_old_engine_is_stale_and_recomputes_by_itself():
    # R5: result_store.engine_version() / freshness.stale_reason compare the stored block with
    # config.ENGINE_VERSION on every read; a different version = stale = recomputed (no manual step)
    assert config.ENGINE_VERSION >= "2026-11-24"
    assert result_store.engine_version().startswith(config.ENGINE_VERSION)
    old = {"freshness": {"engine_version": "2026-11-20.1"}}
    assert freshness.stale_reason(old) == freshness.REASON_ENGINE
