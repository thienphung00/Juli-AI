"""Fast track P80: listing edit spans resolve against the original text, tolerantly.

Live sandbox run 23ac1c02 (01/11, prompt v4 + P79, edge case D34): a description-fix
card on a product whose description is ONE sentence (one paragraph section). The
model sent two ``replace_span`` ops on section 0; op 0 applied, op 1 was refused
``old_not_found`` on both attempts and nothing was written.

What this file pins:

* ``apply_ops`` resolves every span against the ORIGINAL section text (two disjoint
  ops in one sentence, a replace + an ``insert_after`` on the same section) -- the
  "op 1 searches the text op 0 already changed" hypothesis is refuted here;
* an ``old`` that differs from the original only by what the model cannot see or
  type the same way (hidden format characters the product read strips, NFD vs NFC,
  whitespace runs, dash / quote variants, surrounding spaces) is matched and the
  replacement lands on the exact original offsets -- nothing looser;
* an ``old`` copied from an earlier op's ``new`` (the model chaining ops) is refused
  with a message saying spans refer to the original and naming the op to merge into;
* a true overlap is ``ops_overlap`` with a merge instruction;
* an ``old_not_found`` / ``old_ambiguous`` / ``ops_overlap`` refusal hands the model
  the section's current text (hidden characters stripped, capped) for its one retry;
* the live run replayed through the real runner now pauses for consent with the
  seller's sentence kept.

Synthetic listing only: no real shop, brand or product.
"""

from __future__ import annotations

import unicodedata
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
from juli_backend.services.agent.tools.product_write import (
    REJECTION_TEXT_MAX_CHARS,
    register_product_write_tools,
)
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.shop_rules.listing_structure import (
    EditRejection,
    EditResult,
    ListingEditOps,
    RejectionCode,
    apply_ops,
)

PRODUCT_ID = "prod-synthetic-80"
TITLE_CODE = "TITLE_LESS_THAN_40_CHARACTERS"
DESC_SHORT = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
DESC_ONE_BLOCK = "DESC_NO_NEW_LINE"
IMAGE_CODE = "MAIN_IMG_NUMBER_LESS_THAN_FIVE"
FLAGGED = (TITLE_CODE, DESC_ONE_BLOCK, DESC_SHORT, IMAGE_CODE)

# The live shape: one sentence, one paragraph section.
SENTENCE = "Nồi lẩu điện mini 1.5L có nắp kính, dùng để nấu lẩu, mì và súp cho 1-2 người."
DESCRIPTION = f"<p>{SENTENCE}</p>"
TITLE = "Nồi lẩu điện mini 1.5L nắp kính"


def _span(old: str, new: str, *, code: str = DESC_SHORT, section: int = 0) -> dict[str, Any]:
    return {
        "op": "replace_span",
        "section_index": section,
        "old": old,
        "new": new,
        "reason_code": code,
    }


def _insert(text: str, *, section: int = 0) -> dict[str, Any]:
    return {"op": "insert_after", "section_index": section, "text": text, "reason_code": DESC_SHORT}


def _apply(
    description_ops: list[dict[str, Any]],
    *,
    description: str = DESCRIPTION,
    title: str = TITLE,
    title_ops: list[dict[str, Any]] | None = None,
) -> EditResult | EditRejection:
    ops = ListingEditOps.model_validate(
        {"title_ops": title_ops or [], "description_ops": description_ops}
    )
    return apply_ops(title, description, ops, FLAGGED)


def _applied(result: EditResult | EditRejection) -> EditResult:
    assert isinstance(result, EditResult), result
    return result


def _refused(result: EditResult | EditRejection, code: RejectionCode) -> EditRejection:
    assert isinstance(result, EditRejection), result
    assert result.code is code, result
    return result


# -- 1. spans resolve against the original (the live op patterns) -----------------------


@pytest.mark.parametrize(
    ("ops", "expected_html"),
    [
        pytest.param(
            [
                _span("Nồi lẩu điện mini 1.5L", "Nồi lẩu điện mini 1.5L 600W"),
                _span("cho 1-2 người.", "cho 1-2 người.\nVỏ inox, tay cầm cách nhiệt."),
            ],
            "<p>Nồi lẩu điện mini 1.5L 600W có nắp kính, dùng để nấu lẩu, mì và súp cho "
            "1-2 người.<br>Vỏ inox, tay cầm cách nhiệt.</p>",
            id="two_disjoint_spans_in_one_sentence",
        ),
        pytest.param(
            [
                _span("cho 1-2 người.", "cho 1-2 người.\nVỏ inox, tay cầm cách nhiệt."),
                _span("Nồi lẩu điện mini 1.5L", "Nồi lẩu điện mini 1.5L 600W"),
            ],
            "<p>Nồi lẩu điện mini 1.5L 600W có nắp kính, dùng để nấu lẩu, mì và súp cho "
            "1-2 người.<br>Vỏ inox, tay cầm cách nhiệt.</p>",
            id="op_order_does_not_matter",
        ),
        pytest.param(
            [
                _span("có nắp kính", "có nắp kính cường lực"),
                _insert("Dùng điện 220V, công suất 600W."),
            ],
            f"<p>{SENTENCE.replace('có nắp kính', 'có nắp kính cường lực')}</p>"
            "<p>Dùng điện 220V, công suất 600W.</p>",
            id="replace_then_insert_after_same_section",
        ),
    ],
)
def test_ops_on_one_section_all_resolve_against_the_original(
    ops: list[dict[str, Any]], expected_html: str
):
    assert _applied(_apply(ops)).description_html == expected_html


def test_whole_sentence_plus_sub_span_is_an_overlap_with_a_merge_instruction():
    rejection = _refused(
        _apply([_span(SENTENCE, SENTENCE + " Thêm."), _span("cho 1-2 người.", "cho 2 người.")]),
        RejectionCode.OPS_OVERLAP,
    )
    assert rejection.op_index == 1
    assert "merge" in rejection.message.lower()
    assert "one replace_span" in rejection.message
    assert rejection.context_text == SENTENCE


def test_two_title_spans_resolve_against_the_original_title():
    result = _applied(
        _apply(
            [],
            title_ops=[
                {
                    "op": "replace_title_span",
                    "old": "Nồi lẩu điện mini",
                    "new": "Nồi lẩu điện mini đa năng",
                    "reason_code": TITLE_CODE,
                },
                {
                    "op": "replace_title_span",
                    "old": "nắp kính",
                    "new": "nắp kính cho 1-2 người",
                    "reason_code": TITLE_CODE,
                },
            ],
        )
    )
    assert result.title == "Nồi lẩu điện mini đa năng 1.5L nắp kính cho 1-2 người"


# -- 2. tolerant-but-safe matching ------------------------------------------------------

_NFD_SENTENCE = unicodedata.normalize("NFD", SENTENCE)


@pytest.mark.parametrize(
    ("original", "old", "replaced"),
    [
        pytest.param(SENTENCE, "cho 1–2 người.", "cho 1-2 người.", id="en_dash_for_hyphen"),
        pytest.param(SENTENCE, "cho 1—2 người.", "cho 1-2 người.", id="em_dash_for_hyphen"),
        pytest.param(SENTENCE, "cho 1‐2 người.", "cho 1-2 người.", id="unicode_hyphen"),
        pytest.param(
            SENTENCE.replace("1-2", "1–2"), "cho 1-2 người.", "cho 1–2 người.", id="dash_in_text"
        ),
        pytest.param(SENTENCE, "  cho 1-2 người. ", "cho 1-2 người.", id="outer_whitespace"),
        pytest.param(SENTENCE, "mì  và\tsúp", "mì và súp", id="whitespace_runs"),
        pytest.param(
            SENTENCE.replace("mì và", "mì\u200b và"), "mì và súp", "mì\u200b và súp", id="zwsp"
        ),
        pytest.param(
            SENTENCE.replace("1.5L", "1.5\u00adL"), "mini 1.5L", "mini 1.5\u00adL", id="soft_hyph"
        ),
        pytest.param(_NFD_SENTENCE, "cho 1-2 người.", None, id="nfd_original_nfc_old"),
        pytest.param(
            SENTENCE,
            unicodedata.normalize("NFD", "cho 1-2 người."),
            "cho 1-2 người.",
            id="nfc_original_nfd_old",
        ),
        pytest.param(
            "Nắp “kính” cho 1-2 người.", 'Nắp "kính"', "Nắp “kính”", id="curly_vs_straight_quote"
        ),
        pytest.param("Nắp 'kính' rời.", "Nắp ’kính’", "Nắp 'kính'", id="straight_vs_curly_single"),
    ],
)
def test_old_matches_after_normalisation_and_replaces_the_exact_original_span(
    original: str, old: str, replaced: str | None
):
    result = _applied(_apply([_span(old, "XX")], description=f"<p>{original}</p>"))
    (section,) = result.skeleton
    (line,) = section.lines
    assert "XX" in line
    if replaced is not None:
        # Exactly the matched original characters were replaced, nothing around them.
        assert line == original.replace(replaced, "XX", 1)
    assert line.count("XX") == 1


@pytest.mark.parametrize(
    "old",
    [
        pytest.param("cho 1-3 người.", id="different_digit"),
        pytest.param("Cho 1-2 người.", id="different_case"),
        pytest.param("cho 1-2 nguoi.", id="diacritics_dropped"),
        pytest.param("cho 1 2 người.", id="dash_dropped"),
        pytest.param("cho 1-2 người!", id="different_punctuation"),
    ],
)
def test_matching_never_goes_beyond_the_listed_normalisations(old: str):
    rejection = _refused(_apply([_span(old, "XX")]), RejectionCode.OLD_NOT_FOUND)
    assert rejection.context_text == SENTENCE


def test_a_match_that_is_unique_only_before_normalisation_is_kept_exact():
    text = "Loại 1-2 người và loại 1–2 người."
    result = _applied(_apply([_span("1–2 người", "2-3 người")], description=f"<p>{text}</p>"))
    assert result.skeleton[0].lines == ("Loại 1-2 người và loại 2-3 người.",)


def test_two_matches_after_normalisation_are_ambiguous():
    text = "Loại 1-2 người và loại 1–2 người."
    rejection = _refused(
        _apply([_span("1—2 người", "x")], description=f"<p>{text}</p>"),
        RejectionCode.OLD_AMBIGUOUS,
    )
    assert rejection.context_text == text


def test_whitespace_only_old_is_empty():
    rejection = _refused(_apply([_span("   ", "x")]), RejectionCode.OLD_EMPTY)
    assert rejection.op_index == 0


def test_applying_is_deterministic():
    ops = [_span("cho 1–2 người.", "cho 1-2 người."), _span("mini 1.5L", "mini 1.5 lít")]
    assert _apply(ops) == _apply(ops)


# -- chained ops: old copied from an earlier op's new ----------------------------------


def test_an_old_copied_from_an_earlier_ops_new_says_spans_refer_to_the_original():
    rejection = _refused(
        _apply(
            [
                _span("cho 1-2 người.", "cho 1-2 người. Vỏ inox bền."),
                _span("Vỏ inox bền.", "Vỏ inox 304 bền, dễ lau chùi."),
            ]
        ),
        RejectionCode.OLD_NOT_FOUND,
    )
    assert rejection.op_index == 1
    assert "operation 0" in rejection.message
    assert "ORIGINAL" in rejection.message
    assert rejection.context_text == SENTENCE


def test_a_missing_old_carries_the_section_text_for_the_retry():
    rejection = _refused(_apply([_span("nồi cơm điện", "x")]), RejectionCode.OLD_NOT_FOUND)
    assert rejection.context_text == SENTENCE
    assert rejection.op_index == 0


def test_a_missing_title_old_carries_the_title():
    rejection = _refused(
        _apply(
            [],
            title_ops=[
                {"op": "replace_title_span", "old": "Bình", "new": "x", "reason_code": TITLE_CODE}
            ],
        ),
        RejectionCode.OLD_NOT_FOUND,
    )
    assert rejection.context_text == TITLE


# -- 3/4. the live run, replayed through the real runner -----------------------------------


class _Products:
    def __init__(self, description: str) -> None:
        self.description = description

    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        return {"id": PRODUCT_ID, "title": TITLE, "description": self.description}

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        results = [{"code": code} for code in FLAGGED]
        return {
            "products": [
                {"id": PRODUCT_ID, "diagnoses": [{"field": "ALL", "diagnosis_results": results}]}
            ]
        }


class _Resources:
    def __init__(self, products: _Products) -> None:
        self.products = products


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


def _edits_call(call_id: str, description_ops: list[dict[str, Any]]) -> ToolCallBlock:
    edits = {"title_ops": [], "description_ops": description_ops}
    return ToolCallBlock(
        call_id=call_id,
        tool_name="update_product_listing",
        arguments={"title": None, "description": None, "attach_staged_image": None, "edits": edits},
    )


async def _run(script: list[AssistantTurn], description: str) -> tuple[StopReason, RunState]:
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
            registry=registry,
            read_resources=_Resources(_Products(description)),
            product_id=PRODUCT_ID,
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


_FILLER = "Vỏ inox sáng bóng, tay cầm cách nhiệt, đế chống trượt, dễ lau chùi sau khi nấu."
#: The live pattern: op 0 grows the sentence's start, op 1 adds lines at its end -- the
#: model typed the dash in "1-2" as an en dash, as it renders on screen.
LIVE_OPS = [
    _span("Nồi lẩu điện mini 1.5L", "Nồi lẩu điện mini 1.5L công suất 600W"),
    _span("cho 1–2 người.", "cho 1–2 người.\n" + "\n".join([_FILLER] * 6), code=DESC_ONE_BLOCK),
]


async def test_live_run_23ac1c02_now_pauses_for_consent_with_the_sentence_kept():
    # The seller's text carries a zero-width space the product read strips for the model.
    description = DESCRIPTION.replace("mì và", "mì\u200b và")
    stop, state = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", LIVE_OPS)),
        ],
        description,
    )
    assert stop == StopReason.PAUSED_FOR_CONFIRMATION
    assert _tool_errors(state) == []
    # What the model read: the section without the hidden character.
    (read,) = [
        m["content"]
        for m in state.conversation_window
        if m.get("role") == "tool" and m.get("tool_name") == "get_product_information"
    ]
    assert read["description_sections"]["items"][0]["text"]["text"] == SENTENCE
    applied = state.pending_confirmation["arguments"]["description"]
    assert applied.startswith("<p>Nồi lẩu điện mini 1.5L công suất 600W có nắp kính, dùng để")
    # Outside the two spans every original character stays, the hidden one included.
    assert "có nắp kính, dùng để nấu lẩu, mì\u200b và súp cho 1–2 người.<br>" in applied
    assert applied.count(_FILLER) == 6


async def test_a_refused_span_hands_the_model_the_section_text_and_the_retry_passes():
    wrong = [LIVE_OPS[0], _span("cho hai người.", "cho hai người.\n" + _FILLER)]
    stop, state = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", wrong)),
            _turn(_edits_call("c2", LIVE_OPS)),
        ],
        DESCRIPTION.replace("mì và", "mì\u200b và"),
    )
    assert stop == StopReason.PAUSED_FOR_CONFIRMATION
    (message,) = _tool_errors(state)
    assert f"error_code={ERROR_LISTING_EDIT_REJECTED}: [old_not_found]" in message
    assert "(description operation 1)" in message
    # The section as the model read it: the hidden character stripped, verbatim otherwise.
    assert f'Section 0 reads exactly: "{SENTENCE}"' in message
    assert "\u200b" not in message
    assert state.proposal_refusals == {"update_product_listing": 1}


async def test_the_section_text_in_a_refusal_is_capped():
    long_sentence = "Nồi lẩu điện mini dùng cho gia đình nhỏ, nấu nhanh và tiết kiệm điện. " * 15
    stop, state = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", [_span("không có câu này", "x")])),
            _turn(_edits_call("c2", [_span("không có câu này", "x")])),
        ],
        f"<p>{long_sentence}</p>",
    )
    assert stop != StopReason.PAUSED_FOR_CONFIRMATION
    first, _second = _tool_errors(state)
    quoted = first.split("reads exactly: ", 1)[1]
    assert len(quoted) < REJECTION_TEXT_MAX_CHARS + 200
    assert "…" in quoted
