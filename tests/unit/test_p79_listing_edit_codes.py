"""Fast track P79: the codes a listing edit may cite = TikTok's ∪ Juli's own check.

Live sandbox run dbd17987 (30/10, edge case D33): Juli's listing evidence raised the
card (title 31 characters, a one-line ~80-character description) but TikTok's diagnoses
lagged and returned only ``MAIN_IMG_NUMBER_LESS_THAN_FIVE``; the model put that image
code on a title op, was refused twice and the run wrote nothing.

Replayed here through the real `WorkflowRunner` and `ProductToolExecutor` with a
scripted model and a fake TikTok bundle:

* the product read lists, per field, the codes an edit may cite, with their source
  (``tiktok`` / ``juli_check``), and the image code as not usable for text;
* an edit citing Juli's own title / description codes passes the resolver and the
  post-validator and pauses for the seller's consent;
* a wrong-field code is refused with the allowed codes named, and the retry succeeds;
* image-only codes on a listing whose text already meets TikTok's rules end the run
  cleanly (``concluded_without_changes``) with the seller-facing Vietnamese line.

Synthetic listing only: no real shop, brand or product.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.sanitize import load_banned_patterns
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools.listing_codes import (
    SOURCE_JULI_CHECK,
    SOURCE_TIKTOK,
    card_evidence_from_payload,
    edit_codes,
    local_text_codes,
)
from juli_backend.services.agent.tools.listing_rules import (
    ERROR_LISTING_EDIT_REJECTED,
    LISTING_NEEDS_PHOTOS_VI,
)
from juli_backend.services.agent.tools.product import (
    ProductToolContext,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    precheck_update_product_listing,
    register_product_write_tools,
    resolve_update_product_listing,
)
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.shop_rules.listing_structure import ListingEditOps

PRODUCT_ID = "prod-synthetic-79"
IMAGE_CODE = "MAIN_IMG_NUMBER_LESS_THAN_FIVE"
TITLE_CODE = "TITLE_LESS_THAN_40_CHARACTERS"
DESC_SHORT = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
DESC_ONE_BLOCK = "DESC_NO_NEW_LINE"

# The live shape: a 31-character title, one ~80-character sentence, no line break.
SHORT_TITLE = "Bình Giữ Nhiệt Inox 500ml Xanh "[:31]
SHORT_DESCRIPTION = "Bình giữ nhiệt inox hai lớp, giữ lạnh lâu, nắp kín không rò rỉ khi mang đi."
SHORT_DETAIL = {"id": PRODUCT_ID, "title": SHORT_TITLE, "description": SHORT_DESCRIPTION}

_SENTENCE = "Bình giữ nhiệt bằng inox hai lớp, giữ nước lạnh lâu, nắp kín không rò rỉ. "
CLEAN_DETAIL = {
    "id": PRODUCT_ID,
    "title": "Bình Giữ Nhiệt Inox 500ml Giữ Lạnh 12 Giờ Màu Xanh Rêu",
    "description": (
        "<p><strong>Thông tin sản phẩm</strong></p>"
        f"<p>{_SENTENCE * 7}</p>"
        "<ul><li>Dung tích 500ml</li><li>Giữ lạnh 12 giờ</li></ul>"
    ),
}


class _Products:
    def __init__(self, detail: dict[str, Any], flagged: tuple[str, ...] = (IMAGE_CODE,)) -> None:
        self.detail = detail
        self.flagged = flagged
        self.diagnosis_reads = 0

    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        return dict(self.detail)

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        self.diagnosis_reads += 1
        results = [{"code": code} for code in self.flagged]
        return {
            "products": [
                {"id": PRODUCT_ID, "diagnoses": [{"field": "IMAGE", "diagnosis_results": results}]}
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


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(0, 0))


def _read(call_id: str, tool_name: str) -> ToolCallBlock:
    return ToolCallBlock(call_id=call_id, tool_name=tool_name, arguments={})


def _conclude() -> ToolCallBlock:
    return ToolCallBlock(
        call_id="z1", tool_name="conclude_without_changes", arguments={"reason": "read only"}
    )


def _edits_call(call_id: str, edits: dict[str, Any]) -> ToolCallBlock:
    return ToolCallBlock(
        call_id=call_id,
        tool_name="update_product_listing",
        arguments={"title": None, "description": None, "attach_staged_image": None, "edits": edits},
    )


def _title_op(reason_code: str) -> dict[str, Any]:
    return {
        "op": "replace_title_span",
        "old": "Xanh",
        "new": "Xanh Rêu Giữ Lạnh 12 Giờ Nắp Bật",
        "reason_code": reason_code,
    }


_BODY_LINE = "Rửa sạch bình bằng nước ấm trước khi dùng lần đầu, không dùng trong lò vi sóng."
VALID_EDITS: dict[str, Any] = {
    "title_ops": [_title_op(TITLE_CODE)],
    "description_ops": [
        {
            "op": "append_section",
            "heading": "Hướng dẫn sử dụng",
            "body": "\n".join([_BODY_LINE] * 6),
            "reason_code": DESC_SHORT,
        }
    ],
}
WRONG_FIELD_EDITS: dict[str, Any] = {
    "title_ops": [_title_op(IMAGE_CODE)],
    "description_ops": [],
}


async def _run(
    script: list[AssistantTurn], products: _Products, *, card_evidence: tuple = ()
) -> tuple[Any, RunState, InMemoryEventSink]:
    store, sink = _Store(), InMemoryEventSink()
    registry = _registry()
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=_Resources(products),
        product_id=PRODUCT_ID,
        card_evidence=card_evidence,
    )
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
    result = await runner.run(run_id, product_ref=PRODUCT_ID)
    return result, store.states[run_id], sink


def _tool_result(state: RunState, tool_name: str) -> dict[str, Any]:
    (content,) = [
        m["content"]
        for m in state.conversation_window
        if m.get("role") == "tool" and m.get("tool_name") == tool_name
    ]
    return content


def _tool_errors(state: RunState) -> list[dict[str, Any]]:
    return [
        message["content"]["error"]
        for message in state.conversation_window
        if message.get("role") == "tool" and "error" in (message.get("content") or {})
    ]


# -- the live scenario, replayed --------------------------------------------------------


async def test_stale_image_only_diagnosis_still_lets_juli_codes_edit_the_text():
    products = _Products(SHORT_DETAIL)
    result, state, sink = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", VALID_EDITS)),
        ],
        products,
    )
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    # What the model read before proposing: per field, with the source of each code.
    assert _tool_result(state, "get_product_information")["edit_codes"] == {
        "title_codes": [{"code": TITLE_CODE, "source": SOURCE_JULI_CHECK}],
        "description_codes": [
            {"code": DESC_SHORT, "source": SOURCE_JULI_CHECK},
            {"code": DESC_ONE_BLOCK, "source": SOURCE_JULI_CHECK},
        ],
        "not_for_text": [IMAGE_CODE],
        "tiktok_read": True,
    }
    arguments = state.pending_confirmation["arguments"]
    assert arguments["title"].startswith(SHORT_TITLE.rstrip())
    assert len(arguments["title"]) >= 40
    assert "Hướng dẫn sử dụng" in arguments["description"]
    assert state.proposal_refusals == {}
    assert products.diagnosis_reads == 1  # the run's own read was reused
    assert [e for e in sink.events if e.event_type == "workflow.approval_required"]


async def test_a_wrong_field_code_is_refused_with_the_allowed_codes_and_the_retry_passes():
    result, state, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_edits_call("c1", WRONG_FIELD_EDITS)),
            _turn(_edits_call("c2", VALID_EDITS)),
        ],
        _Products(SHORT_DETAIL),
    )
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    (error,) = _tool_errors(state)
    message = error["message"]
    assert f"error_code={ERROR_LISTING_EDIT_REJECTED}: [reason_code_wrong_field]" in message
    assert f"Allowed title reason codes: {TITLE_CODE} ({SOURCE_JULI_CHECK})." in message
    assert error["retryable"] is True
    assert state.proposal_refusals == {"update_product_listing": 1}


async def test_image_only_codes_on_a_clean_listing_end_the_run_cleanly():
    result, state, sink = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(
                _edits_call(
                    "c1",
                    {
                        "title_ops": [
                            {
                                "op": "replace_title_span",
                                "old": "Màu Xanh Rêu",
                                "new": "Màu Xanh",
                                "reason_code": IMAGE_CODE,
                            }
                        ],
                        "description_ops": [],
                    },
                )
            ),
            _turn(FinalResponse(content="never reached")),
        ],
        _Products(CLEAN_DETAIL),
    )
    assert result.stop_reason == StopReason.CONCLUDED_WITHOUT_CHANGES
    assert result.status == WorkflowRunStatus.COMPLETED
    assert _tool_result(state, "get_product_information")["edit_codes"] == {
        "title_codes": [],
        "description_codes": [],
        "not_for_text": [IMAGE_CODE],
        "tiktok_read": True,
    }
    assert state.pending_confirmation is None
    assert state.proposal_refusals == {}
    narrations = [
        e.payload.phase_narration for e in sink.events if e.event_type == "workflow.status"
    ]
    assert narrations[-1] == LISTING_NEEDS_PHOTOS_VI
    completed = [e.payload for e in sink.events if e.event_type == "tool.completed"]
    assert completed[-1].summary == LISTING_NEEDS_PHOTOS_VI and completed[-1].ok is False
    assert not [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert not [e for e in sink.events if e.event_type == "workflow.failed"]


async def test_an_unreadable_diagnosis_never_ends_the_run_as_needs_photos():
    class _Failing(_Products):
        def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
            from juli_backend.integrations.tiktok import TikTokAPIError

            raise TikTokAPIError(code=1, message="down")

    result, state, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_edits_call("c1", WRONG_FIELD_EDITS)),
            _turn(_edits_call("c2", WRONG_FIELD_EDITS)),
        ],
        _Failing(CLEAN_DETAIL),
    )
    assert result.stop_reason != StopReason.CONCLUDED_WITHOUT_CHANGES
    assert "[reason_code_wrong_field]" in _tool_errors(state)[0]["message"]


async def test_the_card_evidence_joins_the_codes_the_model_reads():
    card = ((TITLE_CODE, SOURCE_TIKTOK),)
    _, state, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_conclude()),
        ],
        _Products(CLEAN_DETAIL),
        card_evidence=card,
    )
    codes = _tool_result(state, "get_product_information")["edit_codes"]
    assert codes["title_codes"] == [{"code": TITLE_CODE, "source": SOURCE_TIKTOK}]


# -- unit: the union and the per-field listing ------------------------------------------


def test_local_text_codes_reuse_the_scan_thresholds():
    assert local_text_codes(SHORT_DETAIL) == (TITLE_CODE, DESC_SHORT, DESC_ONE_BLOCK)
    assert local_text_codes(CLEAN_DETAIL) == ()
    assert local_text_codes(None) == ()


def test_edit_codes_union_keeps_tiktok_first_and_one_entry_per_code():
    codes = edit_codes(
        tiktok_codes=(IMAGE_CODE, DESC_SHORT),
        detail=SHORT_DETAIL,
        card_evidence=((DESC_SHORT, SOURCE_JULI_CHECK), ("SEO_DIAGNOSTIC_ITEM", SOURCE_TIKTOK)),
    )
    assert codes.flagged == (
        IMAGE_CODE,
        DESC_SHORT,
        TITLE_CODE,
        DESC_ONE_BLOCK,
        "SEO_DIAGNOSTIC_ITEM",
    )
    assert codes.for_model() == {
        "title_codes": [
            {"code": TITLE_CODE, "source": SOURCE_JULI_CHECK},
            {"code": "SEO_DIAGNOSTIC_ITEM", "source": SOURCE_TIKTOK},
        ],
        "description_codes": [
            {"code": DESC_SHORT, "source": SOURCE_TIKTOK},
            {"code": DESC_ONE_BLOCK, "source": SOURCE_JULI_CHECK},
        ],
        "not_for_text": [IMAGE_CODE],
        "tiktok_read": True,
    }


def test_edit_codes_without_a_tiktok_read_is_not_a_fact_about_tiktok():
    codes = edit_codes(tiktok_codes=None, detail=CLEAN_DETAIL)
    assert codes.tiktok_read is False and not codes.has_text_code
    assert codes.allowed_line("title") == (
        "No title code is flagged on this product: leave the title unchanged."
    )


def test_card_evidence_is_read_from_the_card_payload():
    payload = {
        "diagnosis": {
            "lever": {
                "evidence": [
                    {"code": TITLE_CODE, "source": "local", "detail": "x"},
                    {"code": IMAGE_CODE, "source": "tiktok"},
                    {"code": "BAD", "source": "elsewhere"},
                    {"source": "tiktok"},
                ]
            }
        }
    }
    assert card_evidence_from_payload(json.dumps(payload)) == (
        (TITLE_CODE, SOURCE_JULI_CHECK),
        (IMAGE_CODE, SOURCE_TIKTOK),
    )
    assert card_evidence_from_payload("not json") == ()
    assert card_evidence_from_payload(None) == ()
    assert card_evidence_from_payload({"diagnosis": "x"}) == ()


def test_an_append_for_a_juli_check_code_is_applied_by_the_resolver():
    context = ProductToolContext(
        product_id=PRODUCT_ID, product_detail=SHORT_DETAIL, flagged_codes=(IMAGE_CODE,)
    )
    resolution = resolve_update_product_listing(
        None, context, UpdateProductListingInput(edits=ListingEditOps.model_validate(VALID_EDITS))
    )
    assert resolution is not None and resolution.params is not None


def test_the_post_validator_receives_the_union(monkeypatch: Any):
    from juli_backend.services.agent.tools import product_write

    seen: dict[str, Any] = {}
    real = product_write.validate_listing_proposal

    def spy(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(product_write, "validate_listing_proposal", spy)
    context = ProductToolContext(
        product_id=PRODUCT_ID, product_detail=SHORT_DETAIL, flagged_codes=(IMAGE_CODE,)
    )
    precheck_update_product_listing(None, context, UpdateProductListingInput(title=SHORT_TITLE))
    assert tuple(seen["flagged_codes"]) == (IMAGE_CODE, TITLE_CODE, DESC_SHORT, DESC_ONE_BLOCK)


async def test_an_unavailable_diagnosis_read_is_kept_as_not_read():
    class _Down(_Products):
        def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
            from juli_backend.integrations.tiktok import TikTokAPIError

            raise TikTokAPIError(code=1, message="down")

    _, state, _ = await _run(
        [
            _turn(_read("d1", "get_product_diagnoses")),
            _turn(_read("i1", "get_product_information")),
            _turn(_conclude()),
        ],
        _Down(SHORT_DETAIL),
    )
    assert _tool_result(state, "get_product_information")["edit_codes"]["tiktok_read"] is False


def test_the_needs_photos_line_is_clean_seller_copy():
    assert not [p.pattern for p in load_banned_patterns() if p.search(LISTING_NEEDS_PHOTOS_VI)]
