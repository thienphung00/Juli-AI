"""Fast track P81: a listing edit may split a paragraph into several (edge case D35).

Live sandbox run aba7cb24 (01/11, prompt v4 + P79 + P80): the description is ONE
paragraph section holding one sentence; TikTok flags ``DESC_NO_NEW_LINE`` and
``DESC_LESS_THAN_FIVE_HUNDRED_CHARS``. Attempt 1 sent two ``replace_span`` ops whose
``old`` was the whole sentence (``ops_overlap``, correctly); attempt 2 merged them into
one ``replace_span`` whose ``new`` kept the sentence and added paragraphs split by blank
lines -- refused ``section_structure_changed`` ("a section must not be split"). Fixing
``DESC_NO_NEW_LINE`` on a one-paragraph description REQUIRES that split.

What this file pins:

* a ``replace_span`` / ``insert_after`` whose text holds blank lines becomes several
  paragraphs in the section's place when its reason_code is a flagged
  ``DESC_NO_NEW_LINE`` / ``DESC_LESS_THAN_FIVE_HUNDRED_CHARS``; the HTML carries one
  ``<p>`` per paragraph and the post-validator's line-break check passes;
* still refused: emptying a section, merging two original sections, dropping lines,
  splitting a heading, a blank list item, and a split without such a flagged code
  (the message names the code that allows it and what is allowed);
* the live run replayed through the real runner now pauses for consent with the
  seller's sentence kept, the description longer and in several paragraphs.

Synthetic listing only: no real shop, brand or product.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools.listing_rules import ERROR_LISTING_EDIT_REJECTED
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.shop_rules.listing_structure import (
    EditRejection,
    EditResult,
    ListingEditOps,
    RejectionCode,
    SectionKind,
    apply_ops,
    parse_description,
    render_description,
)
from juli_backend.services.shop_rules.listing_validator import (
    ListingViolationCode,
    description_text,
    validate_listing_proposal,
)

PRODUCT_ID = "prod-synthetic-81"
TITLE_CODE = "TITLE_LESS_THAN_40_CHARACTERS"
DESC_SHORT = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
DESC_ONE_BLOCK = "DESC_NO_NEW_LINE"
IMAGE_CODE = "MAIN_IMG_NUMBER_LESS_THAN_FIVE"
FLAGGED = (TITLE_CODE, DESC_ONE_BLOCK, DESC_SHORT, IMAGE_CODE)

SENTENCE = "Nồi lẩu điện mini 1.5L có nắp kính, dùng để nấu lẩu, mì và súp cho 1-2 người."
DESCRIPTION = f"<p>{SENTENCE}</p>"
TITLE = "Nồi lẩu điện mini 1.5L nắp kính"
PARA_2 = "Vỏ inox sáng bóng, tay cầm cách nhiệt, đế chống trượt, dễ lau chùi sau khi nấu."
PARA_3 = "Hai mức nhiệt nấu và giữ ấm, phù hợp phòng trọ, ký túc xá và văn phòng."
TWO_PARAGRAPHS = "<p>Đoạn một của mô tả.</p><p>Đoạn hai của mô tả.</p>"
ALLOWED = "New paragraphs and line breaks inside the edited paragraph are allowed"


def _span(old: str, new: str, *, code: str = DESC_ONE_BLOCK, section: int = 0) -> dict[str, Any]:
    return {
        "op": "replace_span",
        "section_index": section,
        "old": old,
        "new": new,
        "reason_code": code,
    }


def _insert(text: str, *, code: str = DESC_ONE_BLOCK, section: int = 0) -> dict[str, Any]:
    return {"op": "insert_after", "section_index": section, "text": text, "reason_code": code}


def _apply(
    description_ops: list[dict[str, Any]],
    *,
    description: str = DESCRIPTION,
    flagged: tuple[str, ...] = FLAGGED,
) -> EditResult | EditRejection:
    ops = ListingEditOps.model_validate({"title_ops": [], "description_ops": description_ops})
    return apply_ops(TITLE, description, ops, flagged)


def _applied(result: EditResult | EditRejection) -> EditResult:
    assert isinstance(result, EditResult), result
    return result


def _refused(result: EditResult | EditRejection, code: RejectionCode) -> EditRejection:
    assert isinstance(result, EditRejection), result
    assert result.code is code, result
    assert result.message.isascii()
    return result


def _paragraph_count(description_html: str) -> int:
    return len(re.findall(r"<p>", description_html))


# -- 1. what a split may do ----------------------------------------------------------------


def test_replace_span_splits_one_paragraph_into_three_and_keeps_the_sentence():
    result = _applied(_apply([_span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}\n\n{PARA_3}")]))

    assert result.description_html == f"<p>{SENTENCE}</p><p>{PARA_2}</p><p>{PARA_3}</p>"
    assert _paragraph_count(result.description_html) == 3
    assert [s.kind for s in result.skeleton] == [SectionKind.PARAGRAPH] * 3
    # The rendered HTML reads back as the same three paragraphs (TikTok sees the breaks).
    assert parse_description(result.description_html) == result.skeleton
    assert render_description(parse_description(result.description_html)) == (
        result.description_html
    )


def test_a_split_passes_the_post_validators_line_break_check():
    result = _applied(_apply([_span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}")]))

    validation = validate_listing_proposal(TITLE, DESCRIPTION, None, result.description_html)
    codes = {violation.code for violation in validation.violations}
    assert ListingViolationCode.DESCRIPTION_NO_LINE_BREAK not in codes
    unsplit = validate_listing_proposal(TITLE, DESCRIPTION, None, DESCRIPTION)
    assert ListingViolationCode.DESCRIPTION_NO_LINE_BREAK in {
        violation.code for violation in unsplit.violations
    }


def test_single_line_breaks_inside_a_split_paragraph_stay_line_breaks():
    result = _applied(_apply([_span(SENTENCE, f"{SENTENCE}\n{PARA_2}\n\n{PARA_3}")]))

    assert result.description_html == f"<p>{SENTENCE}<br>{PARA_2}</p><p>{PARA_3}</p>"


@pytest.mark.parametrize("code", [DESC_ONE_BLOCK, DESC_SHORT])
def test_insert_after_with_several_paragraphs_is_allowed_for_a_flagged_code(code: str):
    result = _applied(_apply([_insert(f"{PARA_2}\n\n{PARA_3}", code=code)]))

    assert result.description_html == f"<p>{SENTENCE}</p><p>{PARA_2}</p><p>{PARA_3}</p>"


def test_a_split_leaves_other_sections_untouched_and_indices_original():
    result = _applied(
        _apply(
            [
                _span("Đoạn một của mô tả.", f"Đoạn một của mô tả.\n\n{PARA_2}", section=0),
                _span("Đoạn hai", "Đoạn hai (cuối)", section=1),
            ],
            description=TWO_PARAGRAPHS,
        )
    )

    assert result.description_html == (
        f"<p>Đoạn một của mô tả.</p><p>{PARA_2}</p><p>Đoạn hai (cuối) của mô tả.</p>"
    )


def test_a_trailing_blank_line_is_not_a_split():
    # One paragraph comes out, so no flagged code is needed.
    result = _applied(_apply([_span("1-2 người.", "1-2 người.\n\n", code=DESC_SHORT)], flagged=()))

    assert result.description_html == DESCRIPTION


# -- 2. what stays refused ------------------------------------------------------------------


def test_emptying_a_section_is_refused_and_says_what_is_allowed():
    rejection = _refused(_apply([_span(SENTENCE, "")]), RejectionCode.SECTION_STRUCTURE_CHANGED)

    assert "empties section 0" in rejection.message
    assert ALLOWED in rejection.message
    assert rejection.op_index == 0


def test_blank_lines_only_count_as_emptying():
    rejection = _refused(_apply([_span(SENTENCE, "\n\n")]), RejectionCode.SECTION_STRUCTURE_CHANGED)

    assert "empties section 0" in rejection.message


def test_merging_two_original_sections_is_refused():
    rejection = _refused(
        _apply(
            [
                _span("Đoạn một của mô tả.", "Đoạn một của mô tả. Đoạn hai của mô tả.", section=0),
                _span("Đoạn hai của mô tả.", "", section=1),
            ],
            description=TWO_PARAGRAPHS,
        ),
        RejectionCode.SECTION_STRUCTURE_CHANGED,
    )

    assert "empties section 1" in rejection.message
    assert "deleting or merging other sections is not" in rejection.message


def test_merging_the_lines_of_a_paragraph_while_splitting_it_is_refused():
    rejection = _refused(
        _apply(
            [_span("Dòng một.\nDòng hai.\nDòng ba.", f"Dòng một. Dòng hai. Dòng ba.\n\n{PARA_2}")],
            description="<p>Dòng một.<br>Dòng hai.<br>Dòng ba.</p>",
        ),
        RejectionCode.SECTION_DROPPED,
    )

    assert ALLOWED in rejection.message


@pytest.mark.parametrize(
    ("op", "flagged"),
    [
        pytest.param(_span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}"), (), id="nothing_flagged"),
        pytest.param(
            _span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}"), (DESC_SHORT,), id="its_code_not_flagged"
        ),
        pytest.param(
            _span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}", code="DESCRIPTION_OTHER"),
            ("DESCRIPTION_OTHER",),
            id="flagged_code_that_is_not_a_split_code",
        ),
    ],
)
def test_a_split_without_a_flagged_split_code_is_refused_naming_the_code(
    op: dict[str, Any], flagged: tuple[str, ...]
):
    rejection = _refused(_apply([op], flagged=flagged), RejectionCode.SECTION_STRUCTURE_CHANGED)

    assert "splits section 0 into several paragraphs" in rejection.message
    assert "DESC_NO_NEW_LINE" in rejection.message
    assert "DESC_LESS_THAN_FIVE_HUNDRED_CHARS" in rejection.message
    assert ALLOWED in rejection.message


def test_insert_after_with_several_paragraphs_without_a_flagged_code_is_refused():
    rejection = _refused(
        _apply([_insert(f"{PARA_2}\n\n{PARA_3}")], flagged=(DESC_SHORT,)),
        RejectionCode.INSERT_TEXT_INVALID,
    )

    assert "DESC_NO_NEW_LINE" in rejection.message


def test_splitting_a_heading_is_refused_even_with_a_flagged_code():
    rejection = _refused(
        _apply([_span("Công dụng", "Công dụng\n\nThêm")], description="<h2>Công dụng</h2>"),
        RejectionCode.SECTION_STRUCTURE_CHANGED,
    )

    assert "is a heading" in rejection.message


def test_a_blank_list_item_is_refused():
    rejection = _refused(
        _apply([_span("Mục một", "Mục một\n\nMục hai")], description="<ul><li>Mục một</li></ul>"),
        RejectionCode.SECTION_STRUCTURE_CHANGED,
    )

    assert "empty item in section 0" in rejection.message


# -- 3. the live run, replayed through the real runner -------------------------------------


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
        state.prompt_version = state.prompt_version or "optimize_product.v4"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState, **_: Any) -> None:
        self.states[workflow_run_id] = state


def _turn(*blocks: ToolCallBlock) -> AssistantTurn:
    return AssistantTurn(blocks=blocks, usage=Usage(0, 0))


def _read(call_id: str, tool_name: str) -> ToolCallBlock:
    return ToolCallBlock(call_id=call_id, tool_name=tool_name, arguments={})


_TITLE_OP = {
    "op": "replace_title_span",
    "old": "nắp kính",
    "new": "nắp kính cường lực, chống dính",
    "reason_code": TITLE_CODE,
}


def _edits_call(call_id: str, description_ops: list[dict[str, Any]]) -> ToolCallBlock:
    edits = {"title_ops": [_TITLE_OP], "description_ops": description_ops}
    return ToolCallBlock(
        call_id=call_id,
        tool_name="update_product_listing",
        arguments={"title": None, "description": None, "attach_staged_image": None, "edits": edits},
    )


async def _run(script: list[AssistantTurn]) -> tuple[StopReason, RunState]:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    store = _Store()
    run_id = uuid.uuid4()
    store.states[run_id] = RunState()
    runner = WorkflowRunner(
        llm_service=FakeLLMService(script=script),
        tool_executor=ProductToolExecutor(
            registry=registry, read_resources=_Resources(), product_id=PRODUCT_ID
        ),
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        registry=registry,
        playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        clock=lambda: 0.0,
    )
    result = await runner.run(run_id, product_ref=PRODUCT_ID)
    return result.stop_reason, store.states[run_id]


def _tool_errors(state: RunState) -> list[str]:
    return [
        str(message["content"]["error"]["message"])
        for message in state.conversation_window
        if message.get("role") == "tool" and "error" in (message.get("content") or {})
    ]


_MORE = [
    PARA_2,
    PARA_3,
    "Lòng nồi phủ chống dính, nấu mì hay luộc trứng đều nhanh, không bám cặn.",
    "Nắp kính cường lực giúp quan sát món ăn khi nấu, có lỗ thoát hơi an toàn.",
    "Dây điện dài, phích cắm chắc chắn; nhớ rút điện sau khi dùng xong.",
    "Kích thước gọn, cất tủ dễ dàng, mang theo khi đi du lịch hoặc dã ngoại.",
]
#: Attempt 2 of run aba7cb24: the sentence kept, more paragraphs after blank lines.
MERGED = _span(SENTENCE, "\n\n".join([SENTENCE, *_MORE]))
#: Attempt 1: two ops whose ``old`` is the whole sentence.
OVERLAPPING = [
    _span(SENTENCE, f"{SENTENCE}\n\n{PARA_2}"),
    _span(SENTENCE, f"{SENTENCE}\n\n{PARA_3}", code=DESC_SHORT),
]


async def test_live_run_aba7cb24_attempt_2_now_pauses_for_consent():
    stop, state = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", OVERLAPPING)),
            _turn(_edits_call("c2", [MERGED])),
        ]
    )

    assert stop == StopReason.PAUSED_FOR_CONFIRMATION
    (message,) = _tool_errors(state)
    assert f"error_code={ERROR_LISTING_EDIT_REJECTED}: [ops_overlap]" in message
    assert state.proposal_refusals == {"update_product_listing": 1}
    arguments = state.pending_confirmation["arguments"]
    assert arguments["title"] == "Nồi lẩu điện mini 1.5L nắp kính cường lực, chống dính"
    applied = arguments["description"]
    # Every original character kept, the description longer and in several paragraphs.
    assert applied.startswith(f"<p>{SENTENCE}</p>")
    assert _paragraph_count(applied) == 1 + len(_MORE)
    assert all(f"<p>{text}</p>" in applied for text in _MORE)
    assert len(description_text(applied)) >= max(500, len(description_text(DESCRIPTION)))
