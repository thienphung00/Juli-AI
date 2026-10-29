"""P76-4 (D78): the listing-edit post-validator, its precheck wiring and one-retry-then-refuse.

Rules: ``shop_rules.listing_validator``. Wiring: ``product_write.precheck_update_product_listing``.
Retry: ``WorkflowRunner`` counts precheck refusals per run and tool on ``RunState``.
"""

from __future__ import annotations

import logging
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
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools.listing_rules import (
    ERROR_RULE_VIOLATION,
    RULE_REFUSAL_FINAL_VI,
    RULE_REFUSAL_SUMMARY_VI,
)
from juli_backend.services.agent.tools.product import (
    ProductToolContext,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    precheck_update_product_listing,
    register_product_write_tools,
)
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.shop_rules.listing_edits import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
)
from juli_backend.services.shop_rules.listing_validator import (
    DESCRIPTION_MIN_TEXT_CHARS,
    ListingViolationCode,
    description_text,
    missing_tokens,
    must_keep_tokens,
    validate_listing_proposal,
)

Code = ListingViolationCode

CURRENT_TITLE = "Nước Ngọt Coca Cola Vị Nguyên Bản 270mL Thùng 24 Lon Chính Hãng"
_SENTENCE = "Nước ngọt có ga vị nguyên bản, uống lạnh ngon hơn, dùng cho tiệc và gia đình. "
CURRENT_DESCRIPTION = (
    "<p><strong>Thông tin sản phẩm</strong></p>"
    f"<p>{_SENTENCE * 6}</p>"
    "<ul><li>Dung tích 270mL mỗi lon</li><li>Thùng 24 lon</li></ul>"
    f"<p>{_SENTENCE * 3}</p>"
)
GOOD_TITLE = "Nước Ngọt Coca Cola Vị Nguyên Bản 270mL Thùng 24 Lon Chính Hãng Giao Nhanh"
GOOD_DESCRIPTION = CURRENT_DESCRIPTION + "<p>Bảo quản nơi khô ráo, tránh ánh nắng trực tiếp.</p>"
BRAND = ("Coca Cola",)


def _codes(**overrides: Any) -> set[Code]:
    args: dict[str, Any] = {
        "current_title": CURRENT_TITLE,
        "current_description_html": CURRENT_DESCRIPTION,
        "proposed_title": GOOD_TITLE,
        "proposed_description_html": GOOD_DESCRIPTION,
        "flagged_codes": (),
        "brand_terms": BRAND,
    }
    args.update(overrides)
    return {violation.code for violation in validate_listing_proposal(**args).violations}


def test_the_fixture_description_is_long_enough():
    assert len(description_text(CURRENT_DESCRIPTION)) >= DESCRIPTION_MIN_TEXT_CHARS
    assert _codes() == set()


# -- every rule: one pass, one fail ---------------------------------------------------------

_LONG_DESC_ONE_BLOCK = "<p>" + _SENTENCE * 8 + "</p>"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, set(), id="good-proposal-passes"),
        pytest.param(
            {
                "current_title": None,
                "current_description_html": None,
                "proposed_title": "Áo thun nam cotton 100% cổ tròn",
            },
            {Code.TITLE_TOO_SHORT},
            id="title-under-40",
        ),
        pytest.param(
            {"current_title": None, "proposed_title": "A" * TITLE_MIN_CHARS},
            set(),
            id="title-exactly-40",
        ),
        pytest.param(
            {"current_title": None, "proposed_title": "A" * (TITLE_MAX_CHARS + 1)},
            {Code.TITLE_TOO_LONG},
            id="title-over-255",
        ),
        pytest.param(
            {"current_title": "B" * 100, "proposed_title": "B" * 79},
            {Code.TITLE_SHRUNK},
            id="title-under-80pct-of-current",
        ),
        pytest.param(
            {"current_title": "B" * 100, "proposed_title": "B" * 80},
            set(),
            id="title-at-80pct-of-current",
        ),
        pytest.param(
            {
                "proposed_title": (
                    "Nước Ngọt Coca Cola Vị Nguyên Bản Thùng 24 Lon Chính Hãng Mát Lạnh"
                )
            },
            {Code.TITLE_MISSING_TOKENS},
            id="title-drops-270mL",
        ),
        pytest.param(
            {"proposed_description_html": GOOD_DESCRIPTION.replace(_SENTENCE * 3, _SENTENCE, 1)},
            {Code.DESCRIPTION_SHORTER_THAN_CURRENT},
            id="description-shorter-than-current",
        ),
        pytest.param(
            {
                "current_description_html": "<p>Ngắn.</p>",
                "proposed_description_html": "<p>Ngắn.</p><p>Dài hơn một chút.</p>",
            },
            {Code.DESCRIPTION_TOO_SHORT},
            id="description-under-500",
        ),
        pytest.param(
            {"current_description_html": None, "proposed_description_html": _LONG_DESC_ONE_BLOCK},
            {Code.DESCRIPTION_NO_LINE_BREAK},
            id="description-one-block",
        ),
        pytest.param(
            {
                "current_description_html": None,
                "proposed_description_html": _LONG_DESC_ONE_BLOCK + "<p>Đoạn hai.</p>",
            },
            set(),
            id="description-two-paragraphs",
        ),
        pytest.param(
            {
                "current_description_html": None,
                "proposed_description_html": "<p>" + _SENTENCE * 8 + "<br>dòng hai</p>",
            },
            set(),
            id="description-br-line-break",
        ),
        pytest.param(
            {
                "current_description_html": None,
                "proposed_description_html": "<p>a</p><p>" + "x" * DESCRIPTION_MAX_CHARS + "</p>",
            },
            {Code.DESCRIPTION_TOO_LONG},
            id="description-over-10000",
        ),
        pytest.param(
            {"proposed_title": None, "proposed_description_html": None},
            set(),
            id="nothing-proposed",
        ),
    ],
)
def test_each_rule(overrides: dict[str, Any], expected: set[Code]):
    assert _codes(**overrides) == expected


@pytest.mark.parametrize(
    ("current_title", "current_description"),
    [
        pytest.param("T" * (TITLE_MAX_CHARS + 1), CURRENT_DESCRIPTION, id="title-over"),
        pytest.param(CURRENT_TITLE, "<p>" + "x" * DESCRIPTION_MAX_CHARS + "</p>", id="desc-over"),
    ],
)
def test_a_listing_already_over_limits_is_refused_and_left_unedited(
    current_title: str, current_description: str
):
    result = validate_listing_proposal(
        current_title, current_description, GOOD_TITLE, GOOD_DESCRIPTION, (), BRAND
    )
    (violation,) = result.violations
    assert violation.code is Code.LISTING_OVER_LIMITS and violation.field == "listing"
    assert "conclude without changes" in violation.message
    assert "không sửa" in violation.message_vi


def test_every_violation_has_an_english_and_a_vietnamese_message():
    result = validate_listing_proposal(
        CURRENT_TITLE, CURRENT_DESCRIPTION, "Coca", "<p>ngắn</p>", (), BRAND
    )
    assert {v.code for v in result.violations} >= {
        Code.TITLE_TOO_SHORT,
        Code.TITLE_SHRUNK,
        Code.TITLE_MISSING_TOKENS,
        Code.DESCRIPTION_SHORTER_THAN_CURRENT,
        Code.DESCRIPTION_TOO_SHORT,
        Code.DESCRIPTION_NO_LINE_BREAK,
    }
    for violation in result.violations:
        assert violation.message and violation.message_vi
        assert violation.message != violation.message_vi


# -- must-keep tokens -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "keys"),
    [
        ("Nước Coca 270mL Thùng 24 Lon x2", ["brand:coca cola", "270ml", "thung24lon", "x2"]),
        ("Sữa tắm 1,5 lít 100% thiên nhiên 12 Chai", ["1.5l", "100%", "12chai"]),
        ("Bình giữ nhiệt 500 ml 2x", ["500ml", "x2"]),
        ("Áo thun mẫu 2024 size M", []),
    ],
)
def test_must_keep_tokens_are_brand_terms_and_quantities(title: str, keys: list[str]):
    brand = ("Coca Cola",) if "Coca" in title else ()
    title = title.replace("Coca", "Coca Cola")
    assert [token.key for token in must_keep_tokens(title, brand)] == keys


@pytest.mark.parametrize(
    ("current", "proposed"),
    [
        pytest.param("Nước 270mL", "nước 270 ML mát lạnh", id="case-and-spacing"),
        pytest.param("Sữa 1,5 lít", "Sữa 1.5L", id="decimal-comma-and-lit"),
        pytest.param("Thùng 24 Lon bia", "bia THUNG 24 lon", id="diacritics"),
        pytest.param("Coca Cola 330ml", "COCA  COLA 330 mL", id="brand-case-and-spaces"),
        pytest.param("Hộp x2", "Hộp 2x", id="multiplier-order"),
    ],
)
def test_must_keep_normalisation_keeps_equivalent_spellings(current: str, proposed: str):
    assert missing_tokens(current, proposed, ("Coca Cola",)) == []


@pytest.mark.parametrize(
    ("current", "proposed", "missing"),
    [
        ("Nước 270mL", "Nước 330mL", "270mL"),
        ("Coca Cola 330ml", "Nước ngọt 330ml", "Coca Cola"),
        ("Sữa 12 Chai", "Sữa 12 lon", "12 Chai"),
        ("Sữa 1,5 lít", "Sữa 15 lít", "1,5 lít"),
    ],
)
def test_a_dropped_or_changed_token_is_missing(current: str, proposed: str, missing: str):
    assert [token.text for token in missing_tokens(current, proposed, ("Coca Cola",))] == [missing]


# -- warn-only: drift and claim words -------------------------------------------------------


def test_drift_is_logged_and_flagged_but_never_a_violation(caplog: pytest.LogCaptureFixture):
    drifted_title = "Thức Uống Giải Khát Có Gas Coca Cola 270mL Thùng 24 Lon Tiện Lợi Cho Gia Đình"
    with caplog.at_level(logging.WARNING, logger="juli_backend.services.shop_rules"):
        result = validate_listing_proposal(
            CURRENT_TITLE, CURRENT_DESCRIPTION, drifted_title, None, ("SEO_DIAGNOSTIC_ITEM",), BRAND
        )
    assert result.ok
    assert result.drift.title_drifted and result.drift.title_overlap is not None
    assert result.drift.title_overlap < 0.7
    (record,) = [r for r in caplog.records if r.getMessage() == "listing_proposal_drift"]
    assert record.__dict__["blocking"] is False
    assert record.__dict__["flagged_codes"] == ["SEO_DIAGNOSTIC_ITEM"]


def test_a_close_proposal_does_not_drift(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="juli_backend.services.shop_rules"):
        result = validate_listing_proposal(
            CURRENT_TITLE, CURRENT_DESCRIPTION, GOOD_TITLE, GOOD_DESCRIPTION, (), BRAND
        )
    assert result.ok and not result.drift.title_drifted and not result.drift.description_drifted
    assert not [r for r in caplog.records if r.getMessage() == "listing_proposal_drift"]


def test_an_added_claim_word_is_warned_not_blocked():
    result = validate_listing_proposal(
        CURRENT_TITLE, CURRENT_DESCRIPTION, GOOD_TITLE + " Tốt Nhất", None, (), BRAND
    )
    assert result.ok and result.drift.claim_words_added == ("tot nhat",)


# -- the precheck wiring --------------------------------------------------------------------

DETAIL = {
    "title": CURRENT_TITLE,
    "description": CURRENT_DESCRIPTION,
    "brand": {"id": "1", "name": "Coca Cola"},
}


def _context(detail: dict[str, Any] | None = None) -> ProductToolContext:
    return ProductToolContext(product_id="prod-1", product_detail=detail or DETAIL)


def test_precheck_passes_a_good_proposal():
    params = UpdateProductListingInput(title=GOOD_TITLE, description=GOOD_DESCRIPTION)
    assert precheck_update_product_listing(None, _context(), params) is None


def test_precheck_refuses_with_every_violation_for_the_model():
    params = UpdateProductListingInput(title="Nước ngọt Coca Cola thùng lớn")
    refusal = precheck_update_product_listing(None, _context(), params)
    assert refusal is not None
    assert refusal.error_code == ERROR_RULE_VIOLATION
    assert refusal.summary_vi == RULE_REFUSAL_SUMMARY_VI
    for code in (Code.TITLE_TOO_SHORT, Code.TITLE_SHRUNK, Code.TITLE_MISSING_TOKENS):
        assert f"[{code.value}]" in refusal.model_hint
    assert "270mL" in refusal.model_hint
    assert refusal.final_summary_vi is not None
    assert refusal.final_summary_vi.startswith(RULE_REFUSAL_FINAL_VI)


def test_precheck_drops_the_brand_from_the_product_detail():
    title = GOOD_TITLE.replace("Coca Cola ", "")
    refusal = precheck_update_product_listing(
        None, _context(), UpdateProductListingInput(title=title)
    )
    assert refusal is not None and '"Coca Cola"' in refusal.model_hint


def test_precheck_refuses_an_over_limits_listing():
    detail = {**DETAIL, "description": "<p>" + "x" * DESCRIPTION_MAX_CHARS + "</p>"}
    refusal = precheck_update_product_listing(
        None, _context(detail), UpdateProductListingInput(title=GOOD_TITLE)
    )
    assert refusal is not None and "[listing_over_limits]" in refusal.model_hint


# -- the runner: one retry, then refuse -----------------------------------------------------


class _Store:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states[workflow_run_id]
        state.prompt_version = state.prompt_version or "optimize_product.v1"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState, **_: Any) -> None:
        self.states[workflow_run_id] = state


class _PrecheckExecutor:
    """Runs the real listing precheck; records any dispatch (there must be none)."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def precheck(self, *, tool_name: str, params: Any) -> dict[str, Any] | None:
        if tool_name != "update_product_listing":
            return None
        refusal = precheck_update_product_listing(None, _context(), params)
        return None if refusal is None else refusal.model_dump(mode="json")

    def execute(self, *, tool_name: str, params: Any, tool_call_id: str | None = None) -> dict:
        self.executed.append(tool_name)
        return {"ok": True}


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(0, 0))


def _listing_call(call_id: str, title: str) -> ToolCallBlock:
    return ToolCallBlock(
        call_id=call_id, tool_name="update_product_listing", arguments={"title": title}
    )


BAD_TITLE = "Nước ngọt Coca Cola thùng lớn"


async def _run(script: list[AssistantTurn]) -> tuple[Any, _Store, InMemoryEventSink, Any]:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    store, sink, executor = _Store(), InMemoryEventSink(), _PrecheckExecutor()
    run_id = uuid.uuid4()
    store.states[run_id] = RunState()
    runner = WorkflowRunner(
        llm_service=FakeLLMService(script=script),
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        clock=lambda: 0.0,
    )
    result = await runner.run(run_id, product_ref="prod-1")
    assert executor.executed == []
    return result, store.states[run_id], sink, run_id


def _completed(sink: InMemoryEventSink) -> list[Any]:
    return [e.payload for e in sink.events if e.event_type == "tool.completed"]


async def test_fail_then_fix_reaches_the_seller():
    result, state, sink, _ = await _run(
        [
            _turn(_listing_call("c1", BAD_TITLE)),
            _turn(_listing_call("c2", GOOD_TITLE)),
        ]
    )
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    assert state.pending_confirmation["arguments"]["title"] == GOOD_TITLE
    assert state.proposal_refusals == {"update_product_listing": 1}
    (refused,) = _completed(sink)
    assert refused.ok is False and refused.summary == RULE_REFUSAL_SUMMARY_VI
    tool_message = next(m for m in state.conversation_window if m.get("role") == "tool")
    error = tool_message["content"]["error"]
    assert error["retryable"] is True and "[title_missing_tokens]" in error["message"]


async def test_fail_then_fail_refuses_even_with_text_between_the_drafts():
    """A TextBlock resets the malformed streak; the per-tool count is not reset."""
    result, state, sink, _ = await _run(
        [
            _turn(_listing_call("c1", BAD_TITLE)),
            _turn(TextBlock(text="Juli soạn lại."), _listing_call("c2", BAD_TITLE + " mới")),
            _turn(FinalResponse(content="never reached")),
        ]
    )
    assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
    assert result.status == WorkflowRunStatus.FAILED
    assert state.pending_confirmation is None
    assert not [e for e in sink.events if e.event_type == "workflow.approval_required"]
    first, second = _completed(sink)
    assert first.summary == RULE_REFUSAL_SUMMARY_VI
    assert second.summary.startswith(RULE_REFUSAL_FINAL_VI)
    last_tool = [m for m in state.conversation_window if m.get("role") == "tool"][-1]
    assert last_tool["content"]["error"]["retryable"] is False


def test_the_refusal_count_survives_the_state_round_trip():
    state = RunState(proposal_refusals={"update_product_listing": 1})
    assert RunState.from_dict(state.to_dict()).proposal_refusals == {"update_product_listing": 1}
    assert "proposal_refusals" not in RunState().to_dict()


def test_a_revert_run_is_not_gated_by_the_post_validator():
    """A "Hoàn tác" run puts back the seller's own earlier title, however short."""
    context = ProductToolContext(product_id="prod-1", product_detail=DETAIL, reverting=True)
    params = UpdateProductListingInput(title="Nồi lẩu điện mini 1.5L")
    assert precheck_update_product_listing(None, context, params) is None
