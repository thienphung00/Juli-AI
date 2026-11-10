"""P99: one base, one cost, one margin across Tự tạo, the saved card and Kế hoạch.

For every family the builder offers (voucher, combo khuyến mãi, listing combo, affiliate, a new ads
campaign) the same version shows the same per-card Δ and cost in Tự tạo (``evaluate_versions``),
on the saved card ("Chọn"'s outcome) and in Kế hoạch (the plan's per-card result); a product shows
one margin on Luồng sản phẩm, the Tự tạo list, So sánh "Hôm nay" and Kế hoạch; a saved version
keeps its own days; profit per order comes from the days with costs (the metrics side's
``profit_orders`` contract). Synthetic reco shop only (SQLite, invented figures).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_analytics.matrix import product_row
from juli_backend.services.shopee_builder import ads_builder, specs_p98
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_profit import shop_profit
from juli_backend.services.shopee_recommendations import manual, plans, store
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor

ITEM = "1001"


# ------------------------------------------------------------------ profit per order (pure)


@dataclass
class _Base:
    """A FunnelBase double carrying the metrics side's P99 totals."""

    totals: dict[str, D | None]
    sources: tuple[Any, ...] = ()

    def total(self, name: str) -> D | None:
        if name not in self.totals:
            raise AttributeError(name)
        return self.totals[name]


def test_profit_per_order_divides_by_the_orders_of_the_days_with_costs():
    base = _Base({"orders": D(100), "profit": D(600_000), "profit_orders": D(60)})
    assert integrate.profit_per_order(base) == D(10_000)  # 600.000 ÷ 60, not ÷ 100


def test_profit_per_order_falls_back_to_every_order_before_the_metrics_side_lands():
    base = _Base({"orders": D(100), "profit": D(600_000)})
    assert integrate.profit_per_order(base) == D(6_000)
    assert integrate.profit_per_order(_Base({"orders": D(100), "profit": None})) is None


def test_the_card_says_on_how_many_days_the_profit_stands():
    days = (SimpleNamespace(profit_days=9, days=30), SimpleNamespace(profit_days=9, days=30))
    base = _Base({"orders": D(100), "profit": D(1), "profit_orders": D(40)}, days)
    note = integrate.profit_coverage_note(base)
    assert note is not None and "9 ngày có dữ liệu chi phí" in note and "30 ngày" in note
    full = (SimpleNamespace(profit_days=30, days=30),)
    assert integrate.profit_coverage_note(_Base({"profit": D(1)}, full)) is None
    assert integrate.profit_coverage_note(_Base({"profit": D(1)})) is None  # base does not say


# ----------------------------------------------------------------------------- the shop


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


def _staff(seeded):
    return manual.Actor("staff", seeded.user.id, seeded.user.id)


async def _save_and_plan(session, seeded, spec) -> tuple[dict[str, Any], dict[str, Any]]:
    """("Chọn"'s answer, the Kế hoạch card) of one version."""
    from juli_backend.models.shop_proposals import ShopProposal

    saved = await builder.choose(
        session, seeded.shop_id, [spec], 0, primary=False, acknowledge_breaches=True,
        actor=_staff(seeded), as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    card_id = uuid.UUID(saved["id"])
    prop = await session.get(ShopProposal, card_id)
    prop.status = "sent"
    await session.commit()
    out = await plans.add_card(
        session, seeded.shop_id, card_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    card = next(c for c in out["aggregate"]["cards"] if c["card_id"] == str(card_id))
    return saved, {**card, "_aggregate": out["aggregate"]}


VOUCHER = sp.VoucherSpec(
    kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=20_000,
    min_spend=60_000, usage_limit=50, start=AS_OF, end=AS_OF + timedelta(days=6),
)  # fmt: skip
VOUCHER_NO_DATES = sp.VoucherSpec(
    kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=20_000,
    min_spend=60_000,
)  # fmt: skip
COMBO = sp.ComboSpec(
    kind="combo", item_ids=[ITEM], discount_type="pct",
    tiers=[sp.ComboTier(qty=2, value=5), sp.ComboTier(qty=3, value=8)],
)  # fmt: skip
LISTING_COMBO = sp.ListingComboSpec(
    kind="listing_combo", title="Combo thử 1001 + 1003", price=160_000, stock=10,
    member_ids=["1001", "1003"],
)  # fmt: skip
AFFILIATE = sp.AffiliateSpec(kind="affiliate", item_id=ITEM, commission_pct=10)
ADS = sp.AdsNewSpec(
    kind="ads_new", campaign="single", item_ids=[ITEM], daily_budget=100_000, start=AS_OF,
    end=AS_OF + timedelta(days=13),
)  # fmt: skip

FAMILIES = {
    "voucher": VOUCHER,
    "combo": COMBO,
    "listing_combo": LISTING_COMBO,
    "affiliate": AFFILIATE,
    "ads_new": ADS,
}


def _plan_view(result: dict[str, Any]) -> dict[str, Any]:
    """An OptionResult's wire block as Kế hoạch states it: per 30 days."""
    k = 30 / result["days"]
    per30 = result["per_30d"]
    return {
        "estimable": result["estimable"],
        "dgmv": None if not result["estimable"] else per30["gmv"],
        "dorders": None if not result["estimable"] else pa.round_orders(per30["orders"]),
        "dprofit": None if not result["estimable"] else per30["profit"],
        "cost_month": result["cost"]["total"] * k,
        "days": result["days"],
    }


def _card_view(card: dict[str, Any]) -> dict[str, Any]:
    r = card["result"]
    p50 = (r.get("delta") or {}).get("p50") or {}
    return {
        "estimable": r["estimable"],
        "dgmv": p50.get("dgmv"),
        "dorders": p50.get("dorders"),
        "dprofit": p50.get("dprofit"),
        "cost_month": r["cost_month"],
        "days": r["days"],
    }


def _same(a: dict[str, Any], b: dict[str, Any]) -> None:
    assert a.keys() == b.keys()
    for k in a:
        if a[k] is None or b[k] is None or isinstance(a[k], bool):
            assert a[k] == b[k], k
        else:
            assert a[k] == pytest.approx(b[k], abs=1e-6), k


@pytest.mark.parametrize("family", sorted(FAMILIES))
async def test_tu_tao_the_saved_card_and_ke_hoach_show_one_result(session, shop, family):
    seeded, _ = shop
    spec = FAMILIES[family]
    compared = await builder.evaluate_versions(
        session, seeded.shop_id, [spec], as_of=AS_OF, now=NOW
    )
    tu_tao = compared["versions"][0]
    assert tu_tao["ok"], tu_tao.get("refusal")
    assert tu_tao["result"] is not None, tu_tao.get("result_refusal")  # every family has one
    saved, planned = await _save_and_plan(session, seeded, spec)
    card = saved["outcome"]["result"]
    _same(_plan_view(tu_tao["result"]), _plan_view(card))
    _same(_plan_view(card), _card_view(planned))
    agg = planned["_aggregate"]
    # one cost: Kế hoạch's cost per month is the OptionResult's, also for the cap
    assert agg["cost"]["delta_per_month"] == pytest.approx(planned["result"]["cost_month"])
    if not tu_tao["result"]["estimable"]:
        # shown as "chưa ước tính được" with its cost, left out of the sums
        assert planned["result"]["message"] == pa.NOT_ESTIMABLE_TEXT
        assert agg["not_estimable_cards"] == [planned["card_id"]]


async def test_a_listing_combo_without_evidence_is_not_estimable_never_plus_zero(session, shop):
    seeded, _ = shop
    out = await builder.evaluate_versions(
        session, seeded.shop_id, [LISTING_COMBO], as_of=AS_OF, now=NOW
    )
    r = out["versions"][0]["result"]
    if r["estimable"]:  # the seeded shop holds a 1001 + 1003 basket: switching is measured
        pytest.skip("the synthetic shop has a matching basket")
    assert r["delta"]["orders"]["value"] is None and r["delta"]["gmv"]["value"] is None
    assert any("chưa có dữ liệu cho quy cách này" in n for n in r["notes"])


async def test_an_affiliate_version_costs_commission_times_its_expected_gmv(session, shop):
    seeded, env = shop
    out = await builder.evaluate_versions(
        session, seeded.shop_id, [AFFILIATE], as_of=AS_OF, now=NOW
    )
    r = out["versions"][0]["result"]
    aff_gmv = sum(
        (ln.order_value for ln in env.lines_for([ITEM]) if ln.product_id == ITEM and ln.affiliate),
        D(0),
    )
    want = D("0.10") * aff_gmv * 30 / env.window_days
    assert r["estimable"] is False and r["kind"] == "affiliate_commission"
    assert r["cost"]["total"] == pytest.approx(float(want))
    assert r["days"] == 30 and r["horizon"] == "first_30_days"


async def test_an_ads_tab_setup_carries_the_version_that_adds_it_to_the_plan(session, shop):
    seeded, env = shop
    setup = specs_p98.AdsSetup(
        campaign="single", item_ids=[ITEM], daily_budget=100_000, start_date=AS_OF,
        end_date=AS_OF + timedelta(days=13),
    )  # fmt: skip
    out = ads_builder.assemble(env, specs_p98.AdsRequest(setups=[setup]), str(seeded.shop_id))
    row = out["setups"][0]
    spec = sp.AdsNewSpec.model_validate(row["spec"])
    assert spec == ADS
    _, planned = await _save_and_plan(session, seeded, spec)
    # the Ads tab's result is the plan card's, cost included (exact: budget × days)
    _same(_plan_view(row["result"]), _card_view(planned))
    assert planned["result"]["cost_total"] == pytest.approx(100_000 * 14)


async def test_a_saved_version_keeps_its_own_days(session, shop):
    seeded, _ = shop
    saved, planned = await _save_and_plan(session, seeded, VOUCHER)
    payload = await store.card_payload(session, seeded.shop_id, uuid.UUID(saved["id"]))
    assert payload is not None
    version = payload["versions"][0]
    assert version["spec"]["start"] == AS_OF.isoformat()
    assert version["inputs"]["days"] == 7 and planned["result"]["days"] == 7
    assert saved["outcome"]["result"]["days"] == 7
    # a voucher without dates: the version, its result and Kế hoạch all use the 30-day horizon
    saved, planned = await _save_and_plan(session, seeded, VOUCHER_NO_DATES)
    payload = await store.card_payload(session, seeded.shop_id, uuid.UUID(saved["id"]))
    assert payload is not None
    assert payload["versions"][0]["inputs"]["days"] == 30
    assert planned["result"]["days"] == 30 and planned["result"]["horizon"] == "first_30_days"


async def test_ke_hoach_adds_a_cards_delta_onto_the_base_it_was_computed_on(session, shop):
    seeded, env = shop
    _, planned = await _save_and_plan(session, seeded, COMBO)
    agg = planned["_aggregate"]
    block = next(p for p in agg["products"] if p["product_id"] == ITEM)
    base = integrate.scope_today(env, integrate.base_for(env, [ITEM]))
    # the product's "hôm nay" is the product funnel the card used, never the shop's
    assert block["today"]["scope"] == "product" and block["today"]["items"] == [ITEM]
    assert block["today"]["orders_30d"] == pytest.approx(base["orders_30d"])
    assert block["today"]["gmv_30d"] == pytest.approx(base["gmv_30d"])
    before = planned["result"]["before"]
    assert before["orders_30d"] == pytest.approx(base["orders_30d"])
    assert before["gmv_30d"] == pytest.approx(base["gmv_30d"])
    p50 = planned["result"]["delta"]["p50"]
    after = block["after"]
    assert after["gmv_30d"] == pytest.approx(base["gmv_30d"] + p50["dgmv"])
    assert after["orders_30d"] * after["aov"] == pytest.approx(after["gmv_30d"])


async def test_so_sanh_hom_nay_is_the_versions_own_scope(session, shop):
    seeded, env = shop
    out = await builder.evaluate_versions(
        session, seeded.shop_id, [VOUCHER, COMBO], as_of=AS_OF, now=NOW
    )
    today = out["today"]
    assert today["scope"] == "product" and today["items"] == [ITEM]
    assert today["mixed_scopes"] is False
    base = integrate.scope_today(env, integrate.base_for(env, [ITEM]))
    assert today["orders_30d"] == pytest.approx(base["orders_30d"])  # product next to product
    assert today["orders_30d"] < env.shop_orders_30d
    for v in out["versions"]:
        assert v["today"]["orders_30d"] == pytest.approx(base["orders_30d"])
    shop_voucher = sp.VoucherSpec(
        kind="voucher", discount_type="amount", value=10_000, min_spend=100_000
    )
    mixed = await builder.evaluate_versions(
        session, seeded.shop_id, [shop_voucher, COMBO], as_of=AS_OF, now=NOW
    )
    assert mixed["today"]["scope"] == "shop" and mixed["today"]["mixed_scopes"] is True


async def test_one_margin_on_luong_tu_tao_so_sanh_and_ke_hoach(session, shop):
    seeded, env = shop
    luong = product_row(env.view, ITEM)["profit"]["margin_pct"]
    assert luong is not None
    want = float(shop_profit.scope_margin_pct(env.view.profit, [ITEM]) or 0)
    assert luong == pytest.approx(want, abs=0.05)
    listed = await builder.products(session, seeded.shop_id, as_of=AS_OF)
    row = next(r for r in listed["products"] if r["item_id"] == ITEM)
    assert row["margin_pct"] == pytest.approx(luong, abs=0.05)  # Tự tạo list
    out = await builder.evaluate_versions(session, seeded.shop_id, [COMBO], as_of=AS_OF, now=NOW)
    assert out["today"]["margin_pct"] == pytest.approx(luong, abs=0.05)  # So sánh "Hôm nay"
    v = out["versions"][0]
    if v["margin_before_pct"] is not None:  # the version's own "hôm nay"
        assert v["margin_before_pct"] == pytest.approx(luong, abs=0.05)
    aff = await builder.evaluate_versions(
        session, seeded.shop_id, [AFFILIATE], as_of=AS_OF, now=NOW
    )
    assert aff["today"]["margin_pct"] == pytest.approx(luong, abs=0.05)  # affiliate "hôm nay"
    _, planned = await _save_and_plan(session, seeded, COMBO)
    block = next(p for p in planned["_aggregate"]["products"] if p["product_id"] == ITEM)
    assert block["today"]["margin_pct"] == pytest.approx(luong, abs=0.05)  # Kế hoạch
    first = block["steps"]["items"][0]
    if first["margin_pct_before"] is not None:
        assert first["margin_pct_before"] == pytest.approx(luong, abs=0.05)
    assert block["steps"]["total"]["margin_pct_before"] == pytest.approx(luong, abs=0.05)


def test_delta_orders_round_to_the_cards_precision():
    assert pa.round_orders(7.66) == 7.7 and pa.round_orders(-0.04) == -0.0
    assert pa.round_orders(12.4) == 12.0 and pa.round_orders(None) is None
