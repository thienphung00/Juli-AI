"""Fast track P76-6 (D78): the model proposes listing edits as operations.

Through the real `ProductToolExecutor` (its resolver, precheck and diagnoses capture)
and the real `WorkflowRunner`, with a scripted model and a fake TikTok bundle:

* edits are applied to the current listing and the seller is shown -- and the write
  would send -- the applied full title / description, never the operations;
* an `EditRejection` (here `old_not_found`) is refused like a validator violation:
  one redraft, then the run ends (`RunState.proposal_refusals`);
* the product's TikTok-flagged codes reach `apply_ops` (an appended section needs a
  flagged code) and the post-validator.

Synthetic listing only: no real shop, brand or product.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools import product_write
from juli_backend.services.agent.tools.listing_rules import (
    ERROR_LISTING_EDIT_REJECTED,
    RULE_REFUSAL_FINAL_VI,
    RULE_REFUSAL_SUMMARY_VI,
)
from juli_backend.services.agent.tools.product import (
    ProductToolContext,
    description_sections,
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

PRODUCT_ID = "prod-synthetic-1"
TITLE = "Bình Giữ Nhiệt BrandX Inox 500ml Giữ Lạnh 12 Giờ Màu Xanh"
_SENTENCE = "Bình giữ nhiệt bằng inox hai lớp, giữ nước lạnh lâu, nắp kín không rò rỉ. "
DESCRIPTION = (
    "<p><strong>Thông tin sản phẩm</strong></p>"
    f"<p>{_SENTENCE * 7}</p>"
    "<ul><li>Dung tích 500ml</li><li>Giữ lạnh 12 giờ</li></ul>"
)
DETAIL = {
    "id": PRODUCT_ID,
    "title": TITLE,
    "description": DESCRIPTION,
    "brand": {"id": "1", "name": "BrandX"},
}
DESC_CODE = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
TITLE_CODE = "TITLE_KEYWORDS_MISSING"


class _Products:
    def __init__(self, flagged: tuple[str, ...] = (DESC_CODE,)) -> None:
        self.flagged = flagged
        self.detail_reads = 0
        self.diagnosis_reads = 0

    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        self.detail_reads += 1
        return dict(DETAIL)

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        self.diagnosis_reads += 1
        results = [{"code": code} for code in self.flagged]
        return {
            "products": [
                {
                    "id": PRODUCT_ID,
                    "diagnoses": [{"field": "DESCRIPTION", "diagnosis_results": results}],
                }
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


def _diagnoses_call(call_id: str = "d1") -> ToolCallBlock:
    return ToolCallBlock(call_id=call_id, tool_name="get_product_diagnoses", arguments={})


def _edits_call(call_id: str, edits: dict[str, Any]) -> ToolCallBlock:
    # The strict-mode shape: every field present, the ones left out are null.
    return ToolCallBlock(
        call_id=call_id,
        tool_name="update_product_listing",
        arguments={
            "title": None,
            "description": None,
            "attach_staged_image": None,
            "edits": edits,
        },
    )


GOOD_EDITS: dict[str, Any] = {
    "title_ops": [
        {
            "op": "replace_title_span",
            "old": "Màu Xanh",
            "new": "Màu Xanh Rêu Nắp Bật",
            "reason_code": TITLE_CODE,
        }
    ],
    "description_ops": [
        {
            "op": "append_section",
            "heading": "Hướng dẫn sử dụng",
            "body": "Rửa sạch trước khi dùng lần đầu.\nKhông dùng trong lò vi sóng.",
            "reason_code": DESC_CODE,
        }
    ],
}
NOT_FOUND_EDITS: dict[str, Any] = {
    "title_ops": [
        {"op": "replace_title_span", "old": "Màu Đỏ", "new": "Màu Hồng", "reason_code": TITLE_CODE}
    ],
    "description_ops": [],
}


async def _run(
    script: list[AssistantTurn], products: _Products
) -> tuple[Any, RunState, InMemoryEventSink]:
    store, sink = _Store(), InMemoryEventSink()
    registry = _registry()
    executor = ProductToolExecutor(
        registry=registry, read_resources=_Resources(products), product_id=PRODUCT_ID
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


def _tool_errors(state: RunState) -> list[dict[str, Any]]:
    return [
        message["content"]["error"]
        for message in state.conversation_window
        if message.get("role") == "tool" and "error" in (message.get("content") or {})
    ]


# -- success: the seller is shown the applied text --------------------------------------


async def test_edits_are_applied_and_the_seller_confirms_the_full_text():
    products = _Products()
    result, state, sink = await _run(
        [_turn(_diagnoses_call()), _turn(_edits_call("c1", GOOD_EDITS))], products
    )
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    arguments = state.pending_confirmation["arguments"]
    assert "edits" not in arguments
    assert (
        arguments["title"]
        == "Bình Giữ Nhiệt BrandX Inox 500ml Giữ Lạnh 12 Giờ Màu Xanh Rêu Nắp Bật"
    )
    description = arguments["description"]
    assert _SENTENCE.strip() in description  # the seller's text, kept word for word
    assert description.index("Dung tích 500ml") < description.index("Hướng dẫn sử dụng")
    assert "Không dùng trong lò vi sóng." in description
    (approval,) = [e for e in sink.events if e.event_type == "workflow.approval_required"]
    # The consent panel's rows come from `proposed_change`: the applied text, no ops.
    assert approval.payload.proposed_change == arguments
    (option,) = approval.payload.options
    assert option.proposed_change == arguments
    assert state.proposal_refusals == {}
    # The codes the model read were reused: no second diagnoses read.
    assert products.diagnosis_reads == 1


async def test_a_resumed_write_of_the_resolved_params_sends_the_applied_text():
    resolution = resolve_update_product_listing(
        _Resources(_Products()),
        ProductToolContext(product_id=PRODUCT_ID, flagged_codes=(DESC_CODE,)),
        UpdateProductListingInput(edits=ListingEditOps.model_validate(GOOD_EDITS)),
    )
    assert resolution is not None and resolution.params is not None
    dumped = resolution.params.model_dump(mode="json")
    assert set(dumped) == {"title", "description", "attach_staged_image"}
    reparsed = UpdateProductListingInput.model_validate(dumped)
    context = ProductToolContext(
        product_id=PRODUCT_ID,
        product_detail={
            **DETAIL,
            "main_images": [{"uri": "u"}],
            "category_chains": [{"id": "9", "is_leaf": True}],
        },
    )
    body = product_write._build_listing_edit_body(reparsed, context)
    assert body["title"] == dumped["title"] and body["description"] == dumped["description"]


# -- old_not_found: one redraft, then refuse --------------------------------------------


async def test_old_not_found_gets_one_redraft_then_the_run_ends():
    result, state, sink = await _run(
        [
            _turn(_diagnoses_call()),
            _turn(_edits_call("c1", NOT_FOUND_EDITS)),
            _turn(_edits_call("c2", NOT_FOUND_EDITS)),
            _turn(FinalResponse(content="never reached")),
        ],
        _Products(),
    )
    assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
    assert state.pending_confirmation is None
    assert state.proposal_refusals == {"update_product_listing": 2}
    first, second = _tool_errors(state)
    assert first["retryable"] is True and second["retryable"] is False
    assert f"error_code={ERROR_LISTING_EDIT_REJECTED}: [old_not_found]" in first["message"]
    assert "title operation 0" in first["message"]
    completed = [e.payload for e in sink.events if e.event_type == "tool.completed"]
    refusals = [p for p in completed if p.tool_name == "update_product_listing"]
    assert [p.summary for p in refusals] == [RULE_REFUSAL_SUMMARY_VI, RULE_REFUSAL_FINAL_VI]
    assert not [e for e in sink.events if e.event_type == "workflow.approval_required"]


async def test_old_not_found_then_fixed_edits_reach_the_seller():
    result, state, _ = await _run(
        [
            _turn(_diagnoses_call()),
            _turn(_edits_call("c1", NOT_FOUND_EDITS)),
            _turn(_edits_call("c2", GOOD_EDITS)),
        ],
        _Products(),
    )
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    assert state.proposal_refusals == {"update_product_listing": 1}


# -- flagged codes ----------------------------------------------------------------------


async def test_an_append_for_a_code_tiktok_did_not_flag_is_refused():
    products = _Products(flagged=("DESC_NO_NEW_LINE",))
    result, state, _ = await _run(
        [
            _turn(_diagnoses_call()),
            _turn(_edits_call("c1", GOOD_EDITS)),
            _turn(_edits_call("c2", GOOD_EDITS)),
        ],
        products,
    )
    assert result.stop_reason != StopReason.PAUSED_FOR_CONFIRMATION
    (error, *_) = _tool_errors(state)
    assert "[append_code_not_flagged]" in error["message"]


async def test_flagged_codes_are_read_once_when_the_model_skipped_the_diagnoses_step():
    products = _Products()
    result, _, _ = await _run([_turn(_edits_call("c1", GOOD_EDITS))], products)
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    assert products.diagnosis_reads == 1


async def test_unreadable_diagnoses_fail_closed_for_an_append():
    class _Failing(_Products):
        def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
            from juli_backend.integrations.tiktok import TikTokAPIError

            raise TikTokAPIError(code=1, message="down")

    result, state, _ = await _run(
        [_turn(_edits_call("c1", GOOD_EDITS)), _turn(_edits_call("c2", GOOD_EDITS))],
        _Failing(),
    )
    assert result.stop_reason != StopReason.PAUSED_FOR_CONFIRMATION
    assert "[append_code_not_flagged]" in _tool_errors(state)[0]["message"]


def test_the_post_validator_receives_the_flagged_codes(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}
    real = product_write.validate_listing_proposal

    def spy(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(product_write, "validate_listing_proposal", spy)
    context = ProductToolContext(
        product_id=PRODUCT_ID, product_detail=DETAIL, flagged_codes=(DESC_CODE, TITLE_CODE)
    )
    precheck_update_product_listing(None, context, UpdateProductListingInput(title=TITLE))
    assert tuple(seen["flagged_codes"]) == (DESC_CODE, TITLE_CODE)


# -- resolver refusals that never reach apply_ops ---------------------------------------


@pytest.mark.parametrize(
    ("params", "code"),
    [
        (
            UpdateProductListingInput(
                title=TITLE, edits=ListingEditOps(title_ops=[], description_ops=[])
            ),
            "edits_with_text",
        ),
        (
            UpdateProductListingInput(edits=ListingEditOps(title_ops=[], description_ops=[])),
            "edits_change_nothing",
        ),
    ],
)
def test_resolver_refusals_name_their_code(params: UpdateProductListingInput, code: str):
    context = ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL, flagged_codes=())
    resolution = resolve_update_product_listing(None, context, params)
    assert resolution is not None and resolution.refusal is not None
    assert f"[{code}]" in resolution.refusal.model_hint


def test_a_whole_text_proposal_is_left_to_the_precheck():
    context = ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL)
    assert (
        resolve_update_product_listing(None, context, UpdateProductListingInput(title=TITLE))
        is None
    )


# -- the sections the model addresses ---------------------------------------------------


def test_description_sections_number_the_sections_edit_ops_address():
    sections = description_sections(DESCRIPTION)
    assert sections is not None
    kinds = [(item["index"], item["kind"]) for item in sections["items"]]
    assert kinds == [(0, "heading"), (1, "paragraph"), (2, "list")]
    assert sections["items"][2]["text"] == {
        "source": "vendor",
        "text": "Dung tích 500ml\nGiữ lạnh 12 giờ",
    }
    assert description_sections("") is None


def test_description_sections_stay_within_their_budget():
    html = "".join(f"<p>{'đoạn văn ' * 60}{i}</p>" for i in range(30))
    sections = description_sections(html)
    assert sections is not None and sections["truncated"] is True
    assert sections["omitted_count"] + len(sections["items"]) == 30
