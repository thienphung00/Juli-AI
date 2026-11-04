"""p91 D-3: the combo calculator (pure), compare, manual save and the Ops / Demo routes.

SQLite; synthetic shops and figures only."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_profit.fees import (
    FeeBase,
    FeeComponent,
    FeeFormula,
    FeeKind,
    FeeSchedule,
)
from juli_backend.services.shopee_profit.order_profit import OrderLine, SkuCost
from juli_backend.services.shopee_profit.whatif import VoucherRule
from juli_backend.services.shopee_recommendations import combo, manual, store
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client

NOW = datetime(2026, 10, 8, 3, 0)
DEMO = "/v1/demo/shopee/recommendations"

# --------------------------------------------------------------------------- pure math

SCHEDULE = FeeSchedule(
    (
        FeeFormula(
            date(2026, 1, 1),
            (
                FeeComponent("commission", FeeKind.PCT, FeeBase.BUYER_PAID, rate=D("0.10")),
                FeeComponent("fixed", FeeKind.FIXED, amount=D(3000)),
            ),
        ),
    )
)
COSTS = {
    "A": SkuCost("A", D(40_000), D(1_000)),
    "B": SkuCost("B", D(10_000), D(1_000)),
    "C": SkuCost("C", D(5_000), D(500)),
}


def _line(item: str, price: int, qty: int, sku: str | None = None) -> OrderLine:
    return OrderLine(
        order_id="combo:o",
        sku=sku or item,
        product_id=item,
        order_date=date(2026, 10, 1),
        qty=qty,
        original_price=D(price),
        deal_price=D(price),
    )


LINES = [_line("A", 100_000, 1), _line("B", 50_000, 2)]  # 200.000đ at today's prices


def _price(offer: combo.ComboOffer, floors=None, lines=LINES):
    return combo.price_combo(lines, offer, COSTS, SCHEDULE, floors=floors)


def test_percent_combo_splits_discount_and_charges_the_per_order_fee_once():
    r = _price(combo.ComboOffer("pct", D(10)))
    assert r["combo_discount"] == 20_000 and r["buyer_pays"] == 180_000
    assert [x["combo_discount"] for x in r["lines"]] == [10_000, 10_000]
    # 10 % of 90.000 twice + the 3.000đ per-order fee ONCE (1.500 per line, not 3.000 each)
    assert r["platform_fees"] == 21_000
    assert [x["fees_share"] for x in r["lines"]] == [10_500, 10_500]
    assert r["cogs"] == 60_000 and r["packaging"] == 2_000
    assert r["contribution"] == 97_000 and r["margin_pct"] == 53.9
    # the same basket without the offer: 200.000 - 23.000 - 60.000 - 2.000
    assert r["contribution_without_offer"] == 115_000 and r["cost_per_combo_order"] == 18_000


def test_amount_and_fixed_price_discounts():
    amount = _price(combo.ComboOffer("amount", D(30_000)))
    assert amount["combo_discount"] == 30_000 and amount["buyer_pays"] == 170_000
    assert [x["combo_discount"] for x in amount["lines"]] == [15_000, 15_000]
    fixed = _price(combo.ComboOffer("fixed_price", D(150_000)))
    assert fixed["combo_discount"] == 50_000 and fixed["buyer_pays"] == 150_000
    # an amount larger than the basket is capped at the basket
    assert combo.combo_discount(combo.ComboOffer("amount", D(900_000)), D(200_000)) == 200_000


def test_discount_is_spread_by_value_with_the_remainder_on_the_last_line():
    lines = [_line("A", 100_000, 1), _line("B", 33_333, 3), _line("C", 7_001, 1)]
    r = _price(combo.ComboOffer("amount", D(10_001)), lines=lines)
    shares = [x["combo_discount"] for x in r["lines"]]
    assert sum(shares) == 10_001 and shares[0] >= shares[1] > shares[2]


def test_stacked_voucher_applies_on_the_value_after_the_combo_discount():
    voucher = VoucherRule(min_spend=D(100_000), pct=D("0.05"), max_discount=D(20_000))
    r = _price(combo.ComboOffer("pct", D(10), voucher))
    assert r["voucher_discount"] == 9_000 and r["voucher_applies"] is True
    assert r["buyer_pays"] == 171_000
    assert sum(x["voucher_share"] for x in r["lines"]) == 9_000
    high = VoucherRule(min_spend=D(190_000), amount=D(10_000))
    r2 = _price(combo.ComboOffer("pct", D(10), high))  # 180.000 < 190.000: not reached
    assert r2["voucher_discount"] == 0 and r2["voucher_applies"] is False
    assert r2["buyer_pays"] == 180_000


def test_gift_cost_comes_off_the_contribution():
    r = _price(combo.ComboOffer("pct", D(10), gift_cost=D(5_500)))
    assert r["gift_cost"] == 5_500 and r["contribution"] == 97_000 - 5_500
    assert r["cost_per_combo_order"] == 18_000 + 5_500


def test_floor_breach_is_marked_per_sku():
    r = _price(combo.ComboOffer("pct", D(10)), floors={"A": D(95_000), "B": D(20_000)})
    (breach,) = r["breaches"]
    assert breach["sku"] == "A" and breach["floor"] == 95_000 and breach["min_unit_price"] == 90_000
    assert [x["below_floor"] for x in r["lines"]] == [True, False]
    unknown = _price(combo.ComboOffer("pct", D(10)), floors={"A": D(1)})
    assert unknown["floor_unknown_skus"] == ["B"] and unknown["breaches"] == []


def test_break_even_extra_combo_orders():
    assert combo.break_even_extra_orders(10, D(18_000), D(97_000)) == (2, None)  # 180k / 97k
    assert combo.break_even_extra_orders(0, D(18_000), D(97_000)) == (0, None)
    assert combo.break_even_extra_orders(10, D(18_000), D(0)) == (None, "contribution_not_positive")


@pytest.mark.parametrize(
    ("lines", "offer", "code"),
    [
        ([_line("A", 100_000, 1)], combo.ComboOffer("pct", D(10)), "combo_needs_2_or_3_products"),
        (
            [_line("A", 1, 1, "A"), _line("A", 1, 1, "B")],
            combo.ComboOffer("pct", D(10)),
            "combo_needs_distinct_products",
        ),
        (
            [_line("A", 100_000, 21), _line("B", 1, 1)],
            combo.ComboOffer("pct", D(10)),
            "combo_qty_out_of_range",
        ),
        (LINES, combo.ComboOffer("fixed_price", D(200_000)), "combo_price_not_below_value"),
        (LINES, combo.ComboOffer("pct", D(0)), "combo_no_offer"),
        (LINES, combo.ComboOffer("pct", D(95)), "combo_discount_value_invalid"),
        (LINES, combo.ComboOffer("half", D(5)), "combo_discount_type_invalid"),
    ],
)
def test_a_combo_that_cannot_be_priced_is_refused_with_a_reason(lines, offer, code):
    with pytest.raises(combo.ComboRefusal) as exc:
        combo.price_combo(lines, offer, COSTS, SCHEDULE)
    assert exc.value.code == code and combo.refusal_text(code) != code


def test_missing_cost_is_refused_not_zero():
    with pytest.raises(combo.ComboRefusal) as exc:
        combo.price_combo(LINES, combo.ComboOffer("pct", D(10)), {"A": COSTS["A"]}, SCHEDULE)
    assert exc.value.code.startswith("cost_or_fee_unknown")


# ------------------------------------------------------------------ with the shop env


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    return seeded, env


def _combo(pct: float = 10, **extra):
    return {
        "change_kind": "combo_multi",
        "extra": {
            "combo_items": [{"item_id": "1001", "qty": 1}, {"item_id": "1002", "qty": 2}],
            "discount_type": "pct",
            "discount_value": pct,
            **extra,
        },
    }


def _discount(pct: int = 15):
    return {"change_kind": "product_discount", "items": ["1001"], "inputs": {"discount_pct": pct}}


async def test_a_combo_card_is_built_by_the_card_builder_with_the_lift_model(shop):
    _, env = shop
    card, why = manual.build_variant(env, _combo(), now=NOW)
    assert why is None and card is not None
    c = card["certain"]
    assert c["kind"] == "combo" and c["combo_multi"] is True and len(c["lines"]) == 2
    assert c["buyer_pays"] < c["value_now"] and c["cost_per_combo_order"] > 0
    assert c["aov_combo"] == c["buyer_pays"] and c["aov_shop_now"] is not None
    assert card["predicted"]["lift"]["metric"] == "aov"
    assert set(card["scope"]["product_ids"]) == {"1001", "1002"}
    assert card["title"].startswith("Combo nhiều sản phẩm — ")
    assert card["execution_sheet"]["steps"] and card["floor"]["ok"] is (not c["breaches"])


async def test_a_gift_with_unknown_cost_is_refused_with_a_clear_reason(shop):
    _, env = shop
    card, why = manual.build_variant(env, _combo(gift_item="9999"), now=NOW)
    assert card is None and why["code"] == "gift_cost_unknown" and "giá vốn" in why["message"]
    ok, _ = manual.build_variant(env, _combo(gift_item="1003"), now=NOW)
    base, _ = manual.build_variant(env, _combo(), now=NOW)
    assert ok["certain"]["gift_cost"] == 16_000  # 15.000 giá vốn + 1.000 đóng gói
    assert ok["certain"]["contribution"] == base["certain"]["contribution"] - 16_000


async def test_compare_isolates_a_refused_variant_and_computes_deltas(shop):
    _, env = shop
    bad = {"change_kind": "product_discount", "items": ["nope"], "inputs": {"discount_pct": 10}}
    out = manual.compare(env, [_discount(10), _combo(), bad, _discount(25)], now=NOW)
    assert out["saved"] is False and [v["ok"] for v in out["variants"]] == [True, True, False, True]
    assert out["variants"][2]["refusal"]["code"].startswith("item_unknown")
    assert out["variants"][2]["metrics"] is None
    a, b = out["variants"][0]["metrics"], out["variants"][1]["metrics"]
    pair = next(x for x in out["between"] if (x["from"], x["to"]) == (0, 1))
    assert pair["delta"]["dprofit_p50"] == round(b["dprofit_p50"] - a["dprofit_p50"], 4)
    assert len(out["between"]) == 3  # three valid variants -> three pairs
    assert out["today"]["aov"] and out["vs_today"][0]["delta"]["dprofit_p10"] is not None
    for key in ("dprofit_p10", "dprofit_p90", "dgmv_p50", "dorders_p50", "aov_p25", "cost_month"):
        assert key in a
    assert out["best_profit_p50"] in (0, 1, 3)


async def test_compare_needs_two_to_four_variants(shop):
    _, env = shop
    from juli_backend.services.shop_proposals import ProposalError

    with pytest.raises(ProposalError):
        manual.compare(env, [_discount()], now=NOW)
    with pytest.raises(ProposalError):
        manual.compare(env, [_discount()] * 5, now=NOW)


# ------------------------------------------------------------------------------ routes


@pytest.fixture
async def seller(session, shop):
    seeded, _ = shop
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


def _body(variants, **kw):
    return {"variants": variants, "as_of": AS_OF.isoformat(), **kw}


async def test_demo_compare_records_nothing_and_hides_model_internals(session, shop, seller):
    r = await seller.post(f"{DEMO}/compare", json=_body([_discount(), _combo()]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False and all(v["ok"] for v in body["variants"])
    assert "rank_inputs" not in body["variants"][0]["card"]
    assert (await session.scalars(select(ShopProposal))).first() is None


async def test_request_limits_are_422(session, shop, seller):
    one = await seller.post(f"{DEMO}/compare", json=_body([_discount()]))
    five = await seller.post(f"{DEMO}/compare", json=_body([_discount()] * 5))
    assert one.status_code == 422 and five.status_code == 422
    four_items = _combo()
    four_items["extra"]["combo_items"] = [{"item_id": str(n), "qty": 1} for n in range(4)]
    bad = [
        four_items,
        {**_combo(), "extra": {**_combo()["extra"], "combo_items": [{"item_id": "1", "qty": 1}]}},
        {**_combo(), "extra": {**_combo()["extra"], "discount_value": 95}},
        {
            **_combo(),
            "extra": {
                **_combo()["extra"],
                "combo_items": [{"item_id": "1001", "qty": 21}, {"item_id": "1002", "qty": 1}],
            },
        },
        {
            **_combo(),
            "extra": {
                **_combo()["extra"],
                "discount_type": "fixed_price",
                "discount_value": 5_000_000_000,
            },
        },
        _discount(150) | {"inputs": {"discount_pct": 150}},
        {"change_kind": "x" * 40},
        {**_combo(), "extra": {**_combo()["extra"], "voucher": {"value": 5, "pct": 5}}},
    ]
    for variant in bad:
        r = await seller.post(f"{DEMO}/compare", json=_body([_discount(), variant]))
        assert r.status_code == 422, variant
    over = await seller.post(f"{DEMO}/manual", json=_body([_discount()], chosen=1))
    assert over.status_code == 422


async def _events(session, shop_id, card_id, event_type=None):
    q = select(CardEvent).where(CardEvent.shop_id == shop_id, CardEvent.card_id == card_id)
    if event_type:
        q = q.where(CardEvent.event_type == event_type)
    return list((await session.scalars(q.order_by(CardEvent.occurred_at))).all())


async def test_a_seller_manual_card_runs_approve_then_done_like_any_card(session, shop, seller):
    seeded, _ = shop
    r = await seller.post(
        f"{DEMO}/manual", json=_body([_discount(), _combo()], chosen=1, primary=True)
    )
    assert r.status_code == 201, r.text
    out = r.json()
    cid = uuid.UUID(out["id"])
    assert out["origin"] == "manual" and out["status"] == "sent" and out["position"] == 1
    assert [v["index"] for v in out["versions"]] == [1, 0]  # chosen first
    assert out["versions"][0]["chosen"] is True and out["versions"][1]["chosen"] is False
    (proposed,) = await _events(session, seeded.shop_id, cid, "proposed")
    assert proposed.payload["origin"] == "manual"
    assert proposed.payload["created_by"] == {"type": "seller", "id": str(seeded.user.id)}
    assert proposed.payload["primary"] is True and len(proposed.payload["versions"]) == 2
    assert (await store.card_meta(session, seeded.shop_id, cid))["origin"] == "manual"
    # it is in the seller's list and detail
    listing = (await seller.get(DEMO)).json()
    assert [c["id"] for c in listing["cards"]] == [str(cid)]
    assert (await seller.get(f"{DEMO}/{cid}")).status_code == 200
    # approve -> Đã làm, unchanged
    ap = await seller.post(f"{DEMO}/{cid}/approve", json={})
    assert ap.status_code == 200 and ap.json()["status"] == "approved"
    done = await seller.post(f"{DEMO}/{cid}/executed", json={})
    assert done.status_code == 201, done.text
    (ex,) = await _events(session, seeded.shop_id, cid, "executed")
    assert ex.payload["change"]["change_kind"] == "combo_multi"
    assert (await session.get(ShopProposal, cid)).status == "executed"


async def test_a_breaching_manual_card_needs_the_acknowledgement(session, shop, seller):
    seeded, _ = shop
    below = _combo(pct=60)
    r = await seller.post(f"{DEMO}/manual", json=_body([below]))
    detail = r.json()["detail"]
    assert r.status_code == 422 and detail["code"] == "reco_breach_not_acknowledged"
    assert detail["breaches"] and detail["breaches"][0]["type"] == "floor"
    await session.refresh(seeded.shop)  # a refusing route rolls back
    await session.refresh(seeded.user)
    assert (await session.scalars(select(ShopProposal))).first() is None
    ok = await seller.post(f"{DEMO}/manual", json=_body([below], acknowledge_breaches=True))
    assert ok.status_code == 201, ok.text
    cid = uuid.UUID(ok.json()["id"])
    (proposed,) = await _events(session, seeded.shop_id, cid, "proposed")
    ack = proposed.payload["acknowledged_breaches"]
    assert ack["by"] == {"type": "seller", "id": str(seeded.user.id)} and ack["at"]
    assert ack["breaches"] == [b for b in ack["breaches"] if b["type"] in ("floor", "spend_cap")]
    assert ack["breaches"] and proposed.payload["floor"]["ok"] is False


async def test_an_unbuildable_manual_card_is_refused(session, shop, seller):
    bad = {"change_kind": "product_discount", "items": ["nope"], "inputs": {"discount_pct": 5}}
    r2 = await seller.post(f"{DEMO}/manual", json=_body([bad], acknowledge_breaches=True))
    assert r2.status_code == 422 and r2.json()["detail"]["code"] == "reco_manual_invalid"


async def test_ops_compare_is_viewer_and_manual_is_operator_and_audited(session, shop, monkeypatch):
    seeded, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        ok = await client.post(f"{base}/compare", json=_body([_discount(), _combo()]))
        assert ok.status_code == 200 and "rank_inputs" in ok.json()["variants"][0]["card"]
        denied = await client.post(f"{base}/manual", json=_body([_discount()]))
        assert denied.status_code == 403
    viewer.dependency_overrides.clear()
    assert (await session.scalars(select(OpsAuditLog))).first() is None
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        r = await client.post(f"{base}/manual", json=_body([_combo(), _discount()], primary=False))
        assert r.status_code == 201, r.text
    operator.dependency_overrides.clear()
    out = r.json()
    cid = uuid.UUID(out["id"])
    assert out["status"] == "draft" and out["position"] == manual.DEFAULT_MANUAL_POSITION
    (row,) = (await session.scalars(select(OpsAuditLog))).all()
    assert row.action == "reco_manual_create" and row.after["card_id"] == out["id"]
    p = await session.get(ShopProposal, cid)
    assert p.proposed_by_staff_id is not None
    (proposed,) = await _events(session, seeded.shop_id, cid, "proposed")
    assert proposed.payload["created_by"]["type"] == "staff"
