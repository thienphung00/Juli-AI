"""#52 / #53: the finding -> lever table is data; the schema, the prompt and the tool tags follow
it; the model chooses the levers and code only validates."""

from __future__ import annotations

import json
from typing import Any

from juli_backend.services.analytics_agent import advisor, levers
from juli_backend.services.analytics_agent.labels import shopee_labels
from juli_backend.services.shopee_recommendations.kinds import KINDS
from tests.unit.analytics_agent.test_advisor import _ctx

L = shopee_labels()


def _plan_schema() -> dict[str, Any]:
    spec = next(t for t in advisor.tool_specs(sorted(L.kinds)) if t["name"] == "emit_plan")
    return spec["input_schema"]


def test_the_table_only_names_real_levers_and_never_the_out_set() -> None:
    assert levers.check_table() == []
    assert len(levers.FINDINGS) == 25
    lead_only = {f.key for f in levers.FINDINGS if not f.levers}
    assert lead_only == {
        "ads_channel_no_baseline",
        "sale_day_in_window",
        "gmv_concentration",
        "open_card_duplicate",
        "data_too_thin",
    }
    assert levers.FINDING_BY_KEY["cogs_gap"].levers == ("nhap_gia_von",)


def test_the_lever_enum_is_kinds_py_minus_the_out_set_plus_the_non_card_action() -> None:
    expected = [k for k in KINDS if k not in levers.OUT_LEVERS] + ["nhap_gia_von"]
    assert levers.lever_enum() == expected
    assert levers.OUT_LEVERS == {"listing_hide", "listing_relist", "listing_combo"}
    # the platform label table covers every card lever (no code leaks as a label)
    assert set(levers.lever_enum(L.kinds)) == set(expected)


def test_emit_plan_has_a_lead_and_actions_with_a_required_card_ref() -> None:
    schema = _plan_schema()
    assert schema["required"] == ["lead", "actions"]
    item = schema["properties"]["actions"]["items"]
    assert item["required"] == ["lever", "card_ref", "why"]
    assert item["properties"]["lever"]["enum"] == levers.lever_enum(L.kinds)
    assert item["properties"]["card_ref"]["type"] == "string"  # null is not allowed
    assert "action" not in item["properties"] and "items" not in schema["properties"]
    draft = next(t for t in advisor.tool_specs(sorted(L.kinds)) if t["name"] == "draft_card")
    assert draft["input_schema"]["properties"]["kind"]["enum"] == levers.card_kinds(L.kinds)
    assert advisor.PLAN_TOOL["input_schema"]["required"] == ["lead", "actions"]


def test_the_prompt_carries_three_or_four_valid_few_shot_examples() -> None:
    assert 3 <= len(advisor.FEW_SHOT) <= 4
    enum = set(levers.lever_enum())
    for ex in advisor.FEW_SHOT:
        assert advisor.SYSTEM.count(json.dumps(ex, ensure_ascii=False)) == 1
        out = ex["emit_plan"]
        assert set(out) == {"lead", "actions"} and out["lead"]
        for a in out["actions"]:
            assert set(a) == {"lever", "card_ref", "why"} and a["lever"] in enum
            assert a["card_ref"].split(":")[0] in ("open", "draft", "none")
            assert (a["card_ref"] == "none") == (a["lever"] in levers.CARD_EXEMPT)
    # a premise correction, a lead-only answer and a non-card lever are all shown
    assert any(not ex["emit_plan"]["actions"] for ex in advisor.FEW_SHOT)
    assert any(
        a["lever"] == "nhap_gia_von" for ex in advisor.FEW_SHOT for a in ex["emit_plan"]["actions"]
    )
    assert "Chưa có phương án" not in advisor.SYSTEM


async def test_tool_results_carry_findings_tagged_with_the_allowed_levers() -> None:
    ctx = await _ctx()
    res = await advisor.run_tool(ctx, "campaigns", {})
    tags = {t["phát_hiện"]: t["lever"] for t in res["phát_hiện_và_lever"]}
    thin = levers.FINDING_BY_KEY["camp_thin"]
    assert tags[thin.label_vi] == list(thin.levers)
    res = await advisor.run_tool(ctx, "traffic_sources", {})
    lead_only = [t for t in res["phát_hiện_và_lever"] if isinstance(t["lever"], str)]
    assert lead_only and all("lead" in t["lever"] for t in lead_only)
    assert not any(ch.isdigit() for t in res["phát_hiện_và_lever"] for ch in t["phát_hiện"])
    # the model's own tools and refusals are not tagged
    assert "phát_hiện_và_lever" not in await advisor.run_tool(ctx, "draft_card", {"kind": "title"})


async def test_week_tools_accept_a_month_to_date_window_from_the_enum_only() -> None:
    ctx = await _ctx()
    ok = await advisor.run_tool(ctx, "campaigns", {"window": "mtd_vs_same_days_last_month"})
    assert "lỗi" not in ok
    assert await advisor.run_tool(ctx, "campaigns", {"window": "2026-11-01"}) == {
        "lỗi": "bad_argument"
    }
    props = next(t for t in advisor.tool_specs([]) if t["name"] == "idle_budget_days")[
        "input_schema"
    ]["properties"]
    assert props["window"]["enum"] == list(advisor.WINDOWS)


def test_an_idle_budget_day_spends_under_30_percent_of_budget_with_no_ad_orders() -> None:
    from datetime import date

    from juli_backend.services.analytics_agent import weekly

    d1, d2, d3, d4 = (date(2026, 11, n) for n in (16, 17, 18, 19))
    shop = [{"day": d, "orders": 5} for d in (d1, d2, d3, d4)]
    budget = [
        {"day": d1, "spend": 20.0, "budget": 100.0, "ad_orders": 0.0},  # idle
        {"day": d2, "spend": 40.0, "budget": 100.0, "ad_orders": 0.0},  # spent 40 %: not idle
        {"day": d3, "spend": 10.0, "budget": 100.0, "ad_orders": 1.0},  # has an ad order
        {"day": d4, "spend": 10.0, "budget": None, "ad_orders": 0.0},  # no budget limit
    ]
    assert [b["day"] for b in weekly.idle_days(budget, shop, (d1, d4))] == [d1]
    # an older row without ad orders falls back to the shop's orders that day
    old = [{"day": d1, "spend": 10.0, "budget": 100.0}]
    assert weekly.idle_days(old, shop, (d1, d4)) == []
    assert weekly.idle_days(old, [{"day": d1, "orders": 0}], (d1, d4)) == old


# ------------------------------------------------------------ live shapes (24/11 run)

#: shop_proposals.kind is the COARSE proposal kind; the card's own kind id is change_after's
#: change_kind (24/11 live run: every open card was refused as a kind mismatch).
LIVE_CARDS = [
    {
        "kind": "ads",
        "change_kind": "ads_budget",
        "item_id": None,
        "status": "sent",
        "code": "JC-2611-0298",
        "change_after": '{"change_kind": "ads_budget"}',
    },
    {
        "kind": "other",
        "change_kind": "affiliate_commission",
        "item_id": "p1",
        "status": "sent",
        "code": "JC-2611-0290",
        "change_after": '{"change_kind": "affiliate_commission"}',
    },
]


def _live_data() -> Any:
    from tests.unit.analytics_agent.test_weekly import _data

    data = _data()
    data.cards = LIVE_CARDS
    return data


def test_a_card_names_its_lever_from_change_kind_not_the_coarse_kind() -> None:
    assert advisor.card_lever(LIVE_CARDS[0]) == "ads_budget"
    assert advisor.card_lever(LIVE_CARDS[1]) == "affiliate_commission"
    assert advisor.card_lever({"kind": "ads"}) is None  # coarse alone names no lever
    assert advisor.card_lever({"kind": "title"}) == "title"  # a fine id in `kind` (older rows)


async def test_open_cards_tool_shows_each_cards_lever_and_label() -> None:
    from tests.unit.analytics_agent.test_advisor import _ctx

    ctx = await _ctx()
    ctx.data.cards = LIVE_CARDS
    res = await advisor.run_tool(ctx, "open_cards", {})
    got = {c["mã"]: (c["lever"], c["loại"]) for c in res["thẻ"]}
    assert got["JC-2611-0298"] == ("ads_budget", "Ngân sách quảng cáo")
    assert got["JC-2611-0290"][0] == "affiliate_commission"


async def test_a11_shape_open_card_of_another_lever_is_refused_then_drafted() -> None:
    """A11: the model first attaches the open budget card to a ROAS-target action; the refusal
    names the card's real lever; the model drafts the right card and the row points to it."""
    from tests.unit.analytics_agent.fakes import FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import _ask_with, _rows, plan

    why = "CDN/01 dưới ROAS hoà vốn, đang lỗ khi chạy quảng cáo."
    budget = {"lever": "ads_budget", "card_ref": "open:JC-2611-0298", "why": "Ngày chi ít."}

    class A11(FakeLLM):
        async def agent(self, system: Any, tools: Any, messages: Any, *, force_tool: Any = None):
            if not self.agent_script:
                seen = json.dumps(messages, ensure_ascii=False)
                if "d1" in seen and "card_ref" in seen and "draft:" in seen:
                    ref = next(
                        json.loads(r["content"])["card_ref"]
                        for m in messages
                        if m["role"] == "user" and isinstance(m["content"], list)
                        for r in m["content"]
                        if r.get("tool_use_id") == "d1"
                    )
                    self.agent_script.append(
                        plan(
                            {"lever": "ads_roas_target", "card_ref": ref, "why": why},
                            budget,
                            lead="Cả hai chiến dịch đều lãi.",
                        )
                    )
            return await super().agent(system, tools, messages, force_tool=force_tool)

    wrong = {"lever": "ads_roas_target", "card_ref": "open:JC-2611-0298", "why": why}
    llm = A11(
        agent_script=[
            [tool_use("campaigns", "t1"), tool_use("open_cards", "t2")],
            plan(wrong, budget),  # refused: the card is an ads_budget card
            [tool_use("draft_card", "d1", kind="ads_roas_target")],
        ]
    )
    sink, res, _ = await _ask_with(llm, _live_data())
    rows = _rows(sink)
    assert [r["lever"] for r in rows] == ["ads_roas_target", "ads_budget"]
    assert rows[0]["value_vi"] == "Thẻ nháp" and rows[1]["value_vi"] == "Đã có thẻ JC-2611-0298"
    assert [c["kind"] for c in sink.of("card")] == ["ads_roas_target"]
    refused = json.dumps(llm.agent_calls[2]["replayed"], ensure_ascii=False)
    assert "lever_của_thẻ" in refused and "ads_budget" in refused
    step = [s for s in res.routing if s.get("step") == "advise"][0]
    assert step["dropped"] == []


def test_the_parser_slot_sends_should_i_questions_to_advise_not_unsupported() -> None:
    from juli_backend.services.analytics_agent import routing
    from tests.unit.analytics_agent.test_routing import intent

    # fits is low (0.02) for this question, yet the typed slot decides: advise
    dec = routing.decide(
        intent(question_type="other", needs_advice=True, goal="ads"),
        {"fits": {"type": "noul", "noul": 0.02}},
    )
    assert dec["outcome"] == "go" and dec["mode"] == "advise" and dec["goal"] == "ads"
    # the parser is told that "should I ..." / "what to fix" questions are advice
    assert "whether to do something" in routing.PARSE_SYSTEM
    props = routing.INTENT_TOOL["input_schema"]["properties"]["intents"]["items"]["properties"]
    assert "whether to do something" in props["needs_advice"]["description"]
