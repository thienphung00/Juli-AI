"""P98 W4-B / ADR-122 d.2, d.5: the Kế hoạch aggregate reads the same numbers as each option's
result. The plan's Δ is the sum of its cards' ``OptionResult`` Δ (P50 exact, range by the root sum
of squares of the half-widths), an unknown profit stays unknown, a card without a result is
"chưa ước tính được" and counts only for its cost, and the "after" funnel keeps the identity.
Pure tests on hand-made results first, then the synthetic reco shop (SQLite, invented figures)."""

from __future__ import annotations

import math
import uuid
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.engine.contract import OptionResult, Scenario
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_builder.service import variation_rows_for
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from juli_backend.services.shopee_recommendations import plans
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_manual import _discount
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, VOUCHER, _actor, _manual


def col(orders, gmv, profit, views=None, clicks=None):
    return Scenario(
        views=None if views is None else D(views),
        clicks=None if clicks is None else D(clicks),
        orders=D(orders),
        gmv=D(gmv),
        profit=None if profit is None else D(profit),
        offer_cost=D(0),
    )


def result(
    d_gmv, d_orders, d_profit, *, lo=None, hi=None, days=30, cost=0, views=None, estimable=True
):
    """A result whose before is 100 đơn / 10.000.000 / 2.000.000 and whose likely is that + Δ."""
    before = col(100, 10_000_000, 2_000_000, 5000, 400)
    lo = d_profit if lo is None else lo
    hi = d_profit if hi is None else hi

    def at(g, o, p):
        return col(
            100 + o,
            10_000_000 + g,
            None if p is None else 2_000_000 + p,
            None if views is None else 5000 + views,
            None if views is None else 400 + views / 10,
        )

    return OptionResult(
        kind="x",
        label="x",
        days=days,
        horizon="duration",
        drivers=("ctor",),
        estimable=estimable,
        basis="measured",
        before=before,
        low=at(d_gmv * 0.5, d_orders * 0.5, lo) if estimable else None,
        likely=at(d_gmv, d_orders, d_profit) if estimable else None,
        high=at(d_gmv * 1.5, d_orders * 1.5, hi) if estimable else None,
        build_up=(),
        cost_total=D(cost),
        break_even_orders=None,
        break_even_aov=None,
    )


def cr(card_id, **kw):
    return pa.CardResult(card_id, result(**kw))


# ------------------------------------------------------------------------------- pure


def test_p50_adds_exactly_and_the_range_is_the_root_sum_of_squares():
    a = cr("a", d_gmv=300_000, d_orders=6, d_profit=90_000, lo=40_000, hi=150_000)
    b = cr("b", d_gmv=100_000, d_orders=2, d_profit=-20_000, lo=-50_000, hi=10_000)
    t = pa.combine_results([a, b])
    assert t["p50"]["dprofit"] == 70_000 and t["p50"]["dgmv"] == 400_000
    assert t["p50"]["dorders"] == 8
    # half-widths below: 50.000 and 30.000; above: 60.000 and 30.000
    assert t["p10"]["dprofit"] == pytest.approx(70_000 - math.hypot(50_000, 30_000))
    assert t["p90"]["dprofit"] == pytest.approx(70_000 + math.hypot(60_000, 30_000))
    # joint range: narrower than the sum of the ranges, wider than the widest one
    assert 50_000 < 70_000 - t["p10"]["dprofit"] < 80_000


H = pa.Horizon(__import__("datetime").date(2026, 11, 10))


def test_a_card_counts_its_own_days_inside_the_30_day_horizon_never_scaled_to_30():
    """P99b: a 60-day card counts its 30 days inside the horizon; a 15-day card its 15 days --
    its Δ for those days, not ×30/15."""
    long = cr("a", d_gmv=300_000, d_orders=6, d_profit=90_000, days=60)
    assert long.delta("likely", H)["dprofit"] == pytest.approx(45_000)
    assert long.delta_own("likely")["dprofit"] == pytest.approx(90_000)  # Tự tạo's figure
    short = cr("b", d_gmv=0, d_orders=0, d_profit=10_000, days=15, cost=30_000)
    assert short.counted_days(H) == 15 and short.cost_in(H) == pytest.approx(30_000)
    t = pa.combine_results([long, short], H)
    assert t["p50"]["dprofit"] == pytest.approx(45_000 + 10_000)


def test_a_card_partly_outside_the_horizon_counts_only_the_days_inside():
    td = __import__("datetime").timedelta
    late = pa.CardResult(
        "a", result(70_000, 7, 14_000, days=7, cost=7_000), start=H.end - td(days=2)
    )
    assert late.counted_days(H) == 3
    assert late.delta("likely", H)["dgmv"] == pytest.approx(30_000)
    assert late.cost_in(H) == pytest.approx(3_000)
    gone = pa.CardResult("b", result(70_000, 7, 14_000, days=7, cost=7_000), start=H.end + td(1))
    assert gone.counted(H) is None and gone.counted_days(H) == 0
    assert gone.cost_in(H) == 0 and gone.delta("likely", H)["dgmv"] == 0
    past = pa.CardResult("c", result(70_000, 7, 14_000, days=7), start=H.start - td(days=10))
    assert past.counted(H) is None


def test_a_card_without_a_result_has_an_unknown_cost_never_a_number():
    refused = pa.CardResult("b", None, "no_spec")
    assert refused.cost_in(H) is None and refused.cost_own() is None


def test_an_unknown_profit_stays_unknown_never_a_partial_sum():
    known = cr("a", d_gmv=300_000, d_orders=6, d_profit=90_000)
    unknown = cr("b", d_gmv=100_000, d_orders=2, d_profit=None)
    t = pa.combine_results([known, unknown])
    assert [t[q]["dprofit"] for q in ("p10", "p50", "p90")] == [None, None, None]
    assert t["p50"]["dgmv"] == 400_000 and t["p50"]["dorders"] == 8  # GMV and đơn are known


def test_a_card_without_a_result_is_left_out_of_the_sums():
    ok = cr("a", d_gmv=300_000, d_orders=6, d_profit=90_000)
    refused = pa.CardResult("b", None, "no_spec")
    weak = pa.CardResult("c", result(0, 0, 0, estimable=False), "not_estimable")
    assert not refused.ok and not weak.ok
    assert pa.combine_results([ok, refused, weak]) == pa.combine_results([ok])
    none = pa.combine_results([refused, weak])
    assert none["p50"] == {m: 0.0 for m in pa.RESULT_METRICS}


def test_the_after_funnel_keeps_the_identity():
    t = pa.combine_results(
        [
            cr("a", d_gmv=300_000, d_orders=6, d_profit=90_000, views=600),
            cr("b", d_gmv=100_000, d_orders=2, d_profit=5_000, views=200),
        ]
    )
    today = {
        "gmv_30d": 4_000_000.0,
        "orders_30d": 70,
        "views_30d": 15_400,
        "clicks_30d": 980,
        "profit_30d": 1_000_000.0,
    }
    after = pa.after_funnel(today, t)
    assert after["orders_30d"] == 78 and after["gmv_30d"] == 4_400_000
    assert after["views_30d"] * after["ctr"] * after["ctor"] == pytest.approx(after["orders_30d"])
    assert after["orders_30d"] * after["aov"] == pytest.approx(after["gmv_30d"])
    assert after["profit_30d"] == 1_000_000 + 95_000


def test_the_after_funnel_is_unknown_where_todays_traffic_is():
    t = pa.combine_results([cr("a", d_gmv=1_000, d_orders=1, d_profit=1)])
    after = pa.after_funnel({"gmv_30d": 1.0, "orders_30d": 10, "profit_30d": None}, t)
    assert after["views_30d"] is None and after["ctr"] is None and after["ctor"] is None
    assert after["orders_30d"] == 11 and after["profit_30d"] is None


# ------------------------------------------------------------------- the synthetic reco shop


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


async def _plan_of(session, seeded, env, *variants):
    out = None
    for n, v in enumerate(variants):
        cid = uuid.UUID((await _manual(session, seeded, env, v))["id"])
        out = await plans.add_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)
    assert out is not None
    return out["aggregate"]


async def _period(session, seeded, env, spec):
    """The builder's Δ over the version's own days (P99b: what Tự tạo shows) and its days."""
    ctx = BuilderContext(
        env=env, variations=await variation_rows_for(session, seeded.shop_id, env, ["1001"])
    )
    done, _ = integrate.evaluate(ctx, spec)
    r = done.result_json()
    d = r["delta"]
    return {
        "profit": d["profit"]["value"],
        "gmv": d["gmv"]["value"],
        "orders": d["orders"]["value"],
        "days": r["days"],
    }


DISCOUNT = sp.ProductDiscountSpec(
    kind="product_discount",
    item_id="1001",
    variations=[sp.VariationPrice(variation_id="", discount_pct=15)],
)
VOUCHER_SPEC = sp.VoucherSpec(
    kind="voucher",
    scope="product",
    item_ids=["1001"],
    discount_type="amount",
    value=20_000,
    min_spend=60_000,
    usage_limit=50,
    # the plan rebuilds a candidate voucher's dates from today (the horizon's first day)
    start=NOW.date(),
    end=NOW.date() + __import__("datetime").timedelta(days=13),
)


async def test_the_plan_delta_is_the_sum_of_its_cards_result_delta(session, shop):
    seeded, env = shop
    agg = await _plan_of(session, seeded, env, _discount(15), VOUCHER)
    assert agg["result_basis"] == "option_result" and agg["not_estimable_cards"] == []
    d = await _period(session, seeded, env, DISCOUNT)
    v = await _period(session, seeded, env, VOUCHER_SPEC)
    # both lie wholly inside the 30 days from today: each counts its full own-days Δ
    assert (d["days"], v["days"]) == (30, 14)
    for key, got in (
        ("profit", agg["dprofit_month"]["total"]["p50"]),
        ("gmv", agg["dgmv_month"]["total"]["p50"]),
        ("orders", agg["dorders_month"]["p50"]),
    ):
        # P99: the wire's Δ Đơn is at the card's precision (one decimal under 10 orders)
        assert got == pytest.approx(d[key] + v[key], abs=0.11 if key == "orders" else 1)
    assert [c["result"]["counted"] for c in agg["cards"]] == [True, True]
    assert agg["deltas_p50"]["gmv"] == pytest.approx(agg["dgmv_month"]["total"]["p50"])


async def test_the_plans_after_keeps_the_funnel_identity(session, shop):
    seeded, env = shop
    agg = await _plan_of(session, seeded, env, _discount(15), VOUCHER)
    a, t = agg["after"], agg["today"]
    assert t["views_30d"] and t["clicks_30d"]
    assert a["views_30d"] * a["ctr"] * a["ctor"] == pytest.approx(a["orders_30d"])
    assert a["orders_30d"] * a["aov"] == pytest.approx(a["gmv_30d"])
    assert a["gmv_30d"] == pytest.approx(t["gmv_30d"] + agg["dgmv_month"]["total"]["p50"])
    assert a["orders_30d"] == pytest.approx(t["orders_30d"] + agg["dorders_month"]["p50"])


async def test_a_card_that_is_not_estimable_counts_for_its_cost_only(session, shop, monkeypatch):
    seeded, env = shop
    only_discount = await _plan_of(session, seeded, env, _discount(15))
    real = pa.spec_of_candidate

    def no_voucher_spec(cand, *a, **k):  # the voucher cannot be rebuilt: no result
        return None if cand.kind == "min_spend_voucher" else real(cand, *a, **k)

    monkeypatch.setattr(pa, "spec_of_candidate", no_voucher_spec)
    both = (await plans.get_plan(session, seeded.shop_id, now=NOW))["aggregate"]
    cid = uuid.UUID((await _manual(session, seeded, env, VOUCHER))["id"])
    out = await plans.add_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)
    both = out["aggregate"]
    by = {c["change_kind"]: c for c in both["cards"]}
    assert by["min_spend_voucher"]["result"]["estimable"] is False
    assert by["min_spend_voucher"]["result"]["message"] == "chưa ước tính được"
    assert by["min_spend_voucher"]["result"]["delta"] is None
    assert both["not_estimable_cards"] == [str(cid)]
    # left out of the sums ...
    for key in ("dprofit_month", "dgmv_month"):
        assert both[key]["total"]["p50"] == pytest.approx(only_discount[key]["total"]["p50"])
    assert both["dorders_month"]["p50"] == pytest.approx(only_discount["dorders_month"]["p50"])
    # ... and with no result its cost is unknown: listed, never the money layer's figure (P99b)
    assert by["min_spend_voucher"]["result"]["cost_horizon"] is None
    assert by["min_spend_voucher"]["result"]["cost_known"] is False
    assert both["cost"]["cost_unknown_cards"] == [str(cid)]
    assert both["cost"]["cost_complete"] is False and both["cost"]["cost_note"]
    assert both["cost"]["delta_per_month"] == pytest.approx(
        only_discount["cost"]["delta_per_month"]
    )
    assert both["totals_partial"] is True and "chưa ước tính được" in both["totals_note"]


async def test_a_plan_with_no_estimable_card_still_answers(session, shop, monkeypatch):
    seeded, env = shop
    monkeypatch.setattr(pa, "spec_of_candidate", lambda *a, **k: None)
    agg = await _plan_of(session, seeded, env, _discount(15))
    assert agg["not_estimable_cards"] == [agg["cards"][0]["card_id"]]
    # P100-C (B.10): no estimable card -> the plan's Δ is unknown, never the empty sum's 0
    assert agg["dprofit_month"]["total"]["p50"] is None
    assert agg["dgmv_month"]["total"]["p50"] is None
    assert agg["after"]["gmv_30d"] is None
    assert agg["totals_estimable"] is False
    assert agg["totals_partial"] is True and "Chưa ước tính được" in agg["totals_note"]


GIFT_SPEC = sp.GiftSpec(
    kind="gift",
    gift=sp.GiftItem(unit_cost=5_000),
    trigger=sp.GiftTrigger(type="min_spend", amount=60_000),
)


async def test_a_chosen_version_keeps_its_spec_so_every_kind_gets_a_result(session, shop):
    """A card the candidate cannot be turned back into (a gift) still gets its result in the plan:
    "Chọn" stores the builder spec on each version and the plan reads it back as it is."""
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_recommendations import manual, store

    seeded, env = shop
    actor = manual.Actor("staff", seeded.user.id, seeded.user.id)
    saved = await builder.choose(
        session, seeded.shop_id, [GIFT_SPEC, DISCOUNT], 0, primary=False,
        acknowledge_breaches=True, actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    payload = await store.card_payload(session, seeded.shop_id, uuid.UUID(saved["id"]))
    assert payload is not None
    assert [v.get("spec") for v in payload["versions"]] == [
        sp.as_json(GIFT_SPEC),
        sp.as_json(DISCOUNT),
    ]
    agg = await _plan_of_saved(session, seeded, uuid.UUID(saved["id"]))
    card = agg["cards"][0]
    assert card["result"]["counted"] is True, card["result"].get("reason")
    assert agg["not_estimable_cards"] == []
    per30 = saved["outcome"]["result"]["per_30d"]
    assert agg["dgmv_month"]["total"]["p50"] == pytest.approx(per30["gmv"], abs=1)


async def _plan_of_saved(session, seeded, card_id):
    from juli_backend.models.shop_proposals import ShopProposal

    prop = await session.get(ShopProposal, card_id)
    prop.status = "sent"
    await session.commit()
    out = await plans.add_card(
        session, seeded.shop_id, card_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    return out["aggregate"]


TITLE_SPEC = sp.TitleSpec(
    kind="title",
    item_id="1001",
    title="Găng tay tự hủy sinh học STAHAUS, găng tay dùng một lần, găng tay nitrile y tế",
)


async def test_a_keyword_rich_title_card_is_estimable_in_the_plan(session, shop):
    """4f64e2e5: a title lift is scored against the product's keyword volumes, so the plan loads
    them too -- a saved title version is not "chưa ước tính được" in Kế hoạch."""
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_recommendations import manual
    from tests.unit.test_shopee_builder_drafts import _market

    seeded, env = shop
    await _market(session, seeded.shop_id)
    await session.commit()
    actor = manual.Actor("staff", seeded.user.id, seeded.user.id)
    saved = await builder.choose(
        session, seeded.shop_id, [TITLE_SPEC], 0, primary=False,
        acknowledge_breaches=True, actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    agg = await _plan_of_saved(session, seeded, uuid.UUID(saved["id"]))
    card = agg["cards"][0]
    assert card["result"]["counted"] is True, card["result"].get("reason")
    assert agg["not_estimable_cards"] == []
