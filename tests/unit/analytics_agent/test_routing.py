"""E1 (intent parse) and E2 (Jev routing, thresholds, cross-checks, lookup rules, resume)."""

from __future__ import annotations

from datetime import date
from typing import Any

from juli_backend.services.analytics_agent import routing
from juli_backend.services.analytics_agent.labels import shopee_labels
from tests.unit.analytics_agent.fakes import FakeData, FakeJev, FakeLLM

TODAY = date(2026, 10, 26)


def intent(**kw: Any) -> dict[str, Any]:
    base = {
        "question_type": "why_changed",
        "metric_phrase": "that number",
        "claimed_direction": "down",
        "time_phrase": "recently",
        "explicit_from": None,
        "explicit_to": None,
        "named_month": None,
        "product_phrase": None,
        "source_phrase": None,
    }
    return base | kw


def ch(pick: str, p: float = 0.95, second: str = "x") -> dict[str, Any]:
    return {"type": "choice", "choice": pick, "probabilities": {pick: p, second: round(1 - p, 4)}}


def nl(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def ans(**over: Any) -> dict[str, dict[str, Any]]:
    base = {
        "fits": nl(0.95),
        "mode": ch("why"),
        "lookup": ch("metric_total"),
        "chain": ch("orders_change"),
        "metric": ch("orders"),
        "window": ch("last_7d_vs_prev_7d"),
        "scope": ch("shop"),
        "product_named": nl(0.05),
        "metric_named": nl(0.95),
    }
    return base | over


# ------------------------------------------------------------------ E1


async def test_parse_product_phrase_verbatim_and_restatement_prefix() -> None:
    it = intent(product_phrase="áo thun cotton trắng")
    llm = FakeLLM(
        {"restated_vi": "Vì sao đơn hàng của áo thun cotton trắng giảm?", "intents": [it]}
    )
    out, _ = await routing.parse_intents(llm, "sao áo thun cotton trắng ế", TODAY)
    assert out and out["intents"][0]["product_phrase"] == "áo thun cotton trắng"
    assert out["restated"] == "Đang tìm hiểu: Vì sao đơn hàng của áo thun cotton trắng giảm?"


async def test_restatement_guard_empty_and_placeholder_fall_back_to_seller_words() -> None:
    for bad in ("", "   ", "Tôi hiểu: placeholder", "placeholder", "...", "Đang tìm hiểu: "):
        out, _ = await routing.parse_intents(
            FakeLLM({"restated_vi": bad, "intents": [intent()]}), "Vì sao đơn giảm", TODAY
        )
        assert out and out["restated"] == "Đang tìm hiểu: Vì sao đơn giảm", bad


async def test_cap_three_intents_and_rest_in_more() -> None:
    its = [intent(metric_phrase=str(i)) for i in range(5)]
    out, _ = await routing.parse_intents(
        FakeLLM({"restated_vi": "câu hỏi", "intents": its}), "q", TODAY
    )
    assert out and len(out["intents"]) == routing.MAX_INTENTS == 3 and len(out["more"]) == 2


async def test_parse_failure_retries_once_then_none() -> None:
    llm = FakeLLM(None)
    out, _ = await routing.parse_intents(llm, "q", TODAY)
    assert out is None and llm.parse_calls == 2


def test_strict_tool_schema() -> None:
    assert routing.INTENT_TOOL["strict"] is True
    assert routing.INTENT_TOOL["input_schema"]["additionalProperties"] is False


# ------------------------------------------------------------------ E2


def test_routing_questions_cover_the_contract_fields_and_drop_window_for_explicit_dates() -> None:
    qs = routing.routing_questions(intent())
    assert {
        "fits",
        "mode",
        "lookup",
        "chain",
        "metric",
        "window",
        "scope",
        "product_named",
        "metric_named",
    } <= set(qs)
    assert "cost_change" in qs["chain"]["criteria"]
    qs2 = routing.routing_questions(intent(explicit_from="2026-10-01", explicit_to="2026-10-07"))
    assert "window" not in qs2
    assert routing.jev_state(intent(product_phrase="x"))["intent"]["product_phrase"] == "x"


def test_thresholds_go_unsupported_and_between() -> None:
    assert routing.decide(intent(), ans())["outcome"] == "go"
    assert routing.decide(intent(), ans(fits=nl(0.2)))["outcome"] == "unsupported"
    mid = routing.decide(intent(), ans(fits=nl(0.5)))
    assert mid["outcome"] == "needs_choice" and mid["remaining"][0][0] == "chain"
    assert (
        routing.decide(intent(question_type="other"), ans(fits=nl(0.5)))["outcome"] == "unsupported"
    )


def test_choice_goes_ahead_only_when_ptop_06_and_twice_second() -> None:
    ok, _ = routing.choice_ok(ch("a", 0.65, "b"))
    assert ok is False  # 0.65 vs 0.35 is < 2x
    assert routing.choice_ok(ch("a", 0.7, "b"))[0] is True  # 0.7 / 0.3 >= 2
    assert (
        routing.choice_ok({"choice": "a", "probabilities": {"a": 0.5, "b": 0.2}})[0] is False
    )  # p_top < 0.6
    dec = routing.decide(
        intent(), ans(window=ch("last_7d_vs_prev_7d", 0.55, "last_30d_vs_prev_30d"))
    )
    assert dec["outcome"] == "needs_choice" and dec["remaining"][0] == (
        "window",
        ["last_7d_vs_prev_7d", "last_30d_vs_prev_30d"],
    )


def test_one_unclear_item_at_a_time_in_order_chain_metric_window_product() -> None:
    dec = routing.decide(
        intent(), ans(window=ch("a", 0.5, "b"), chain=ch("orders_change", 0.5, "gmv_change"))
    )
    assert [i for i, _ in dec["remaining"]] == ["chain", "window"]


def test_cross_check_chain_metric_conflict() -> None:
    hi = routing.decide(intent(), ans(chain=ch("gmv_change", 0.97), metric=ch("ctr")))
    assert hi["outcome"] == "go" and hi["metric"] == "gmv"  # high-confidence chain wins
    lo = routing.decide(
        intent(), ans(chain=ch("gmv_change", 0.8, "orders_change"), metric=ch("ctr"))
    )
    assert lo["outcome"] == "needs_choice" and lo["remaining"][0][0] == "chain"


def test_cross_check_product_named_vs_scope() -> None:
    d = routing.decide(intent(product_phrase="áo"), ans(product_named=nl(0.9)))
    assert d["scope"] == "product"
    d2 = routing.decide(intent(), ans(scope=ch("product"), product_named=nl(0.1)))
    assert d2["scope"] == "shop"


def test_lookup_rules_vague_asks_metric_and_top_products_needs_none() -> None:
    vague = routing.decide(
        intent(), ans(mode=ch("lookup"), lookup=ch("metric_total"), metric_named=nl(0.1))
    )
    assert vague["outcome"] == "needs_choice" and vague["remaining"][0][0] == "metric"
    top = routing.decide(
        intent(),
        ans(
            mode=ch("lookup"),
            lookup=ch("top_products"),
            metric_named=nl(0.1),
            metric=ch("gmv", 0.4, "orders"),
        ),
    )
    assert top["outcome"] == "go" and top["lookup"] == "top_products"
    named = routing.decide(
        intent(),
        ans(
            mode=ch("lookup"),
            lookup=ch("daily_trend"),
            chain=ch("orders_change", 0.4, "gmv_change"),
        ),
    )
    assert named["outcome"] == "go"  # a data answer never needs the chain


def test_needs_choice_event_has_real_dates_and_resume_runs_in_code() -> None:
    dec = routing.decide(
        intent(), ans(window=ch("last_7d_vs_prev_7d", 0.55, "last_30d_vs_prev_30d"))
    )
    ev = routing.needs_choice_event(dec, intent(), shopee_labels(), date(2026, 10, 25))
    assert (
        ev["item"] == "window" and ev["options"][0]["label_vi"] == "19/10–25/10 so với 12/10–18/10"
    )
    assert ev["question_vi"]
    dec2 = routing.resume(ev["pending"], {"item": "window", "value": "last_30d_vs_prev_30d"})
    assert (
        dec2["outcome"] == "go"
        and dec2["window"] == "last_30d_vs_prev_30d"
        and dec2["chain"] == "orders_change"
    )


def test_max_two_clarifying_turns_then_go() -> None:
    dec = routing.decide(
        intent(),
        ans(
            chain=ch("orders_change", 0.5, "gmv_change"),
            window=ch("a", 0.5, "b"),
            scope=ch("product", 0.5, "shop"),
        ),
    )
    ev = routing.needs_choice_event(dec, intent(), shopee_labels(), date(2026, 10, 25))
    d1 = routing.resume(ev["pending"], {"item": "chain", "value": "gmv_change"})
    assert d1["outcome"] == "needs_choice"
    ev2 = routing.needs_choice_event(
        d1, intent(), shopee_labels(), date(2026, 10, 25), turns=d1["turns"]
    )
    assert (
        routing.resume(ev2["pending"], {"item": "window", "value": "last_7d_vs_prev_7d"})["outcome"]
        == "go"
    )


async def test_product_resolution_one_many_none() -> None:
    jev = FakeJev({"product": ch("p2", 0.9, "p1")})
    one, _ = await routing.resolve_product(
        FakeData([], catalog=[{"item_id": "p1", "name": "A"}]), jev, intent(product_phrase="a")
    )
    assert one["status"] == "found" and not jev.calls
    many, _ = await routing.resolve_product(
        FakeData([], catalog=[{"item_id": "p1", "name": "A"}, {"item_id": "p2", "name": "B"}]),
        jev,
        intent(product_phrase="a"),
    )
    assert many["item_id"] == "p2" and len(jev.calls) == 1
    none, _ = await routing.resolve_product(FakeData([]), FakeJev({}), intent(product_phrase="zzz"))
    assert none["status"] == "none"
    unsure = FakeJev({"product": ch("p2", 0.5, "p1")})
    amb, _ = await routing.resolve_product(
        FakeData([], catalog=[{"item_id": "p1", "name": "A"}, {"item_id": "p2", "name": "B"}]),
        unsure,
        intent(product_phrase="a"),
    )
    assert amb["status"] == "ambiguous" and len(amb["options"]) == 2


def test_fits_boundaries_07_goes_and_03_is_unsupported() -> None:
    assert routing.decide(intent(), ans(fits=nl(0.7)))["outcome"] == "go"
    assert routing.decide(intent(), ans(fits=nl(0.3)))["outcome"] == "unsupported"
    assert routing.decide(intent(), ans(fits=nl(0.6999)))["outcome"] == "needs_choice"
    assert routing.decide(intent(), ans(fits=nl(0.3001)))["outcome"] == "needs_choice"
