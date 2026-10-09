"""The cover-image and promotion runs: playbooks and deterministic planners (P10-B).

Like P8-C's "Hoàn tác" run (``services/run_changes/planner.py``), these are
ordinary ``workflow_runs`` executed by the ordinary ``WorkflowRunner`` -- same
tools, same ``tool.*`` / ``workflow.*`` SSE events, same CONFIRM consent and
ledger -- with a narrower playbook and a deterministic planner in place of the
LLM: nothing in these flows is a judgement call. Each planner is stateless per
turn (it decides from the conversation the runner hands it), so it survives the
waits and the consent, where the next leg runs in a fresh worker process.

When the run must wait for the seller, the planner raises ``AwaitSeller``;
``LeverFlowRunner`` turns that into ``WorkflowRunner.enter_external_wait``.

**Cover image** (``PHOTO_PLAYBOOK``): read TikTok's diagnoses → read the listing →
look at the current photo → *wait for the seller's photo* → stage it on TikTok
(``upload_product_image``, not yet visible on the listing) → consent
(``update_product_listing`` with the staged image, CONFIRM) → check the status.
The write is recorded before/after by P8-C's capture, so Hoàn tác restores the
old image.

**Promotion** (``PROMOTION_PLAYBOOK``): read the listing → read the promotions
already running → check the seller's rules (narrated) → *wait for the seller to
apply it on Seller Center* → on "Tôi đã áp dụng", look for it again, read-only →
found: done (the measurement clock starts at its start date); not found: wait
again with "Chưa tìm thấy trên TikTok". No write tool is in this playbook (D13).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.service import Message, ToolDefinition
from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    validate_playbook_tools,
)
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolPolicy, ToolRegistry
from juli_backend.services.lever_flows import promotion as promotion_module
from juli_backend.services.lever_flows.flows import (
    AWAITING_PHOTO,
    AWAITING_SELLER_ACTION,
    MAX_VERIFY_ROUNDS,
    NARRATION_AWAITING_PHOTO,
    NARRATION_AWAITING_SELLER,
    NARRATION_NOT_FOUND,
    PHOTO_WAIT_HOURS,
    PROMOTION_WAIT_HOURS,
    AwaitSeller,
)

DIAGNOSES_TOOL = "get_product_diagnoses"
READ_TOOL = "get_product_information"
INSPECT_TOOL = "inspect_product_image"
UPLOAD_TOOL = "upload_product_image"
WRITE_TOOL = "update_product_listing"
STATUS_TOOL = "check_product_status"
FIND_TOOL = "find_product_promotions"

PHOTO_PLAYBOOK = Playbook(
    workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
    version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
    steps=(
        PlaybookStep(
            step_id="photo-1",
            intent="Read TikTok's diagnoses and the listing, and look at the current cover photo.",
            tools=(DIAGNOSES_TOOL, READ_TOOL, INSPECT_TOOL),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="photo-2",
            intent="Stage the seller's checked photo on TikTok Shop; the listing is unchanged.",
            tools=(UPLOAD_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="photo-3",
            intent="Make the seller's photo the cover image, once the seller approves.",
            tools=(WRITE_TOOL,),
            policy=ToolPolicy.CONFIRM,
        ),
        PlaybookStep(
            step_id="photo-4",
            intent="Check the listing's status after the change.",
            tools=(STATUS_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
    ),
    # Seven planner turns end to end (three reads, stage, consent, status, the
    # closing sentence) across up to three worker legs: no extension narration.
    termination_policy=replace(
        OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        max_iterations=10,
        max_extensions=0,
        required_steps=(WRITE_TOOL,),
        terminal_tools=(),
        external_wait_timeout_h=PHOTO_WAIT_HOURS,
    ),
)

PROMOTION_PLAYBOOK = Playbook(
    workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
    version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
    steps=(
        PlaybookStep(
            step_id="promotion-1",
            intent="Read the product's price and the promotions it already has.",
            tools=(READ_TOOL, FIND_TOOL),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="promotion-2",
            intent=(
                "After the seller applies the promotion on Seller Center, look for it on "
                "TikTok, read-only."
            ),
            tools=(FIND_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
    ),
    # Three turns before the wait, then one or two per verification round, and
    # at most MAX_VERIFY_ROUNDS rounds: the cap never ends a healthy run.
    termination_policy=replace(
        OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        max_iterations=4 + 2 * MAX_VERIFY_ROUNDS,
        max_extensions=0,
        required_steps=(FIND_TOOL,),
        terminal_tools=(),
        external_wait_timeout_h=PROMOTION_WAIT_HOURS,
    ),
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


validate_playbook_tools(PHOTO_PLAYBOOK, _registry())
validate_playbook_tools(PROMOTION_PLAYBOOK, _registry())


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=0, output_tokens=0))


def _results(messages: Sequence[Message]) -> dict[str, list[Any]]:
    """tool name -> its results, in conversation order."""
    results: dict[str, list[Any]] = {}
    for message in messages:
        if isinstance(message, Mapping) and message.get("role") == "tool":
            results.setdefault(str(message.get("tool_name")), []).append(message.get("content"))
    return results


def _assistant_texts(messages: Sequence[Message]) -> list[str]:
    return [
        str(message.get("content"))
        for message in messages
        if isinstance(message, Mapping) and message.get("role") == "assistant"
    ]


def _declined(content: Any) -> bool:
    return (
        isinstance(content, Mapping)
        and isinstance(content.get("confirmation"), Mapping)
        and content["confirmation"].get("decision") == "declined"
    )


def _errored(content: Any) -> bool:
    return isinstance(content, Mapping) and ("error" in content or bool(content.get("conflict")))


@dataclass
class PhotoPlanner:
    """A deterministic ``LLMService`` for the cover-image run (module docstring).

    ``photo_ready`` is whether the seller's checked photo is stored; the worker
    knows, the conversation does not.
    """

    photo_ready: bool

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
        tool_choice: str | None = None,
    ) -> AssistantTurn:
        del system, tools, config, tool_choice  # deterministic: the flow decides
        results = _results(messages)
        if WRITE_TOOL in results:
            content = results[WRITE_TOOL][-1]
            if _declined(content):
                return _turn(
                    FinalResponse(
                        content=(
                            "Bạn đã chọn không thay ảnh. Lượt chạy kết thúc, ảnh bìa giữ nguyên."
                        )
                    )
                )
            if _errored(content):
                return _turn(
                    FinalResponse(content="Juli chưa thay được ảnh bìa. Ảnh bìa giữ nguyên.")
                )
            if STATUS_TOOL not in results:
                return _turn(ToolCallBlock(call_id="photo-status", tool_name=STATUS_TOOL))
            return _turn(
                FinalResponse(
                    content=(
                        "Đã thay ảnh bìa. Ảnh cũ đã được lưu — bạn có thể hoàn tác để dùng lại."
                    )
                )
            )
        if UPLOAD_TOOL in results:
            if _errored(results[UPLOAD_TOOL][-1]):
                return _turn(
                    FinalResponse(
                        content="Juli chưa tải được ảnh lên TikTok Shop. Ảnh bìa giữ nguyên."
                    )
                )
            return _turn(
                ToolCallBlock(
                    call_id="photo-write",
                    tool_name=WRITE_TOOL,
                    arguments={"attach_staged_image": True},
                )
            )
        if INSPECT_TOOL in results:
            if not self.photo_ready:
                raise AwaitSeller(awaiting=AWAITING_PHOTO, narration=NARRATION_AWAITING_PHOTO)
            return _turn(ToolCallBlock(call_id="photo-upload", tool_name=UPLOAD_TOOL))
        if READ_TOOL in results:
            if _errored(results[READ_TOOL][-1]):
                return _turn(
                    FinalResponse(
                        content=(
                            "Juli không đọc được sản phẩm từ TikTok Shop nên chưa thay ảnh. "
                            "Ảnh bìa giữ nguyên."
                        )
                    )
                )
            return _turn(ToolCallBlock(call_id="photo-inspect", tool_name=INSPECT_TOOL))
        if DIAGNOSES_TOOL in results:
            return _turn(ToolCallBlock(call_id="photo-read", tool_name=READ_TOOL))
        return _turn(ToolCallBlock(call_id="photo-diagnoses", tool_name=DIAGNOSES_TOOL))


def _shop_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=7)).date()


@dataclass
class PromotionPlanner:
    """A deterministic ``LLMService`` for a Seller Center promotion run.

    ``verify_round`` is how many "Tôi đã áp dụng" checks this run has made,
    this one included (0 on the first leg); ``LeverFlowRunner`` sets it before
    each verification leg. ``product_detail`` returns the raw listing the read
    step fetched (the concurrency guard holds it) -- the sanitized tool result
    carries no SKU ids, and the seller's caps are per SKU.
    """

    lever: str
    rules: promotion_module.PromotionRules
    product_detail: Callable[[], Mapping[str, Any] | None]
    verify_round: int = 0
    today: Callable[[], date] = _shop_today
    #: Set when a verification found the promotion: what was found.
    found: Mapping[str, Any] | None = field(default=None, init=False)
    proposal: promotion_module.PromotionProposal | None = field(default=None, init=False)

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
        tool_choice: str | None = None,
    ) -> AssistantTurn:
        del system, tools, config, tool_choice
        results = _results(messages)
        if READ_TOOL not in results:
            return _turn(ToolCallBlock(call_id="promotion-read", tool_name=READ_TOOL))
        if _errored(results[READ_TOOL][-1]):
            return _turn(
                FinalResponse(
                    content=(
                        "Juli không đọc được sản phẩm từ TikTok Shop nên chưa đề xuất khuyến mãi."
                    )
                )
            )
        finds = results.get(FIND_TOOL, [])
        if not finds:
            return _turn(
                ToolCallBlock(
                    call_id="promotion-existing",
                    tool_name=FIND_TOOL,
                    arguments={"promotion_type": self.lever},
                )
            )
        if self.verify_round <= 0:
            return self._before_seller(messages)
        if len(finds) < 1 + self.verify_round:
            return _turn(
                ToolCallBlock(
                    call_id=f"promotion-verify-{self.verify_round}",
                    tool_name=FIND_TOOL,
                    arguments={"promotion_type": self.lever},
                )
            )
        latest = finds[-1]
        new = promotion_module.new_promotions(finds[0], latest)
        if not isinstance(latest, Mapping) or latest.get("unavailable") or not new:
            raise AwaitSeller(
                awaiting=AWAITING_SELLER_ACTION, narration=NARRATION_NOT_FOUND, not_found=True
            )
        self.found = dict(new[0])
        return _turn(
            FinalResponse(
                content=(
                    f"Đã xác nhận trên TikTok. {promotion_module.found_sentence(new[0])}. "
                    "Juli bắt đầu đo từ ngày khuyến mãi bắt đầu: đo sơ bộ ngày 7, chốt ngày 14."
                )
            )
        )

    def _before_seller(self, messages: Sequence[Message]) -> AssistantTurn:
        """Check the rules (narrated once), then wait for the seller."""
        proposal = promotion_module.propose(
            self.lever, self.rules, self.product_detail(), today=self.today()
        )
        self.proposal = proposal
        sentence = promotion_module.rules_sentence(proposal)
        if not proposal.ok:
            return _turn(
                TextBlock(text=sentence),
                FinalResponse(
                    content=f"{proposal.refusal_vi} Juli không đề xuất áp dụng khuyến mãi này."
                ),
            )
        if sentence not in _assistant_texts(messages):
            return _turn(TextBlock(text=sentence))
        raise AwaitSeller(
            awaiting=AWAITING_SELLER_ACTION,
            narration=NARRATION_AWAITING_SELLER,
            proposal=proposal.to_json(),
        )


__all__ = [
    "PHOTO_PLAYBOOK",
    "PROMOTION_PLAYBOOK",
    "PhotoPlanner",
    "PromotionPlanner",
]
