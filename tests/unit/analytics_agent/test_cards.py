"""E5: card stage gates, Jev choices, engine values, overlap."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from juli_backend.services.analytics_agent import cards
from juli_backend.services.analytics_agent.chains import ChainResult, run_chain
from juli_backend.services.analytics_agent.labels import shopee_labels
from juli_backend.services.analytics_agent.types import TEMPLATE_BY_KEY
from tests.unit.analytics_agent.fakes import (
    AS_OF,
    FakeCardEngine,
    FakeData,
    FakeJev,
    engine_card,
    funnel_data,
    shop_rows,
)

L = shopee_labels()
PRESET = "last_7d_vs_prev_7d"


def nl(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def ch(pick: str, p: float = 0.95, second: str = "z") -> dict[str, Any]:
    return {"type": "choice", "choice": pick, "probabilities": {pick: p, second: round(1 - p, 4)}}


def jev_ok(
    kind: str = "product_discount",
    product: str | None = "p1",
    overlap: float = 0.1,
    version: str = "Vừa",
) -> FakeJev:
    def f(state: dict[str, Any], qs: dict[str, Any]) -> dict[str, Any]:
        out = {
            "actionable": nl(0.9),
            "kind": ch(kind),
            "overlap": nl(overlap),
            "version": ch(version),
        }
        if product:
            out["product"] = ch(product)
        return out

    return FakeJev(f)


async def explained_chain(with_product: bool = True) -> tuple[FakeData, ChainResult]:
    shop, srcs = funnel_data()
    prods = (
        [
            {
                "day": d,
                "item_id": "p1",
                "gmv": 5000.0 if d <= AS_OF - timedelta(days=7) else 1000.0,
                "orders": 5.0 if d <= AS_OF - timedelta(days=7) else 1.0,
                "units": 1.0,
            }
            for d in (r["day"] for r in shop)
        ]
        if with_product
        else []
    )
    d = FakeData(shop, srcs, products=prods, names={"p1": "Sản phẩm A", "p2": "Sản phẩm B"})
    return d, await run_chain(d, "orders_change", "orders", PRESET, AS_OF)


async def test_accepted_card_uses_engine_values_and_jev_recommended_version() -> None:
    d, c = await explained_chain()
    jev = jev_ok()
    eng = FakeCardEngine()
    out = await cards.card_stage(chains=[c], data=d, engine=eng, jev=jev, labels=L, as_of=AS_OF)
    ev = out.events[0]
    assert (
        ev["type"] == "card"
        and ev["draft_ref"].startswith("d_")
        and ev["kind"] == "product_discount"
    )
    assert ev["kind_vi"] == "Giảm giá sản phẩm" and ev["item_name"] == "Sản phẩm A"
    assert eng.calls == [("product_discount", "p1")]
    by = {v["label_vi"]: v for v in ev["versions"]}
    assert by["Vừa"]["recommended"] and not by["Nhẹ"]["recommended"]
    assert (
        by["Vừa"]["gmv_p50"] == 2_000_000.0
        and by["Vừa"]["profit_p50"] == 300_000.0
        and by["Vừa"]["days"] == 14
    )
    assert by["Vừa"]["margin_before_pct"] == 30.0 and by["Vừa"]["gmv_dir"] == "up"
    assert (
        by["Mạnh"]["estimable"] is False
        and by["Mạnh"]["cost_text_vi"] == "Chưa đủ dữ liệu"
        and not by["Mạnh"]["recommended"]
    )
    assert out.accepted[0]["engine_card"]["title"] == engine_card()["title"]


async def test_unestimable_pick_is_never_recommended() -> None:
    d, c = await explained_chain()
    out = await cards.card_stage(
        chains=[c],
        data=d,
        engine=FakeCardEngine(),
        jev=jev_ok(version="Mạnh"),
        labels=L,
        as_of=AS_OF,
    )
    rec = [v for v in out.events[0]["versions"] if v["recommended"]]
    assert [v["label_vi"] for v in rec] == ["Vừa"]


async def test_kinds_offered_are_wired_to_the_driver_with_funnel_factors_expanded() -> None:
    d, c = await explained_chain()
    jev = jev_ok()
    await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev, labels=L, as_of=AS_OF
    )
    offered = set(jev.calls[0][1]["kind"]["criteria"])
    assert {
        "title",
        "cover_image",
        "product_discount",
        "min_spend_voucher",
    } <= offered  # views + ctr + ctor kinds
    assert "bundle_deal" not in offered  # aov is not an orders factor
    assert (
        jev.calls[0][0]["findings"]["metric"] == "orders"
        and "events" in jev.calls[0][0]["findings"]
    )


async def test_g1_blocks_within_noise_and_stock_only_events() -> None:
    d, c = await explained_chain()
    c.stop_reason = "within_noise"
    out = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(), labels=L, as_of=AS_OF
    )
    assert out.events == [{"type": "no_card", "reason_vi": cards.NO_CARD_VI["within_noise"]}]
    c.stop_reason, c.events = "unexplained", [{"kind": "stock_out", "items": ["x"], "count": 1}]
    assert (
        await cards.card_stage(
            chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(), labels=L, as_of=AS_OF
        )
    ).events[0]["type"] == "no_card"
    c.events = [{"kind": "ads_spend_drop", "day": "2026-10-24"}]  # unexplained + actionable event
    assert (
        await cards.card_stage(
            chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(), labels=L, as_of=AS_OF
        )
    ).events[0]["type"] == "card"


async def test_g2_wiring_rejects_a_kind_outside_the_driver() -> None:
    d, c = await explained_chain()
    out = await cards.card_stage(
        chains=[c],
        data=d,
        engine=FakeCardEngine(),
        jev=jev_ok(kind="bundle_deal"),
        labels=L,
        as_of=AS_OF,
    )
    assert out.events[0]["type"] == "no_card" and out.gates["G2"] is False


async def test_g5_only_products_in_the_findings_are_offered_and_targeted() -> None:
    d, c = await explained_chain()
    items, metrics = cards.evidence(c)
    assert items == {"p1"} and {"orders", "views", "ctr", "ctor"} <= metrics
    jev = jev_ok(product="p2")  # Jev is only offered p1 (the product in the findings)
    eng = FakeCardEngine()
    await cards.card_stage(chains=[c], data=d, engine=eng, jev=jev, labels=L, as_of=AS_OF)
    assert eng.calls == [("product_discount", "p1")] and "product" not in jev.calls[0][1]
    d2, c2 = await explained_chain(with_product=False)
    eng2 = FakeCardEngine({"ok": False, "reason": "kind_needs_a_product"})
    out = await cards.card_stage(
        chains=[c2], data=d2, engine=eng2, jev=jev_ok(), labels=L, as_of=AS_OF
    )
    assert eng2.calls == [] and out.events[0]["type"] == "no_card"  # D: nothing fillable


async def test_g3_engine_refusal_gives_a_reason_not_a_card() -> None:
    d, c = await explained_chain()
    out = await cards.card_stage(
        chains=[c],
        data=d,
        engine=FakeCardEngine({"ok": False, "reason": "generator_returned_none"}),
        jev=jev_ok(),
        labels=L,
        as_of=AS_OF,
    )
    assert out.events[0]["type"] == "no_card" and "giá sàn" in out.events[0]["reason_vi"]


async def test_g4_exact_overlap_links_the_existing_card_then_jev_overlap() -> None:
    d, c = await explained_chain()
    d.cards = [
        {
            "kind": "product_discount",
            "item_id": "p1",
            "status": "executed",
            "code": "JC-0007",
            "change_after": "x",
        }
    ]
    out = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(), labels=L, as_of=AS_OF
    )
    assert out.events == [
        {
            "type": "no_card",
            "reason_vi": "Đã có thẻ đang làm việc này.",
            "existing_card_code": "JC-0007",
        }
    ]
    d.cards = [
        {"kind": "voucher_cap", "item_id": "p1", "status": "sent", "change_after": "y"}
    ]  # not exact: ask Jev
    blocked = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(overlap=0.8), labels=L, as_of=AS_OF
    )
    assert blocked.events[0]["type"] == "no_card"
    flagged = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev_ok(overlap=0.5), labels=L, as_of=AS_OF
    )
    assert flagged.events[0]["type"] == "card"
    assert any(r["step"] == "overlap" for r in flagged.routing)


async def test_no_actionable_question_is_asked_and_g1_is_the_only_eligibility_gate() -> None:
    d, c = await explained_chain()
    jev = FakeJev(
        lambda s, q: {"kind": ch("product_discount"), "overlap": nl(0.1), "version": ch("Vừa")}
    )
    out = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev, labels=L, as_of=AS_OF
    )
    assert out.events[0]["type"] == "card"
    assert all("actionable" not in q for _, q in jev.calls)


def jev_kind(kind_answer: dict[str, Any]) -> FakeJev:
    return FakeJev(
        lambda s, q: {
            "kind": kind_answer,
            "product": ch("p1"),
            "overlap": nl(0.1),
            "version": ch("Vừa"),
        }
    )


async def test_unsure_kind_tries_the_top_two_in_order_and_drafts_the_first_that_passes() -> None:
    d, c = await explained_chain()
    unsure = {
        "type": "choice",
        "choice": "title",
        "probabilities": {"title": 0.5, "product_discount": 0.4, "price": 0.1},
    }
    eng = FakeCardEngine(per_kind={"title": {"ok": False, "reason": "generator_returned_none"}})
    out = await cards.card_stage(
        chains=[c], data=d, engine=eng, jev=jev_kind(unsure), labels=L, as_of=AS_OF
    )
    assert eng.calls == [("title", "p1"), ("product_discount", "p1")]
    assert [e["type"] for e in out.events] == ["card"] and out.events[0][
        "kind"
    ] == "product_discount"
    assert len(out.accepted) == 1
    variant = next(r for r in out.routing if r["step"] == "card_choice")
    assert (
        variant["variant"] == "A+C+D"
        and variant["mode"] == "top2"
        and variant["candidates"] == ["title", "product_discount"]
    )
    assert [r["passed"] for r in out.routing if r["step"] == "card_try"] == [False, True]


async def test_unsure_kind_never_drafts_more_than_one_card() -> None:
    d, c = await explained_chain()
    unsure = {
        "type": "choice",
        "choice": "title",
        "probabilities": {"title": 0.5, "product_discount": 0.5},
    }
    eng = FakeCardEngine()
    out = await cards.card_stage(
        chains=[c], data=d, engine=eng, jev=jev_kind(unsure), labels=L, as_of=AS_OF
    )
    assert eng.calls == [("title", "p1")] and len(out.accepted) == 1 and len(out.events) == 1


async def test_unsure_kind_both_refused_gives_one_no_card() -> None:
    d, c = await explained_chain()
    unsure = {
        "type": "choice",
        "choice": "title",
        "probabilities": {"title": 0.5, "product_discount": 0.5},
    }
    eng = FakeCardEngine({"ok": False, "reason": "generator_returned_none"})
    out = await cards.card_stage(
        chains=[c], data=d, engine=eng, jev=jev_kind(unsure), labels=L, as_of=AS_OF
    )
    assert len(eng.calls) == 2 and [e["type"] for e in out.events] == ["no_card"]
    assert "giá sàn" in out.events[0]["reason_vi"]


async def test_clear_kind_is_taken_without_trying_a_second() -> None:
    d, c = await explained_chain()
    eng = FakeCardEngine({"ok": False, "reason": "generator_returned_none"})
    out = await cards.card_stage(
        chains=[c], data=d, engine=eng, jev=jev_ok(), labels=L, as_of=AS_OF
    )
    assert eng.calls == [("product_discount", "p1")] and out.events[0]["type"] == "no_card"


async def test_no_product_offers_only_kinds_whose_generator_needs_no_item() -> None:
    from tests.unit.analytics_agent.test_chains import _ov

    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF, orders=5.0)
    d = FakeData(shop, overview=_ov(60.0, 100.0, 1000.0, 1000.0))
    c = await run_chain(d, "profit_change", "profit", PRESET, AS_OF)
    assert c.stop_reason == "explained" and not cards.evidence(c)[0]  # no product in the findings
    jev = FakeJev(
        lambda s, q: {"kind": ch("voucher_cap"), "overlap": nl(0.1), "version": ch("Vừa")}
    )
    eng = FakeCardEngine()
    out = await cards.card_stage(chains=[c], data=d, engine=eng, jev=jev, labels=L, as_of=AS_OF)
    assert set(jev.calls[0][1]["kind"]["criteria"]) == {
        "voucher_cap"
    }  # price / ads kinds need an item
    assert eng.calls == [("voucher_cap", None)] and out.events[0]["type"] == "card"


async def test_no_product_and_no_item_free_kind_means_no_card_without_asking_jev() -> None:
    d, c = await explained_chain(with_product=False)  # orders: every kind needs an item
    jev = jev_ok()
    out = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev, labels=L, as_of=AS_OF
    )
    assert out.events[0]["type"] == "no_card" and not jev.calls


async def test_template_allows_card_at_any_stop_targeting_the_biggest_critical_gap() -> None:
    shop = shop_rows(
        AS_OF - timedelta(days=40), AS_OF, orders=5.0, views=1000, clicks=100, gmv=500.0
    )
    d = FakeData(
        shop,
        names={"p9": "Sản phẩm Z"},
        critical={
            "items": [
                {
                    "product_id": "p9",
                    "at_stake_per_day": 900_000,
                    "change_kinds": ["product_discount", "price"],
                    "cause": {"stage": "ctor"},
                },
                {"product_id": "p1", "at_stake_per_day": 10, "change_kinds": ["title"]},
            ]
        },
    )
    c = await run_chain(d, "gmv_change", "gmv", PRESET, AS_OF)
    assert c.stop_reason == "within_noise"
    eng = FakeCardEngine()
    jev = jev_ok(kind="price", product=None)
    out = await cards.card_stage(
        chains=[c],
        data=d,
        engine=eng,
        jev=jev,
        labels=L,
        as_of=AS_OF,
        template=TEMPLATE_BY_KEY["improve_gmv"],
    )
    assert out.events[0]["type"] == "card" and eng.calls == [("price", "p9")]
    assert set(jev.calls[0][1]["kind"]["criteria"]) == {"product_discount", "price"}
    assert out.accepted[0]["critical"]["product_id"] == "p9"


async def test_cost_change_cards_only_for_ads_offers_affiliate() -> None:
    from tests.unit.analytics_agent.test_chains import _costs  # same synthetic cost fixture

    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF, orders=5.0)
    prods = [
        {"day": r["day"], "item_id": "p1", "gmv": 1000.0, "orders": 2.0, "units": 2.0} for r in shop
    ]
    d = FakeData(shop, products=prods, names={"p1": "Sản phẩm A"}, costs=_costs(900.0, 300.0))
    c = await run_chain(d, "cost_change", None, PRESET, AS_OF)
    jev = jev_ok(kind="ads_budget", product=None)
    out = await cards.card_stage(
        chains=[c], data=d, engine=FakeCardEngine(), jev=jev, labels=L, as_of=AS_OF
    )
    assert set(jev.calls[0][1]["kind"]["criteria"]) == {
        "ads_budget",
        "ads_roas_target",
        "ads_pause",
    }
    assert out.events[0]["type"] in ("card", "no_card")


def test_stage_is_read_only_no_materialize_or_choose_imports() -> None:
    root = Path(cards.__file__).parent
    for f in root.glob("*.py"):
        src = f.read_text()
        for bad in (
            "materialize",
            "create_manual",
            "choose(",
            ".commit(",
            "session.add",
            "persist=True",
        ):
            assert bad not in src, f"{f.name} references {bad}"
