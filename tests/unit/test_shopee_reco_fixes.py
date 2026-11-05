"""Voucher versions, units, freshness and the builder bugs of the 2026-11-05 sweep.

Synthetic shop (tests/support/shopee_reco): every figure is invented.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select

from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services import shopee_reco_refresh
from juli_backend.services.shopee_builder import catalogue, reference, response
from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.variations import observed_skus, variation_rows
from juli_backend.services.shopee_profit.income import LineIncome
from juli_backend.services.shopee_profit.order_profit import OrderLine
from juli_backend.services.shopee_recommendations import (
    config,
    freshness,
    manual,
    service,
    stale,
    store,
    versions,
)
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.voucher_notes import same_result_notes
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    return seeded, env


def voucher(env, **over):
    inputs = {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14}
    inputs.update(over)
    card = build_card(
        env, Candidate("min_spend_voucher", ("1001",), inputs, wiring_key="aov"), now=NOW
    )
    assert card is not None
    return card


# ------------------------------------------------------------------ voucher versions (issue 2)


async def test_quantity_alone_changes_nothing_while_it_does_not_bind_and_says_why(shop):
    _, env = shop
    a, b = voucher(env, quantity=500), voucher(env, quantity=1000)
    assert not a["certain"]["voucher_detail"]["usage"]["capped"]
    assert a["certain"]["extra_cost"] == b["certain"]["extra_cost"]
    notes = same_result_notes(a, b)
    assert len(notes) == 1 and "không đổi kết quả" in notes[0] and "chưa chạm giới hạn" in notes[0]


async def test_quantity_changes_the_outcome_once_it_binds(shop):
    _, env = shop
    uses = voucher(env, quantity=10_000)["certain"]["voucher_detail"]["usage"]["expected_uses"]
    tight = voucher(env, quantity=max(int(uses // 3), 1))
    loose = voucher(env, quantity=10_000)
    d = tight["certain"]["voucher_detail"]["usage"]
    assert d["capped"] is True and d["used"] < uses
    assert tight["certain"]["extra_cost"] < loose["certain"]["extra_cost"]
    assert same_result_notes(tight, loose) == []


async def test_a_binding_limit_also_caps_the_extra_orders_the_voucher_can_bring(shop):
    _, env = shop
    tight = voucher(env, quantity=1)
    assert tight["certain"]["voucher_detail"]["usage"]["headroom"] == 0
    p50 = tight["predicted"]["money_per_month"]["predicted"]["p50"]
    assert p50["dgmv"] == 0  # no use left for an extra order


async def test_days_change_the_period_totals_not_the_per_day_flows(shop):
    _, env = shop
    short, long_ = voucher(env, days=3), voucher(env, days=14)
    ps = short["predicted"]["money_per_month"]["period"]
    pl = long_["predicted"]["money_per_month"]["period"]
    assert ps["days"] == 3 and pl["days"] == 14
    assert abs(pl["certain"]["dchi"]) > abs(ps["certain"]["dchi"])
    assert short["certain"]["voucher_cost_scenario"] < long_["certain"]["voucher_cost_scenario"]
    for card in (short, long_):
        m = card["predicted"]["money_per_month"]
        n = m["period"]["days"]
        assert m["per_day"]["certain"]["dchi"] * n == pytest.approx(m["period"]["certain"]["dchi"])
        assert m["per_day"]["total"]["p50"]["dgmv"] * n == pytest.approx(
            m["period"]["total"]["p50"]["dgmv"]
        )


async def test_min_spend_changes_the_qualifying_orders(shop):
    _, env = shop
    low, high = voucher(env, min_spend=1_000), voucher(env, min_spend=10_000_000)
    assert low["certain"]["qualifying_orders"] > high["certain"]["qualifying_orders"] == 0
    assert low["certain"]["voucher_cost_scenario"] > high["certain"]["voucher_cost_scenario"]


async def test_max_discount_binds_for_a_percent_voucher_and_is_named(shop):
    _, env = shop
    capped = voucher(env, pct=50, value=None, max_value=1000, min_spend=0)
    free = voucher(env, pct=50, value=None, max_value=10_000_000, min_spend=0)
    c, f = (
        capped["certain"]["voucher_detail"]["max_discount"],
        free["certain"]["voucher_detail"]["max_discount"],
    )
    assert c["binding_orders"] > 0 and c["binding_share"] > 0 and f["binding_orders"] == 0
    assert capped["certain"]["extra_cost"] < free["certain"]["extra_cost"]
    other = voucher(env, pct=50, value=None, max_value=20_000_000, min_spend=0)
    assert any("mức giảm tối đa" in n.lower() for n in same_result_notes(free, other))


async def test_per_user_limit_is_reported_as_not_counted(shop):
    _, env = shop
    card = voucher(env, per_user_limit=1)
    pu = card["certain"]["voucher_detail"]["per_user"]
    assert pu == {"limit": 1, "status": "not_enforceable", "enforced": False}
    notes = same_result_notes(voucher(env), card)
    assert notes and "người mua" in notes[0]


async def test_builder_inputs_reach_the_evaluator_under_the_keys_it_reads():
    from juli_backend.services.shopee_builder import specs as sp
    from juli_backend.services.shopee_builder.translate import to_variant

    spec = sp.VoucherSpec.model_validate(
        {
            "kind": "voucher",
            "scope": "product",
            "item_ids": ["1001"],
            "discount_type": "pct",
            "value": 10,
            "min_spend": 99_000,
            "max_value": 20_000,
            "usage_limit": 20,
            "per_buyer_limit": 2,
            "start": "2026-10-10",
            "end": "2026-10-12",
        }
    )
    ctx = SimpleNamespace(env=SimpleNamespace(), rows=lambda i: [])
    inputs = to_variant(spec, ctx).variant["inputs"]
    assert inputs == {
        "min_spend": 99_000,
        "pct": 10,
        "max_value": 20_000,
        "quantity": 20,
        "per_user_limit": 2,
        "days": 3,
    }


async def test_compare_names_why_two_versions_are_equal(shop):
    _, env = shop
    out = manual.compare(
        env,
        [
            {"change_kind": "min_spend_voucher", "items": ["1001"],
             "inputs": {"value": 3000, "min_spend": 90_000, "quantity": 500, "days": 14}},
            {"change_kind": "min_spend_voucher", "items": ["1001"],
             "inputs": {"value": 3000, "min_spend": 90_000, "quantity": 900, "days": 14}},
        ],
        now=NOW,
    )  # fmt: skip
    assert out["between"][0]["notes"] and "không đổi kết quả" in out["between"][0]["notes"][0]
    m = out["variants"][0]["metrics"]
    assert m["period_days"] == 14 and m["usage_limit"] == 500 and m["usage_capped"] is False


# ------------------------------------------------------------------------- units


async def test_money_comes_per_day_per_order_and_over_the_period_with_orders_and_aov(shop):
    _, env = shop
    m = voucher(env, days=5)["predicted"]["money_per_month"]
    assert set(m) >= {"period", "per_day", "per_order", "orders", "aov"}
    assert m["per_order"]["basis"] == "voucher_use" and m["per_order"]["orders_in_period"] > 0
    assert m["per_order"]["certain"]["cost"] > 0
    o = m["orders"]
    assert o["base_per_day"] > 0 and o["total"]["p50"]["changes"] is False  # an AOV lever
    assert o["total"]["p50"]["per_day"] == pytest.approx(o["base_per_day"])
    a = m["aov"]
    assert a["base"] and a["total"]["p10"] <= a["total"]["p90"]


# ----------------------------------------------------------------------- freshness


async def test_cards_and_versions_carry_a_freshness_stamp(shop):
    _, env = shop
    card = voucher(env)
    f = card["freshness"]
    assert f["engine_version"] == config.ENGINE_VERSION and f["inputs_fingerprint"]
    assert f["as_of"] == AS_OF.isoformat() and f["computed_at"]
    assert freshness.card_stale_reason(card, env) is None
    cand = Candidate("min_spend_voucher", ("1001",), dict(card["inputs"]), wiring_key="aov")
    vs = versions.build_versions(env, cand, card, now=NOW)
    assert all("freshness" in v for v in vs)


async def test_a_cost_change_or_a_new_engine_version_makes_the_card_stale(
    session, shop, monkeypatch
):
    seeded, env = shop
    card = voucher(env)
    row = await session.scalar(
        select(ShopRule).where(ShopRule.shop_id == seeded.shop_id, ShopRule.rule_key == "sku_cost")
    )
    row.value = 99_000
    await session.commit()
    env2 = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert freshness.card_stale_reason(card, env2) == freshness.REASON_INPUTS
    monkeypatch.setattr(config, "ENGINE_VERSION", "next")
    assert freshness.card_stale_reason(card) == freshness.REASON_ENGINE


async def test_a_moved_data_anchor_alone_does_not_make_a_card_stale(session, shop):
    """V3 moves the anchor to the newest synced day; the fingerprint is taken over the card's own
    stored as_of (7-day order window), so a later anchor with the same orders is still fresh."""
    from datetime import timedelta

    seeded, env = shop
    card = voucher(env)
    later = await load_env(session, seeded.shop_id, as_of=AS_OF + timedelta(days=2))
    assert later is not None and later.as_of != env.as_of
    assert freshness.card_stale_reason(card, later) is None


async def _saved_voucher(session, seeded, env):
    card = voucher(env)
    card["versions"] = versions.build_versions(
        env, Candidate("min_spend_voucher", ("1001",), dict(card["inputs"]), wiring_key="aov"),
        card, now=NOW,
    )  # fmt: skip
    card["rank"] = {"position": 1, "score": 1.0, "detail": {}, "mode": "x", "explore": False}
    cid = await store.save_card(session, seeded.shop_id, card, cycle="2026-10", position=1, now=NOW)
    await service.publish(session, seeded.shop_id, None, now=NOW)
    await session.commit()
    return cid


async def test_changing_a_cost_recomputes_the_card_and_a_second_run_changes_nothing(session, shop):
    seeded, env = shop
    cid = await _saved_voucher(session, seeded, env)
    before = await store.card_payload(session, seeded.shop_id, cid)
    first = await shopee_reco_refresh.refresh_shop(session, seeded.shop_id, now=NOW)
    assert first["flagged"] == 0 and first["stale"] == 0  # nothing changed: nothing recomputed
    for r in (
        await session.scalars(
            select(ShopRule).where(
                ShopRule.shop_id == seeded.shop_id, ShopRule.rule_key == "sku_cost"
            )
        )
    ).all():
        r.value = 90_000
    await session.commit()
    second = await shopee_reco_refresh.refresh_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert second["flagged"] == 1 and second["revised"] == 1
    cards = (
        await session.scalars(select(ShopProposal).where(ShopProposal.shop_id == seeded.shop_id))
    ).all()
    live = [p for p in cards if p.status == "sent"]
    assert len(live) == 1 and live[0].id != cid  # re-sent, never left as a draft
    after = await store.card_payload(session, seeded.shop_id, live[0].id)
    assert after["certain"]["organic"] != before["certain"]["organic"]
    assert after["freshness"]["inputs_fingerprint"] != before["freshness"]["inputs_fingerprint"]
    third = await shopee_reco_refresh.refresh_shop(session, seeded.shop_id, now=NOW)
    assert third["flagged"] == 0 and third.get("revised", 0) == 0


async def test_bumping_the_engine_version_marks_every_card_stale_and_the_refresh_clears_it(
    session, shop, monkeypatch
):
    seeded, env = shop
    cid = await _saved_voucher(session, seeded, env)
    monkeypatch.setattr(config, "ENGINE_VERSION", "2099-01-01.1")
    detail = await service.card_detail(session, seeded.shop_id, cid, audience="seller")
    assert detail["stale"] is True and detail["stale_reason"] == freshness.REASON_ENGINE
    out = await shopee_reco_refresh.refresh_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert out["flagged"] == 1 and out["revised"] == 1
    live = (
        await session.scalars(
            select(ShopProposal).where(
                ShopProposal.shop_id == seeded.shop_id, ShopProposal.status == "sent"
            )
        )
    ).all()
    assert len(live) == 1
    d2 = await service.card_detail(session, seeded.shop_id, live[0].id, audience="seller")
    assert d2["stale"] is False and d2["engine_version"] == "2099-01-01.1" and d2["computed_at"]
    assert out == {**out} and stale.OPEN


async def test_a_manual_card_keeps_its_variants_through_a_refresh(session, shop, monkeypatch):
    seeded, env = shop
    variants = [
        {"label": "A", "change_kind": "min_spend_voucher", "items": ["1001"],
         "inputs": {"value": 3000, "min_spend": 90_000, "quantity": 30, "days": 7}},
        {"label": "B", "change_kind": "min_spend_voucher", "items": ["1001"],
         "inputs": {"value": 6000, "min_spend": 150_000, "quantity": 40, "days": 9}},
    ]  # fmt: skip
    actor = manual.Actor("seller", seeded.user.id)
    made = await manual.create_manual(
        session,
        seeded.shop_id,
        variants,
        0,
        False,
        actor,
        now=NOW,
        env=env,
        acknowledge_breaches=True,
    )
    await session.commit()
    monkeypatch.setattr(config, "ENGINE_VERSION", "v-next")
    await shopee_reco_refresh.refresh_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    live = (
        await session.scalars(
            select(ShopProposal).where(
                ShopProposal.shop_id == seeded.shop_id, ShopProposal.status == "sent"
            )
        )
    ).all()
    card = await store.card_payload(session, seeded.shop_id, live[0].id)
    assert [v["inputs"]["value"] for v in card["versions"]] == [3000, 6000]
    assert [v["inputs"]["days"] for v in card["versions"]] == [7, 9]
    assert all(v["freshness"]["engine_version"] == "v-next" for v in card["versions"])
    assert made["id"]


# -------------------------------------------------------------- builder bugs (2026-11-05)


def _line(**over):
    base = dict(
        order_id="o1", sku="G500001×3", product_id="26107129526", order_date=AS_OF, qty=1,
        original_price=Decimal(300_000), deal_price=Decimal(300_000), affiliate=True,
    )  # fmt: skip
    base.update(over)
    return OrderLine(**base)


def test_bug2_an_affiliate_line_keeps_its_commission_when_the_formula_replaces_the_fees():
    income = LineIncome(
        fees=(("phi", Decimal(10_000)),), commission=Decimal(12_000), net_shipping=Decimal(0),
        return_shipping=Decimal(0), refund=Decimal(0), compensation=Decimal(0),
        tax_withheld=Decimal(0), seller_coin=Decimal(0), trade_in=Decimal(0), payout=None,
    )  # fmt: skip
    formula = SimpleNamespace(formula_on=lambda d: object())
    env = RecoEnv(
        ctx=None,
        view=SimpleNamespace(
            pairs=[(_line(income=income), None)], fees=SimpleNamespace(schedule=lambda i: formula)
        ),
        as_of=AS_OF,
    )
    (out,) = env.lines_for(None)
    assert out.income is None and out.actual_fees is None
    assert out.commission == Decimal(12_000)  # profit no longer "unknown" on affiliate lines


def _sl(item, scope, base, cost_key=None):
    return SimpleNamespace(
        product_id=item,
        scope=scope,
        variation_id=scope.partition(":")[2],
        base_key=base,
        cost_key=cost_key or base,
        ordered_on=AS_OF,
    )


def test_bug3_5_variation_rows_take_the_sku_text_of_the_order_lines():
    seen = observed_skus(
        [
            _sl("100", "100:1", "G500001"),
            _sl("100", "100:2", "G500002"),
            _sl("77", "77:9", "HAE-01"),
        ]
    )
    assert seen["100"] == {"1": "G500001", "2": "G500002"}
    info = SimpleNamespace(
        list_price=None, current_price=None, seller_sku=None,
        variations=[SimpleNamespace(variation_id="1", name="Combo 3", seller_sku=None),
                    SimpleNamespace(variation_id="2", name="Combo 5", seller_sku=None)],
    )  # fmt: skip
    rules = SimpleNamespace(
        sku_cost={"G500001": Decimal(10_000), "G500002": Decimal(10_000)},
        product_cost={}, packaging_by_key={}, pack_components={}, pack_count={},
        vat_rate={}, prices_include_vat=None, cost_includes_vat=None,
    )  # fmt: skip
    rows = variation_rows(
        "100", info, [], rules=rules, schedule=SimpleNamespace(formula_on=lambda d: None),
        on=AS_OF, item_list_price=Decimal(100_000), item_current_price=Decimal(90_000),
        observed=seen["100"],
    )  # fmt: skip
    assert [r["sku_key"] for r in rows] == ["G500001×3", "G500002×5"]
    assert all(r["has_cost"] for r in rows)
    # a single-model listing (Hae): the model has no SKU in the catalogue, its lines do
    one = SimpleNamespace(
        list_price=None, current_price=None, seller_sku=None,
        variations=[SimpleNamespace(variation_id="177", name=None, seller_sku=None)],
    )  # fmt: skip
    rules.sku_cost["HAE-01"] = Decimal(5_000)
    (row,) = variation_rows(
        "77", one, [], rules=rules, schedule=SimpleNamespace(formula_on=lambda d: None),
        on=AS_OF, item_list_price=Decimal(50_000), item_current_price=Decimal(50_000),
        observed={"": "HAE-01"},  # older lines, stored before the model was named
    )  # fmt: skip
    assert row["sku_key"] == "HAE-01" and row["has_cost"]
    ctx = BuilderContext(env=cast(Any, None), variations={"77": [row]})
    assert ctx.sku_key("77", "") == "HAE-01"  # "no variation named" = its only model
    assert ctx.variation("77", "")["sku_key"] == "HAE-01"


def test_bug3_picker_checks_the_cost_by_the_order_line_sku():
    rules = SimpleNamespace(
        sku_cost={"G500001": Decimal(10_000)}, product_cost={}, packaging_by_key={},
        pack_components={}, pack_count={}, vat_rate={}, prices_include_vat=None,
        cost_includes_vat=None,
    )  # fmt: skip
    info = SimpleNamespace(
        seller_sku=None,
        variations=[SimpleNamespace(variation_id="1", name="Combo 3", seller_sku=None)],
    )
    ctx = SimpleNamespace(rules=rules, catalog=SimpleNamespace(items={"100": info}))
    assert catalogue._item_has_cost(ctx, "100") == (False, 0, 1)
    assert catalogue._item_has_cost(ctx, "100", {"1": "G500001"}) == (True, 1, 1)


def test_bug4_the_price_response_uses_the_days_the_export_covers():
    from datetime import date

    w0, w1 = date(2026, 8, 8), date(2026, 11, 5)
    assert response.covered_span((date(2026, 8, 20), date(2026, 11, 5)), w0, w1) == (
        date(2026, 8, 20),
        w1,
    )
    assert response.covered_span((date(2026, 1, 1), date(2026, 12, 31)), w0, w1) == (w0, w1)
    assert response.covered_span(None, w0, w1) is None
    assert response.covered_span((date(2025, 1, 1), date(2025, 2, 1)), w0, w1) is None


def test_bug9_unmatched_order_lines_are_not_a_product():
    view = SimpleNamespace(
        pairs=[
            (_line(product_id="sku:unknown", order_id="o9"), None),
            (_line(product_id="100", order_id="o1"), None),
        ],
        data=SimpleNamespace(product_flows=None, lines=None),
        lines=[], excluded={}, names={}, window=SimpleNamespace(json=lambda: {}),
    )  # fmt: skip
    info = SimpleNamespace(
        status="active", current_price=None, list_price=None, stock=1, variations=[], seller_sku="X"
    )
    ctx = SimpleNamespace(
        rules=SimpleNamespace(
            sku_cost={}, product_cost={}, packaging_by_key={}, pack_components={}, pack_count={},
            vat_rate={}, prices_include_vat=None, cost_includes_vat=None,
        ),
        catalog=SimpleNamespace(items={"100": info}, name=lambda i: i),
    )  # fmt: skip
    import juli_backend.services.shopee_builder.catalogue as cat

    orig = cat.product_totals_for
    cat.product_totals_for = lambda *_: {}
    try:
        out = cat.picker(ctx, view, AS_OF)
    finally:
        cat.product_totals_for = orig
    assert [p["item_id"] for p in out["products"]] == ["100"]
    assert out["unmatched_orders"] == 1 and out["unmatched_label"] == "Đơn chưa khớp sản phẩm"


async def test_bug6_7_a_listing_with_no_orders_gets_a_reference_order_and_insufficient_basis(shop):
    _, env = shop
    gone = "9999"
    rows = {
        gone: [
            {"variation_id": "", "name": "Mặc định", "sku": "Z9", "sku_key": "Z9",
             "list_price": 100_000, "selling_price": 90_000}
        ]
    }  # fmt: skip
    env.ctx.rules.sku_cost["Z9"] = Decimal(30_000)
    env.ctx.rules.packaging_by_key["Z9"] = Decimal(1_000)
    assert reference.zero_order_items(env, [gone, "1001"]) == [gone]
    ref_env, done = reference.with_reference_lines(env, rows, [gone, "1001"])
    assert done == {gone} and ref_env is not env
    assert gone not in {
        ln.product_id for ln, _ in env.view.pairs
    }  # the shop's own env is untouched
    assert gone in ref_env.item_ids()
    # a discount on it is no longer refused for want of orders
    card, why = manual.build_variant(
        ref_env,
        {"change_kind": "product_discount", "items": [gone],
         "inputs": {
             "discount_pct": 10, "days": 7,
             "variations": [{"sku": "Z9", "discount_pct": 10}],
         }},
        now=NOW,
    )  # fmt: skip
    assert why is None and card is not None


async def test_bug6_hide_and_relist_need_no_orders(shop):
    _, env = shop
    known_item = next(iter(env.ctx.catalog.items), None)
    assert known_item is not None
    # the gate counts the catalogue, not only the order lines
    assert known_item in {*env.item_ids(), *env.ctx.catalog.items, *env.view.active_items}


async def test_bug8_real_campaigns_are_listed_beside_the_pseudo_one(shop):
    from juli_backend.services.shopee_builder.service import _stored_campaigns

    _, env = shop
    out = _stored_campaigns(env, {"daily"}, {"Tổng chi quảng cáo"})
    names = {c["name"] for c in out}
    assert names and "Tổng chi quảng cáo" not in names
    assert all(c["campaign_key"] not in {"daily"} for c in out)


# ------------------------------------------------------------ V8: imported done rows measure


async def test_v8_imported_done_rows_still_approved_are_executed_at_their_date_once(session, shop):
    from juli_backend.models.planned_changes import PlannedChangeRef
    from juli_backend.models.shop_proposals import ShopProposalExecution
    from juli_backend.services import planned_changes as pc
    from tests.unit.test_planned_changes import _plan_file

    seeded, _ = shop
    actor = pc.Actor("seller", user_id=seeded.user.id)
    await pc.apply_import(
        session,
        seeded.shop_id,
        _plan_file(),
        actor=actor,
        reason="Kế hoạch",
        now=datetime(2026, 10, 20, 3),
    )
    ref = await session.scalar(
        select(PlannedChangeRef).where(PlannedChangeRef.external_ref == "MT1")
    )
    p = await session.get(ShopProposal, ref.card_id)
    assert p.status == "approved"  # imported before the importer executed done rows
    ref.state = {"decision": "approve", "status": "done", "executed_on": "2026-10-15"}
    await session.commit()
    first = await pc.backfill_executed(session, seeded.shop_id, now=datetime(2026, 10, 21, 3))
    await session.commit()
    assert first["executed"] == 1
    assert p.status == "executed"
    ex = await session.scalar(
        select(ShopProposalExecution).where(ShopProposalExecution.proposal_id == p.id)
    )
    assert ex.executed_at == datetime(2026, 10, 15, 0, 0)
    again = await pc.backfill_executed(session, seeded.shop_id, now=datetime(2026, 10, 21, 3))
    assert again["executed"] == 0  # idempotent


# ------------------------------------------------------------- V13: no unsent drafts


async def test_v13_xem_nhu_shop_never_lists_an_unsent_draft(session, shop):
    seeded, env = shop
    cid = await _saved_voucher(session, seeded, env)
    p = await session.get(ShopProposal, cid)
    p.status = "draft"  # an Ops manual draft, not sent to the shop
    await session.commit()
    ops = await service.list_cards(session, seeded.shop_id, audience="ops", queue="all")
    seller = await service.list_cards(session, seeded.shop_id, audience="seller", queue="all")
    assert [c["id"] for c in ops["cards"]] == [str(cid)] and seller["cards"] == []
    with pytest.raises(Exception) as hidden:
        await service.card_detail(session, seeded.shop_id, cid, audience="seller")
    assert getattr(hidden.value, "status", None) == 404
