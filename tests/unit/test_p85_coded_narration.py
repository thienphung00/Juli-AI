"""Fast track P85 (D78 step 2, D78.2): the run panel shows a coded Juli status line only.

Live sandbox runs d7b5d16c and 6a3dd6fd (01-02/11, prompt v4) streamed the model's own
narration to the seller -- Markdown headings and bold, English ("Next-steps",
"CONFIRM", "playbook"), "tool của mình". What this file pins:

* with ``coded_narration`` the runner emits no ``assistant.text`` /
  ``assistant.text.delta`` at all; the model's text stays in the conversation (audit);
* the model reports codes through the runner's own strict ``report_status`` tool and
  Juli emits ONE ``workflow.status`` line written from its templates, with the codes in
  ``status_code`` -- before the turn's proposal pauses the run;
* the line is faithful: a reason code this run's reads never flagged is dropped, the
  plan comes from the proposal in the same turn;
* the tool schema is strict-convertible (the D78.5 registry gate, for a tool that is not
  in the registry), and the copy is free of banned patterns, Markdown and English;
* the live pattern: a one-sentence description, DESC_NO_NEW_LINE and
  DESC_LESS_THAN_FIVE_HUNDRED_CHARS flagged, a 415-character split draft refused under
  ``LISTING_VALIDATOR_ENFORCE``, the >= 500-character split then paused for consent.

Synthetic listing only: no real shop, brand or product.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.llm.openai_adapter import _translate_tool
from juli_backend.services.agent.llm.strict_schema import strict_problems, to_strict
from juli_backend.services.agent.playbooks.create_product import CREATE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.coded_status import (
    REPORT_STATUS_TOOL_NAME,
    ImpactCode,
    PlanCode,
    ReasonCode,
    ReportStatusInput,
    coded_status,
    flagged_codes,
    report_status_tool_definition,
)
from juli_backend.services.agent.runner.coded_status_copy import (
    IMPACT_LINES_VI,
    PLAN_LINES_VI,
    coded_status_line_vi,
)
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.sanitize.banned_patterns import AGENT_OUTPUT_SCOPE
from juli_backend.services.agent.sanitize.chokepoints import find_banned_pattern_hits
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools.diagnosis_labels import DIAGNOSIS_CODE_LABELS_VI
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.ops.runs import _audit_texts
from juli_backend.services.shop_rules.listing_validator import (
    description_text,
    validate_listing_proposal,
)

PRODUCT_ID = "prod-synthetic-85"
DESC_SHORT = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
DESC_ONE_BLOCK = "DESC_NO_NEW_LINE"
IMAGE_CODE = "MAIN_IMG_NUMBER_LESS_THAN_FIVE"
FLAGGED = (DESC_ONE_BLOCK, DESC_SHORT, IMAGE_CODE)

TITLE = "Bình giữ nhiệt inox 304 dung tích 500ml nắp bật một chạm"
SENTENCE = "Bình giữ nhiệt inox 304 dung tích 500ml, nắp bật một chạm, giữ nóng và giữ lạnh."
DESCRIPTION = f"<p>{SENTENCE}</p>"

#: The live run's prose, verbatim in shape: Markdown, English, internal mechanics.
LIVE_PROSE = (
    "## Next-steps\n**Lý do đề xuất:** TikTok báo mô tả ngắn. Mình sẽ dùng tool của "
    "mình theo playbook rồi chờ luồng CONFIRM."
)

_SHORT_PARAGRAPHS = [
    "Thân bình inox 304, dung tích 500ml, vừa túi xách và ngăn bàn làm việc.",
    "Nắp bật một chạm, mở bằng một tay khi đang di chuyển.",
    "Giữ nóng và giữ lạnh cho đồ uống mỗi ngày, dùng ở nhà, văn phòng hay trường học.",
    "Rửa bằng nước ấm và để khô tự nhiên sau khi dùng.",
    "Thân bình trơn, cầm chắc tay, đặt vừa ngăn để cốc trên xe máy và ô tô.",
]
_MORE_PARAGRAPHS = [
    "Bình inox 304 có bề mặt nhẵn, dễ lau chùi, không bám mùi đồ uống sau mỗi lần rửa.",
    "Dung tích 500ml đủ cho một buổi làm việc hoặc một buổi học, gọn trong balo.",
    "Nắp bật một chạm có khóa, đậy chặt khi để bình nằm trong túi.",
]


def _split(paragraphs: list[str]) -> dict[str, Any]:
    return {
        "op": "replace_span",
        "section_index": 0,
        "old": SENTENCE,
        "new": "\n\n".join([SENTENCE, *paragraphs]),
        "reason_code": DESC_ONE_BLOCK,
    }


#: The live bottle draft: split, but 415-ish characters of text (< 500).
SHORT_SPLIT = _split(_SHORT_PARAGRAPHS)
LONG_SPLIT = _split(_SHORT_PARAGRAPHS + _MORE_PARAGRAPHS)


# -- doubles --------------------------------------------------------------------------------


class _Products:
    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        return {"id": PRODUCT_ID, "title": TITLE, "description": DESCRIPTION}

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        results = [{"code": code} for code in FLAGGED]
        return {
            "products": [
                {"id": PRODUCT_ID, "diagnoses": [{"field": "ALL", "diagnosis_results": results}]}
            ]
        }


class _Resources:
    def __init__(self) -> None:
        self.products = _Products()


class _Store:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states[workflow_run_id]
        state.prompt_version = state.prompt_version or "optimize_product.v5"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState, **_: Any) -> None:
        self.states[workflow_run_id] = state


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=blocks, usage=Usage(0, 0))


def _read(call_id: str, tool_name: str) -> ToolCallBlock:
    return ToolCallBlock(call_id=call_id, tool_name=tool_name, arguments={})


def _status(call_id: str, reasons: list[str], plan: str, impact: str) -> ToolCallBlock:
    return ToolCallBlock(
        call_id=call_id,
        tool_name=REPORT_STATUS_TOOL_NAME,
        arguments={"reason_codes": reasons, "plan_code": plan, "impact_code": impact},
    )


def _edits(call_id: str, description_op: dict[str, Any]) -> ToolCallBlock:
    edits = {"title_ops": [], "description_ops": [description_op]}
    return ToolCallBlock(
        call_id=call_id,
        tool_name="update_product_listing",
        arguments={"title": None, "description": None, "attach_staged_image": None, "edits": edits},
    )


async def _run(
    script: list[AssistantTurn], *, coded: bool = True, playbook: Any = OPTIMIZE_PRODUCT_PLAYBOOK
) -> tuple[StopReason, RunState, InMemoryEventSink, FakeLLMService]:
    registry = _registry()
    store = _Store()
    run_id = uuid.uuid4()
    store.states[run_id] = RunState()
    llm = FakeLLMService(script=script, stream_chunk_chars=7)
    sink = InMemoryEventSink()
    runner = WorkflowRunner(
        llm_service=llm,
        tool_executor=ProductToolExecutor(
            registry=registry, read_resources=_Resources(), product_id=PRODUCT_ID
        ),
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=playbook,
        clock=lambda: 0.0,
        stream_text=True,
        coded_narration=coded,
    )
    result = await runner.run(run_id, product_ref=PRODUCT_ID)
    return result.stop_reason, store.states[run_id], sink, llm


def _types(sink: InMemoryEventSink) -> list[str]:
    return [event.event_type for event in sink.events]


def _coded_lines(sink: InMemoryEventSink) -> list[Any]:
    return [
        event.payload
        for event in sink.events
        if event.event_type == "workflow.status" and event.payload.status_code is not None
    ]


# -- 1. the live pattern through the real runner ---------------------------------------------


@pytest.fixture
def enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTING_VALIDATOR_ENFORCE", "1")


def test_the_two_drafts_measure_like_the_live_run() -> None:
    short = description_text("".join(f"<p>{p}</p>" for p in [SENTENCE, *_SHORT_PARAGRAPHS]))
    assert 400 <= len(short) < 500
    long = description_text(
        "".join(f"<p>{p}</p>" for p in [SENTENCE, *_SHORT_PARAGRAPHS, *_MORE_PARAGRAPHS])
    )
    assert len(long) >= 500


async def test_live_pattern_streams_no_prose_and_one_coded_line_before_consent(enforce) -> None:
    stop, state, sink, llm = await _run(
        [
            _turn(
                TextBlock(text=LIVE_PROSE),
                _read("d1", "get_product_diagnoses"),
                _read("i1", "get_product_information"),
            ),
            # The live bottle draft: split, but under 500 characters -> refused.
            _turn(_edits("c1", SHORT_SPLIT)),
            _turn(
                TextBlock(text=LIVE_PROSE),
                _status("s1", [DESC_SHORT, DESC_ONE_BLOCK], "description", "easier_to_read"),
                _edits("c2", LONG_SPLIT),
            ),
        ]
    )

    assert stop == StopReason.PAUSED_FOR_CONFIRMATION
    types = _types(sink)
    # No model prose on any seller event, streamed or committed.
    assert "assistant.text" not in types and "assistant.text.delta" not in types
    for event in sink.events:
        dumped = event.model_dump_json()
        assert "Next-steps" not in dumped and "playbook" not in dumped and "**" not in dumped
    # One coded line, written by Juli, before the decision.
    (line,) = _coded_lines(sink)
    assert line.phase_narration == (
        "Juli đề xuất sửa mô tả. Lý do đề xuất: Mô tả quá ngắn, Mô tả chưa xuống dòng. "
        "Tác động dự kiến: trang sản phẩm dễ đọc hơn."
    )
    assert line.status_code.model_dump() == {
        "reason_codes": [DESC_SHORT, DESC_ONE_BLOCK],
        "plan_code": "description",
        "impact_code": "easier_to_read",
    }
    status_at = next(i for i, e in enumerate(sink.events) if e.event_type == "workflow.status")
    assert status_at < types.index("workflow.approval_required")
    # report_status is not a step of the seller's run: no tool.* event names it.
    assert all(
        getattr(event.payload, "tool_name", None) != REPORT_STATUS_TOOL_NAME
        for event in sink.events
    )
    # The model's prose is kept for audit only.
    assert [m["content"] for m in state.conversation_window if m.get("content") == LIVE_PROSE]
    assert _audit_texts({"conversation_window": state.conversation_window})[0]["text"] == LIVE_PROSE
    # The short draft was refused, the long one passes the validator with ENFORCE on.
    assert state.proposal_refusals == {"update_product_listing": 1}
    applied = state.pending_confirmation["arguments"]["description"]
    assert applied.startswith(f"<p>{SENTENCE}</p>")
    assert len(re.findall(r"<p>", applied)) == 1 + len(_SHORT_PARAGRAPHS + _MORE_PARAGRAPHS)
    assert len(description_text(applied)) >= 500
    assert validate_listing_proposal(TITLE, DESCRIPTION, None, applied, FLAGGED).violations == ()
    # The status tool was offered to the model on every call.
    for call in llm.recorded_calls:
        assert REPORT_STATUS_TOOL_NAME in [tool["name"] for tool in call.tools]


async def test_a_reason_the_run_never_flagged_is_dropped_and_the_plan_follows_the_proposal(
    enforce,
) -> None:
    _, _, sink, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses"), _read("i1", "get_product_information")),
            _turn(
                # TITLE code never flagged on this product; plan claims title too.
                _status("s1", ["TITLE_LESS_THAN_40_CHARACTERS", DESC_SHORT], "title", "none"),
                _edits("c1", LONG_SPLIT),
            ),
        ]
    )

    (line,) = _coded_lines(sink)
    assert line.status_code.reason_codes == [DESC_SHORT]
    assert line.status_code.plan_code == "description"
    assert line.phase_narration == "Juli đề xuất sửa mô tả. Lý do đề xuất: Mô tả quá ngắn."


async def test_a_malformed_report_is_answered_and_the_run_goes_on(enforce) -> None:
    stop, state, sink, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses"), _read("i1", "get_product_information")),
            _turn(_status("s1", ["NOT_A_CODE"], "rewrite_everything", "none")),
            _turn(_edits("c1", LONG_SPLIT)),
        ]
    )

    assert stop == StopReason.PAUSED_FOR_CONFIRMATION
    assert _coded_lines(sink) == []
    (answer,) = [
        m["content"] for m in state.conversation_window if m.get("tool_name") == "report_status"
    ]
    assert answer["error"]["retryable"] is True


async def test_a_forced_turn_spent_on_the_status_alone_stays_forced() -> None:
    _, _, _, llm = await _run(
        [
            _turn(FinalResponse(content=LIVE_PROSE)),
            _turn(_status("s1", [], "nothing_to_change", "none")),
            _turn(
                ToolCallBlock(
                    call_id="t1",
                    tool_name="conclude_without_changes",
                    arguments={"reason": "nothing flagged"},
                )
            ),
        ]
    )

    assert [call.tool_choice for call in llm.recorded_calls] == [None, "required", "required"]


async def test_without_coded_narration_nothing_changes() -> None:
    _, _, sink, llm = await _run(
        [
            _turn(TextBlock(text="checking"), _read("d1", "get_product_diagnoses")),
            _turn(
                ToolCallBlock(
                    call_id="t1",
                    tool_name="conclude_without_changes",
                    arguments={"reason": "nothing flagged"},
                )
            ),
        ],
        coded=False,
    )

    assert "assistant.text" in _types(sink)
    assert REPORT_STATUS_TOOL_NAME not in [tool["name"] for tool in llm.recorded_calls[0].tools]


async def test_a_playbook_outside_the_coded_status_workflows_gets_no_status_tool() -> None:
    from juli_backend.services.agent.composition import build_product_tool_registry

    runner = WorkflowRunner(
        llm_service=FakeLLMService(script=[]),
        tool_executor=ProductToolExecutor(
            registry=build_product_tool_registry(), product_id=PRODUCT_ID
        ),
        event_sink=InMemoryEventSink(),
        conversation_store=_Store(),
        registry=build_product_tool_registry(),
        playbook=CREATE_PRODUCT_PLAYBOOK,
        coded_narration=True,
    )
    names = [tool["name"] for tool in runner._tool_definitions()]
    assert REPORT_STATUS_TOOL_NAME not in names


# -- 2. the strict schema (D78.5 gate for a tool outside the registry) ----------------------


def test_report_status_schema_converts_strict_and_closed() -> None:
    definition = report_status_tool_definition()
    strict = to_strict(definition["input_schema"])
    assert strict_problems(strict) == []
    assert to_strict(strict) == strict
    wire = _translate_tool(definition)
    assert wire["strict"] is True
    assert wire["parameters"] == strict
    assert wire["parameters"]["required"] == ["reason_codes", "plan_code", "impact_code"]
    assert wire["parameters"]["additionalProperties"] is False


def test_reason_codes_are_exactly_the_codes_juli_has_labels_for() -> None:
    assert {code.value for code in ReasonCode} == set(DIAGNOSIS_CODE_LABELS_VI)


def test_report_status_takes_codes_only() -> None:
    with pytest.raises(ValueError):
        ReportStatusInput.model_validate(
            {"reason_codes": [], "plan_code": "title", "impact_code": "none", "text": "prose"}
        )


# -- 3. the copy ---------------------------------------------------------------------------


def _every_line() -> list[str]:
    labels = list(DIAGNOSIS_CODE_LABELS_VI.values())
    return [
        coded_status_line_vi(
            reason_labels=labels[:count],
            plan_code=plan.value,
            impact_code=impact.value,
            max_labels=3,
        )
        for plan in PlanCode
        for impact in ImpactCode
        for count in (0, 1, 5)
    ]


def test_every_plan_and_impact_has_copy() -> None:
    assert set(PLAN_LINES_VI) == {plan.value for plan in PlanCode}
    assert set(IMPACT_LINES_VI) == {impact.value for impact in ImpactCode}


@pytest.mark.parametrize("line", _every_line())
def test_every_line_is_clean_vietnamese_without_markdown(line: str) -> None:
    assert find_banned_pattern_hits(line, scope=AGENT_OUTPUT_SCOPE) == ()
    assert not line.startswith("Đang chờ"), "the demo reads that prefix as the pause point"
    assert not re.search(r"[*#`_]|\b(?:tool|playbook|CONFIRM|Next)\b", line)
    assert "\n" not in line


def test_more_than_three_reasons_are_counted_not_listed() -> None:
    labels = ["A", "B", "C", "D", "E"]
    line = coded_status_line_vi(
        reason_labels=labels, plan_code="title", impact_code="none", max_labels=3
    )
    assert line == "Juli đề xuất sửa tiêu đề. Lý do đề xuất: A, B, C và 2 điểm khác."


def test_nothing_to_change_names_no_reason_and_no_impact() -> None:
    report = ReportStatusInput(
        reason_codes=[ReasonCode.DESC_NO_NEW_LINE],
        plan_code=PlanCode.NOTHING_TO_CHANGE,
        impact_code=ImpactCode.EASIER_TO_READ,
    )
    window = [
        {
            "role": "tool",
            "tool_name": "get_product_diagnoses",
            "content": {"codes": [{"code": DESC_ONE_BLOCK}]},
        },
    ]
    line, codes = coded_status(report, window=window)
    assert line == PLAN_LINES_VI["nothing_to_change"]
    assert codes.impact_code == "none"


def test_flagged_codes_read_both_the_diagnoses_and_the_edit_codes() -> None:
    window = [
        {
            "role": "tool",
            "tool_name": "get_product_diagnoses",
            "content": {"codes": [{"code": IMAGE_CODE}]},
        },
        {
            "role": "tool",
            "tool_name": "get_product_information",
            "content": {
                "edit_codes": {
                    "title_codes": [{"code": "SEO_DIAGNOSTIC_ITEM"}],
                    "description_codes": [{"code": DESC_SHORT}],
                    "not_for_text": [IMAGE_CODE],
                }
            },
        },
        {"role": "assistant", "content": f"{DESC_ONE_BLOCK} is mentioned in prose only"},
    ]
    assert flagged_codes(window) == {IMAGE_CODE, "SEO_DIAGNOSTIC_ITEM", DESC_SHORT}


def test_the_v5_worked_example_is_the_line_juli_writes() -> None:
    from juli_backend.services.agent.prompts.composer import compose

    line = coded_status_line_vi(
        reason_labels=[
            DIAGNOSIS_CODE_LABELS_VI[DESC_SHORT],
            DIAGNOSIS_CODE_LABELS_VI[DESC_ONE_BLOCK],
        ],
        plan_code="description",
        impact_code="easier_to_read",
        max_labels=3,
    )
    prompt = compose("optimize_product_2", 5)
    quoted = " ".join(row[2:].strip() for row in prompt.splitlines() if row.startswith("> "))
    assert quoted == line
