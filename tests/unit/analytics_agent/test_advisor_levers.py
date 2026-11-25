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
    shown = {a["lever"] for ex in advisor.FEW_SHOT for a in ex["emit_plan"]["actions"]}
    # an ads-loss question, a sale-day question, a conversion question and a non-card lever
    assert {"ads_remove_product", "ads_roas_target", "nhap_gia_von"} <= shown
    assert {"flash_sale", "min_spend_voucher", "program_registration"} <= shown
    assert {"review_voucher", "cover_image", "description_first_line"} <= shown
    assert any(
        "không" in ex["emit_plan"]["lead"] and "lỗ" in ex["emit_plan"]["lead"]
        for ex in advisor.FEW_SHOT
    )  # a premise correction
    # no example repeats a lever (the validator refuses it)
    for ex in advisor.FEW_SHOT:
        ls = [a["lever"] for a in ex["emit_plan"]["actions"]]
        assert len(ls) == len(set(ls))
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


# ------------------------------------------------ recorded 24/11 shapes (live run 2)


async def test_a31_shape_a_repeated_lever_is_refused_and_merged() -> None:
    """A31: three actions on the same affiliate lever (one per open card) pushed the ads card to
    #4. A repeated lever is refused; the model merges and the other levers surface."""
    from tests.unit.analytics_agent.fakes import FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import _ask_with, _rows, plan

    cards = [
        {**LIVE_CARDS[1], "code": f"JC-2611-02{n}", "item_id": f"p{n}"} for n in (75, 76, 90)
    ] + [LIVE_CARDS[0]]

    def aff(code: str) -> dict[str, Any]:
        return {
            "lever": "affiliate_commission",
            "card_ref": f"open:{code}",
            "why": "Hoa hồng đang chờ trên sản phẩm lỗ.",
        }

    budget = {"lever": "ads_budget", "card_ref": "open:JC-2611-0298", "why": "Giữ ngân sách."}
    llm = FakeLLM(
        agent_script=[
            [tool_use("open_cards", "t1")],
            plan(aff("JC-2611-0275"), aff("JC-2611-0276"), aff("JC-2611-0290"), budget),
            plan(budget, aff("JC-2611-0275")),  # the repair: merged, ads first
        ]
    )
    data = _live_data()
    data.cards = cards
    sink, res, _ = await _ask_with(llm, data)
    assert [r["lever"] for r in _rows(sink)] == ["ads_budget", "affiliate_commission"]
    refused = json.dumps(llm.agent_calls[2]["replayed"], ensure_ascii=False)
    assert "gộp các việc cùng lever" in refused


async def test_a13_shape_a_removal_card_drafts_without_a_number_and_a_miss_says_why() -> None:
    """A13: ads_remove_product / ads_pause have no volume estimate by design; the draft was
    refused as 'not estimable'. They draft now; a real miss tells the model the reason."""
    from juli_backend.services.analytics_agent import cards as cardstage
    from tests.unit.analytics_agent.fakes import FakeCardEngine, FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import _ask_with, _rows, plan

    no_est = {
        "ok": True,
        "card": {
            "title": "Gỡ sản phẩm khỏi chiến dịch nhóm",
            "versions": [{"label": "Gỡ", "inputs": {}, "result": {"estimable": False}}],
        },
    }
    assert cardstage.estimable(no_est["card"], "ads_remove_product")
    assert cardstage.estimable(no_est["card"], "ads_pause")
    assert not cardstage.estimable(no_est["card"], "ads_budget")  # sized kinds still need a number

    ctx = await _ctx()
    ctx.engine = FakeCardEngine(per_kind={"ads_budget": no_est})
    await advisor.run_tool(ctx, "product_margins", {})
    miss = await advisor.run_tool(ctx, "draft_card", {"kind": "ads_budget", "item": "p1"})
    assert miss["card_ref"] is None and miss["lý_do"] == advisor.NO_DRAFT_REASON_VI["not_estimable"]

    def ref_of(m: Any) -> str:
        return next(
            json.loads(r["content"])["card_ref"]
            for x in m
            if x["role"] == "user" and isinstance(x["content"], list)
            for r in x["content"]
            if r.get("tool_use_id") == "d1"
        )

    class A13(FakeLLM):
        async def agent(self, system: Any, tools: Any, messages: Any, *, force_tool: Any = None):
            if not self.agent_script:
                self.agent_script.append(
                    plan(
                        {
                            "lever": "ads_remove_product",
                            "card_ref": ref_of(messages),
                            "why": "Sản phẩm lỗ sau quảng cáo.",
                        },
                        lead="",
                    )
                )
            return await super().agent(system, tools, messages, force_tool=force_tool)

    llm = A13(
        agent_script=[
            [tool_use("product_margins", "t1")],
            [tool_use("draft_card", "d1", kind="ads_remove_product", item="p1")],
        ]
    )
    sink, _, _ = await _ask_with(llm, card_engine=FakeCardEngine(result=no_est))
    rows = _rows(sink)
    assert rows[0]["lever"] == "ads_remove_product" and rows[0]["value_vi"] == "Thẻ nháp"


async def test_tool_descriptions_list_their_findings_and_levers_and_week_shows_sale_days() -> None:
    specs = {t["name"]: t for t in advisor.tool_specs(sorted(L.kinds))}
    assert "ads_remove_product" in specs["product_profit"]["description"]
    assert "flash_sale" in specs["week_summary"]["description"]
    assert "review_voucher" in specs["metric_view"]["description"]
    assert (
        specs["draft_card"]["description"]
        == next(t for t in advisor._tool_specs(sorted(L.kinds)) if t["name"] == "draft_card")[
            "description"
        ]
    )
    ctx = await _ctx()
    res = await advisor.run_tool(ctx, "week_summary", {})
    ahead = res["ngày_sale_sắp_tới"]
    assert ahead and all(len(d) == 5 and d[2] == "/" for d in ahead)


async def test_a_plan_missing_its_lead_field_is_still_a_plan() -> None:
    """A07: the model's tool input is not trusted to be complete (no_plan before)."""
    from tests.unit.analytics_agent.fakes import FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import OPEN_BUDGET, _ask_with, _rows

    llm = FakeLLM(
        agent_script=[
            [tool_use("open_cards", "t1")],
            [tool_use("emit_plan", "p1", actions=[OPEN_BUDGET])],  # no `lead`
        ]
    )
    sink, _, _ = await _ask_with(llm)
    assert _rows(sink)[0]["lever"] == "ads_budget"


# ------------------------------------------------ recorded 24/11 shapes (live run 3)


def _campaign_data() -> Any:
    """The synthetic shop whose campaigns now carry the products they spend on."""
    data = _live_data()
    for c in data.entity["campaigns"]:
        c["items"] = ["p1", "p2"]
    return data


async def test_the_campaigns_tool_lists_each_campaigns_products_so_draft_card_can_take_one() -> (
    None
):
    from tests.unit.analytics_agent.test_advisor import _ctx

    ctx = await _ctx()
    for c in ctx.data.entity["campaigns"]:
        c["items"] = ["p1", "p2"]
    res = await advisor.run_tool(ctx, "campaigns", {})
    first = res["chiến_dịch"][0]
    assert [p["id"] for p in first["sản_phẩm_chạy_quảng_cáo"]] == ["p1", "p2"]
    assert first["sản_phẩm_chạy_quảng_cáo"][0]["tên"]
    # the ids are now known items: a campaign-level draft can name one (no `unknown_item`)
    out = await advisor.run_tool(ctx, "draft_card", {"kind": "ads_roas_target", "item": "p1"})
    assert out.get("lỗi") != "unknown_item"


async def test_a16_shape_a_thin_campaign_gets_a_roas_target_draft_through_its_product() -> None:
    from tests.unit.analytics_agent.fakes import FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import _ask_with, _rows, plan

    def ref(m: Any) -> str:
        return next(
            json.loads(r["content"])["card_ref"]
            for x in m
            if x["role"] == "user" and isinstance(x["content"], list)
            for r in x["content"]
            if r.get("tool_use_id") == "d1"
        )

    class A16(FakeLLM):
        async def agent(self, system: Any, tools: Any, messages: Any, *, force_tool: Any = None):
            if not self.agent_script:
                self.agent_script.append(
                    plan(
                        {
                            "lever": "ads_roas_target",
                            "card_ref": ref(messages),
                            "why": "CDN/02 lãi nhưng ROAS chỉ hơn hoà vốn một chút.",
                        },
                        lead="CDN/01 lãi rõ, không cần xử lý.",
                    )
                )
            return await super().agent(system, tools, messages, force_tool=force_tool)

    llm = A16(
        agent_script=[
            [tool_use("campaigns", "t1")],
            [tool_use("draft_card", "d1", kind="ads_roas_target", item="p1")],
        ]
    )
    sink, res, _ = await _ask_with(llm, _campaign_data())
    assert [r["lever"] for r in _rows(sink)] == ["ads_roas_target"]
    step = [s for s in res.routing if s.get("step") == "advise"][0]
    assert step["drafts"] == [
        {"kind": "ads_roas_target", "item": "p1", "status": "draft", "reason": None}
    ]  # every draft outcome is recorded for the next diagnosis


async def test_a30_shape_nhap_gia_von_needs_a_cogs_gap_in_the_data() -> None:
    """A30 / P03: with no missing giá vốn the model used the card-free lever as an escape. It is
    refused without the finding, and the cover-image lever is drafted instead."""
    from tests.unit.analytics_agent.fakes import FakeLLM, tool_use
    from tests.unit.analytics_agent.test_advisor import _ask_with, plan
    from tests.unit.analytics_agent.test_weekly import _data

    data = _data()
    for v in data.entity["product_profit"].values():  # no product misses giá vốn
        v["coverage_pct"] = 100.0
    gap = {"lever": "nhap_gia_von", "card_ref": "none", "why": "Thiếu giá vốn."}
    lead = "Giá vốn đã đủ."
    llm = FakeLLM(
        agent_script=[
            [tool_use("cogs_gaps", "g1"), tool_use("product_margins", "g2")],
            plan(gap, lead=lead),  # refused: cogs_gaps reported nothing missing
            plan(lead=lead),
        ]
    )
    sink, res, _ = await _ask_with(llm, data)
    refused = json.dumps(llm.agent_calls[2]["replayed"], ensure_ascii=False)
    assert "chỉ dùng khi công cụ đã báo đúng phát hiện" in refused
    assert not [e for e in sink.of("data_answer") if e["title_vi"].startswith("Việc nên")]
    assert lead in "".join(e["text"] for e in sink.of("text_delta"))


def test_p02_shape_the_guard_drops_only_the_leaking_sentence_and_keeps_quoted_names() -> None:
    from juli_backend.services.analytics_agent import facts

    f = facts.Facts()
    name = "[Deal 15.11] Combo Hộp Găng Tay TPE STAHAUS Chuyên Dụng Size L/M"
    text = (
        "Quảng cáo không lỗ nặng, cả hai chiến dịch đều lãi. "
        "Sản phẩm [Deal 15.11] Combo Hộp Găng Tay TPE STAHAUS Chuyên Dụng lỗ sau quảng cáo. "
        "See the full report in the dashboard now."
    )
    out, dropped = advisor.guard_text(text, f, {}, [name])
    assert "Quảng cáo không lỗ nặng" in out  # the clean sentence stays
    assert "Combo Hộp Găng Tay TPE STAHAUS" in out  # a quoted part of a real name is not a leak
    assert "See the full report" not in out and dropped == ["leak:english_run"]


def test_a_summary_quoting_part_of_a_product_name_passes_the_leak_check() -> None:
    from juli_backend.services.analytics_agent import writer

    name = "[Deal 15.11] Combo 3,5,10 Hộp Găng Tay TPE STAHAUS Chuyên Dụng Size L/M"
    text = "Sản phẩm [Deal 15.11] Combo Hộp Găng Tay TPE STAHAUS chiếm 79% GMV."
    assert writer.sanitise(text, None, [name])[1] == []
    assert "english_run" in writer.sanitise("Please check the shop report today.", None, [name])[1]


def test_merged_campaigns_keep_the_products_they_spend_on_biggest_first() -> None:
    from decimal import Decimal

    from juli_backend.services.analytics_agent.data_service import merge_campaigns

    raw = [
        {"key": "c1", "name": "CDN/01", "spend": 100, "gmv": 400, "before_ads": 50,
         "items": {"p1": Decimal(30), "p2": Decimal(70)}},
        {"key": "c2", "name": "CDN/01", "spend": 50, "gmv": 100, "before_ads": 10,
         "items": {"p1": Decimal(60)}},
    ]  # fmt: skip
    (row,) = merge_campaigns(raw)
    assert row["items"] == ["p1", "p2"]  # p1 90 > p2 70
