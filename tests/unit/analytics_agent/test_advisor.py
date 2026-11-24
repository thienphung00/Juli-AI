"""J1-J5: the advisor. A scripted FakeLLM.agent drives the tool loop on the synthetic 22/11-shaped
shop (test_weekly._data); no paid call. Guards, the cap and the fallback are pinned here."""

from __future__ import annotations

import json
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, advisor, run
from juli_backend.services.analytics_agent.types import Usage
from tests.unit.analytics_agent.fakes import (
    FakeCardEngine,
    FakeJev,
    FakeLLM,
    ListSink,
    engine_card,
    tool_use,
)
from tests.unit.analytics_agent.test_cards import ch
from tests.unit.analytics_agent.test_engine import SHOP, L, full
from tests.unit.analytics_agent.test_routing import intent
from tests.unit.analytics_agent.test_weekly import YDAY, _data

READ_ALL = [
    tool_use("week_summary", "t1"),
    tool_use("campaigns", "t2"),
    tool_use("traffic_sources", "t3"),
    tool_use("product_margins", "t4"),
]
DRAFTS = [
    tool_use("open_cards", "t5"),
    tool_use("draft_card", "t6", kind="ads_roas_target"),
    tool_use("draft_card", "t7", kind="title", item="p1"),
]
FIRST = {
    "why": "CDN/01 dưới ROAS hoà vốn, đang lỗ khi chạy quảng cáo.",
    "lever": "ads_roas_target",
    "card_ref": "@ads",
}


OPEN_BUDGET = {"why": "Mở thẻ đang có.", "lever": "ads_budget", "card_ref": "open:JC-0001"}


def plan(*actions: dict[str, Any], lead: str = "") -> list[dict[str, Any]]:
    """An emit_plan turn in the #52 shape: a lead and actions {lever, card_ref, why}."""
    return [tool_use("emit_plan", "p1", lead=lead, actions=list(actions))]


async def _ask(
    script: list[list[dict[str, Any]]],
    *,
    parsed: dict[str, Any] | None = None,
    cost: float = 0.001,
) -> tuple[ListSink, Any, FakeLLM]:
    sink = ListSink()
    llm = FakeLLM(
        {
            "restated_vi": "Nên làm gì trước",
            "intents": [
                parsed or intent(question_type="plan", needs_advice=True, goal="plan_week")
            ],
        },
        agent_script=script,
        agent_cost=cost,
    )
    res = await run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="tuần sau nên làm gì trước?"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(window=ch("last_7d_vs_prev_7d"))),
        sink=sink,
        labels=L,
        data=_data(),
        card_engine=FakeCardEngine(
            per_kind={
                "ads_budget": {"ok": True, "card": {**engine_card(), "title": "Tăng ngân sách QC"}}
            }
        ),
    )
    return sink, res, llm


class _PlanAfterDrafts(FakeLLM):
    """Reads, drafts, then the plan. A card_ref "@ads" / "@title" becomes the draft ref the
    draft_card tool returned (tool ids t6 / t7)."""

    def __init__(self, final_items: list[dict[str, Any]], lead: str = "") -> None:
        super().__init__(agent_script=[READ_ALL, DRAFTS])
        self.final_items = final_items
        self.lead = lead

    async def agent(
        self,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        *,
        force_tool: str | None = None,
    ) -> tuple[list[dict[str, Any]], Usage]:
        if len(self.agent_script) == 0:
            refs: dict[str, str] = {}
            for m in messages:
                if m["role"] == "user" and isinstance(m["content"], list):
                    for r in m["content"]:
                        if r.get("tool_use_id") in ("t6", "t7"):
                            card = json.loads(r["content"]).get("card_ref")
                            refs["@ads" if r["tool_use_id"] == "t6" else "@title"] = card
            self.agent_script.append(
                plan(
                    *(
                        {**i, "card_ref": refs.get(i["card_ref"], i["card_ref"])}
                        for i in self.final_items
                    ),
                    lead=self.lead,
                )
            )
        return await super().agent(system, tools, messages, force_tool=force_tool)


async def _two_step(
    final_items: list[dict[str, Any]], lead: str = ""
) -> tuple[ListSink, Any, FakeLLM]:
    llm = _PlanAfterDrafts(final_items, lead)
    sink, res, _ = await _ask_with(llm)
    return sink, res, llm


async def _ask_with(llm: FakeLLM, data: Any = None) -> tuple[ListSink, Any, FakeLLM]:
    llm.intent = {
        "restated_vi": "Nên làm gì trước",
        "intents": [intent(question_type="plan", needs_advice=True, goal="plan_week")],
    }
    sink = ListSink()
    res = await run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="tuần sau nên làm gì trước?"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(window=ch("last_7d_vs_prev_7d"))),
        sink=sink,
        labels=L,
        data=data or _data(),
        card_engine=FakeCardEngine(
            per_kind={
                "ads_budget": {"ok": True, "card": {**engine_card(), "title": "Tăng ngân sách QC"}}
            }
        ),
    )
    return sink, res, llm


def _rows(sink: ListSink) -> list[dict[str, Any]]:
    secs = [e for e in sink.of("data_answer") if e["title_vi"].startswith("Việc nên làm, theo")]
    assert len(secs) == 1
    return secs[0]["rows"]


async def test_advice_is_an_ordered_list_with_cards_and_a_lead() -> None:
    sink, res, llm = await _two_step(
        [
            FIRST,
            {
                "why": "Tên Găng tay chiếm 80% GMV mà còn ghi ngày sale đã hết.",
                "lever": "title",
                "card_ref": "@title",
            },
            {**OPEN_BUDGET, "why": "Đã có thẻ ngân sách, mở thẻ để duyệt."},
        ],
        lead="Tuần này có ngày sale kéo GMV lên.",
    )
    rows = _rows(sink)
    assert [r["label_vi"][:2] for r in rows] == ["1.", "2.", "3."]
    assert [r["lever"] for r in rows] == ["ads_roas_target", "title", "ads_budget"]
    assert rows[0]["value_vi"] == "Thẻ nháp" and rows[2]["value_vi"] == "Đã có thẻ JC-0001"
    assert "80% GMV" in rows[1]["detail_vi"]  # traced to product_margins
    assert {c["kind"] for c in sink.of("card")} == {"ads_roas_target", "title"}
    assert {c["kind"] for c in res.cards} == {"ads_roas_target", "title"}
    lead = "".join(e["text"] for e in sink.of("text_delta"))
    assert "Số liệu đến hết 22/11" in lead and "Tuần này có ngày sale kéo GMV lên." in lead
    assert lead.endswith("Việc nên làm trước: ROAS mục tiêu quảng cáo.")
    assert res.stop_reasons == ["data_answer"]
    assert len(llm.agent_calls) == 3 and all(len(c["tools"]) == 11 for c in llm.agent_calls)
    assert any(s.get("step") == "advise" for s in res.routing)


async def test_invented_number_is_removed_and_traced_number_kept() -> None:
    sink, _, _ = await _two_step(
        [
            {
                **FIRST,
                "why": "CDN/01 dưới ROAS hoà vốn. Làm vậy sẽ thêm 777.000đ doanh thu. "
                "Tên Găng tay chiếm 80% GMV.",
            }
        ]
    )
    why = _rows(sink)[0]["detail_vi"]
    assert "777" not in why and "80% GMV" in why and why.startswith("CDN/01 dưới")


async def test_a_plan_with_a_bad_card_is_refused_and_the_model_drafts_it() -> None:
    """Missing / unknown / wrong-kind card_refs are sent back (one repair round); the second
    emit_plan carries the drafted card."""

    class Repairing(FakeLLM):
        async def agent(
            self, system: Any, tools: Any, messages: Any, *, force_tool: Any = None
        ) -> Any:
            if not self.agent_script:
                seen = json.dumps(messages, ensure_ascii=False)
                if "kế hoạch chưa hợp lệ" in seen:  # the refusal came back: use the draft
                    ref = next(
                        json.loads(r["content"])["card_ref"]
                        for m in messages
                        if m["role"] == "user" and isinstance(m["content"], list)
                        for r in m["content"]
                        if r.get("tool_use_id") == "t6"
                    )
                    self.agent_script.append(plan({**FIRST, "card_ref": ref}))
                else:
                    self.agent_script.append(
                        plan(
                            {**FIRST, "card_ref": "none"},
                            {**FIRST, "lever": "ads_budget", "card_ref": "open:JC-9999"},
                            {**OPEN_BUDGET, "lever": "title"},  # JC-0001 is an ads_budget card
                        )
                    )
            return await super().agent(system, tools, messages, force_tool=force_tool)

    llm = Repairing(agent_script=[READ_ALL, DRAFTS])
    sink, res, _ = await _ask_with(llm)
    rows = _rows(sink)
    assert [r["lever"] for r in rows] == ["ads_roas_target"] and rows[0]["value_vi"] == "Thẻ nháp"
    assert len(llm.agent_calls) == 4  # reads, drafts, refused plan, repaired plan
    refused = json.dumps(llm.agent_calls[3]["replayed"], ensure_ascii=False)
    assert "thiếu card_ref" in refused and "không có trong open_cards" in refused
    assert "không đúng loại" in refused


async def test_what_is_still_invalid_after_the_repair_round_is_dropped() -> None:
    bad = [
        {**FIRST, "card_ref": "open:JC-9999"},
        {**OPEN_BUDGET, "lever": "title"},
        {"why": "Sai lever.", "lever": "listing_hide", "card_ref": "open:JC-0001"},
        OPEN_BUDGET,
    ]
    llm = FakeLLM(agent_script=[READ_ALL, DRAFTS, plan(*bad), plan(*bad)])
    sink, res, _ = await _ask_with(llm)
    rows = _rows(sink)
    assert [r["lever"] for r in rows] == ["ads_budget"]  # only the valid action is shown
    step = [s for s in res.routing if s.get("step") == "advise"][0]
    assert "unknown_ref:open:JC-9999" in step["dropped"]
    assert "kind_mismatch:open:JC-0001" in step["dropped"]
    assert "bad_lever:open:JC-0001" in step["dropped"]
    assert "Chưa có phương án" not in str(sink.events)


async def test_the_non_card_lever_needs_no_card_and_a_lead_only_plan_is_an_answer() -> None:
    gap = {"why": "Túi đay thiếu giá vốn.", "lever": "nhap_gia_von", "card_ref": "none"}
    sink, _, llm = await _ask_with(FakeLLM(agent_script=[READ_ALL, plan(gap)]))
    rows = _rows(sink)
    assert rows[0]["value_vi"] == "" and rows[0]["label_vi"] == "1. Nhập giá vốn"
    assert len(llm.agent_calls) == 2  # no repair round: the lever is card-exempt
    sink, _, _ = await _ask_with(
        FakeLLM(agent_script=[READ_ALL, plan(lead="Giá vốn đã đủ, lợi nhuận đáng tin.")])
    )
    assert not [e for e in sink.of("data_answer") if e["title_vi"].startswith("Việc nên")]
    assert "Giá vốn đã đủ" in "".join(e["text"] for e in sink.of("text_delta"))


async def test_a_card_is_used_once_and_an_unused_draft_is_not_shown() -> None:
    sink, _, _ = await _two_step([FIRST, {**FIRST, "why": "Lặp lại."}])
    assert len(_rows(sink)) == 1
    assert [c["kind"] for c in sink.of("card")] == ["ads_roas_target"]  # the title draft unused


async def test_cost_cap_aborts_and_falls_back_to_the_weekly_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(advisor.ADVISE_COST_CAP_ENV, "0.02")
    sink, res, llm = await _ask([READ_ALL, DRAFTS, plan(FIRST)], cost=0.012)
    assert len(llm.agent_calls) == 2  # the third turn never starts: 0.0245 >= 0.02
    titles = {e["title_vi"] for e in sink.of("data_answer")}
    assert "Việc nên làm tuần sau" in titles and not any(
        t.startswith("Việc nên làm, theo") for t in titles
    )
    step = [s for s in res.routing if s.get("step") == "advise_fallback"][0]
    assert step["reason"] == "cap" and res.cost_usd >= 0.024  # the money spent is still counted
    assert res.stop_reasons == ["data_answer"]


async def test_llm_error_falls_back_to_the_weekly_sections() -> None:
    sink, res, _ = await _ask([])  # the fake raises on the first turn
    assert "Việc nên làm tuần sau" in {e["title_vi"] for e in sink.of("data_answer")}
    assert [s["reason"] for s in res.routing if s.get("step") == "advise_fallback"] == ["llm_error"]
    assert not sink.of("error")


async def test_four_turns_at_most_and_the_last_is_forced_to_the_plan() -> None:
    sink, res, llm = await _ask(
        [
            READ_ALL,
            [tool_use("open_cards", "a")],
            [tool_use("cogs_gaps", "b")],
            [tool_use("campaigns", "c")],
        ]
    )
    assert len(llm.agent_calls) == 4
    assert [c["force"] for c in llm.agent_calls] == [None, None, None, "emit_plan"]
    assert [s["reason"] for s in res.routing if s.get("step") == "advise_fallback"] == ["no_plan"]
    assert "Việc nên làm tuần sau" in {e["title_vi"] for e in sink.of("data_answer")}


async def test_default_cap_and_bad_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(advisor.ADVISE_COST_CAP_ENV, raising=False)
    assert advisor.cost_cap_usd() == 0.02
    monkeypatch.setenv(advisor.ADVISE_COST_CAP_ENV, "abc")
    assert advisor.cost_cap_usd() == 0.02
    monkeypatch.setenv(advisor.ADVISE_COST_CAP_ENV, "0.05")
    assert advisor.cost_cap_usd() == 0.05


async def _ctx() -> advisor.Ctx:
    data = _data()
    data.entity["product_rows"] = [
        {
            "item_id": k,
            "name": n,
            "profit": p,
            "ad_spend": 50.0,
            "margin_pct": 5.0,
            "gmv": 100.0,
            "break_even_roas": 3.0,
            "contribution_before_ads": 80.0,
        }
        for k, n, p in (("p1", "Găng tay sale 11.11", -20.0), ("p2", "Túi đay", 30.0))
    ]
    return advisor.Ctx(
        data=data,
        engine=FakeCardEngine(per_kind={}),
        jev=FakeJev(lambda s, q: full(window=ch("last_7d_vs_prev_7d"))),
        labels=L,
        as_of=YDAY,
        budget=advisor.Budget(cap=1.0),
    )


async def test_tools_never_take_a_shop_a_free_date_or_an_unseen_item() -> None:
    for spec in advisor.tool_specs(sorted(L.kinds)):
        props = spec["input_schema"].get("properties", {})
        assert not {"shop", "shop_id", "from", "to", "date", "start", "end"} & set(props)
        if "window" in props:
            assert props["window"]["enum"] == list(advisor.WINDOWS)
    ctx = await _ctx()
    bad_item = await advisor.run_tool(
        ctx, "product_profit", {"window": advisor.WINDOWS[0], "item": "zzz"}
    )
    assert bad_item == {"lỗi": "unknown_item"}
    bad_window = await advisor.run_tool(
        ctx, "metric_view", {"metric": "gmv", "window": "2026-01-01"}
    )
    assert bad_window == {"lỗi": "bad_argument"}
    assert await advisor.run_tool(ctx, "drop_table", {}) == {"lỗi": "công cụ không tồn tại"}


async def test_general_tools_answer_a_non_weekly_question() -> None:
    ctx = await _ctx()
    await advisor.run_tool(ctx, "product_margins", {})  # item ids become known
    mv = await advisor.run_tool(
        ctx, "metric_view", {"metric": "gmv", "window": "last_30d_vs_prev_30d", "item": "p1"}
    )
    assert mv.get("kỳ") and mv["số_liệu_đến"] == "Số liệu đến hết 22/11" and "lỗi" not in mv
    pp = await advisor.run_tool(ctx, "product_profit", {"window": "last_30d_vs_prev_30d"})
    assert pp["sản_phẩm"] and all("chi_QC" in r for r in pp["sản_phẩm"])
    one = await advisor.run_tool(
        ctx, "product_profit", {"window": "last_30d_vs_prev_30d", "item": "p2"}
    )
    assert [r["id"] for r in one["sản_phẩm"]] == ["p2"]
    assert len(ctx.results) == 4  # every result is in the fact set the guards check against


async def test_a_priority_question_routes_to_advise_not_jev() -> None:
    sink, _, llm = await _ask(
        [
            READ_ALL,
            plan(OPEN_BUDGET),
        ],
        parsed=intent(question_type="other", needs_advice=True, goal="prioritise"),
    )
    rows = _rows(sink)
    assert rows[0]["value_vi"] == "Đã có thẻ JC-0001" and len(llm.agent_calls) == 2


THINKING = {"type": "thinking", "thinking": "hmm", "signature": "sig"}


async def test_a_thinking_block_is_never_replayed_to_the_next_turn() -> None:
    llm = FakeLLM(
        agent_script=[[THINKING, tool_use("open_cards", "a")], [THINKING, *plan(OPEN_BUDGET)]]
    )
    sink, _, _ = await _ask_with(llm)
    assert _rows(sink)[0]["value_vi"] == "Đã có thẻ JC-0001"
    replayed = llm.agent_calls[1]["replayed"]
    kinds = [
        b["type"]
        for m in replayed
        for b in (m["content"] if isinstance(m["content"], list) else [])
    ]
    assert "thinking" not in kinds and kinds[0] == "tool_use"


async def test_the_second_turn_body_passes_the_real_gate_inspection() -> None:
    from juli_backend.services.juli_agent_api.ports import GateLLM, Vendors
    from juli_backend.services.llm_gate.vendors import Usage as GateUsage
    from juli_backend.services.llm_gate.vendors import inspect_messages_body

    bodies: list[dict[str, Any]] = []
    # the live API (24/11) adds keys the gate refuses on replay: ``caller`` on a tool_use,
    # ``citations`` on a text block; they must be dropped before the next turn
    turns = [
        [
            THINKING,
            {"type": "text", "text": "Xem thẻ.", "citations": None},
            {**tool_use("open_cards", "a"), "caller": {"type": "direct"}},
        ],
        [
            THINKING,
            tool_use("emit_plan", "p", lead="", actions=[OPEN_BUDGET]),
        ],
    ]

    async def messages(gate: Any, *, purpose: str, body: dict[str, Any], timeout: float) -> Any:
        bodies.append(inspect_messages_body(body, shop_identifiers=()))  # PayloadRefused = fail
        return {"content": turns.pop(0)}, GateUsage(100, 50)

    async def never(*a: Any, **k: Any) -> Any:
        raise AssertionError("unused")

    v = Vendors(
        messages=messages, stream=never, system_one=never, call_failed=OSError, refused=ValueError
    )
    ctx = await _ctx()
    advice = await advisor.run_advice(
        GateLLM(object(), v),
        ctx.data,
        ctx.engine,
        ctx.jev,
        L,
        YDAY,
        "nên làm gì",
        "none",
        advisor.Budget(cap=1.0),
    )
    assert advice.turns == 2 and len(bodies) == 2
    assert all(b["thinking"] == {"type": "disabled"} for b in bodies)
    assert all(
        b["type"] != "thinking"
        for m in bodies[1]["messages"]
        if isinstance(m["content"], list)
        for b in m["content"]
    )
