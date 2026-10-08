"""The "Hoàn tác" run: a mode of the existing executor (fast track P8-C, ADR-109 d.9).

A revert run is an ordinary ``workflow_runs`` row (``reverts_run_id`` set)
executed by the ordinary ``WorkflowRunner``: same tools, same CONFIRM pause and
confirmation endpoint, same ledger, same SSE events (``tool.started`` /
``tool.completed`` with the runner's Vietnamese summaries,
``workflow.approval_required``, ``workflow.completed``/``failed``). Two things
differ, both chosen in the worker's ``_construct_runner``:

- **The playbook** (``REVERT_LISTING_PLAYBOOK``) allows only the three steps a
  revert needs: read the product, restore the listing (CONFIRM), check its
  status. It shares Optimize Product's ``workflow_key``, prompt pin and
  termination limits, so the reaper, the prompt composer and the outcome
  recorder treat it exactly like the run it undoes.
- **The planner** (``RevertPlanner``) replaces the LLM. Undoing is not a
  judgement call: the values to restore are the recorded before-values, so a
  deterministic planner proposes them. It is stateless -- each turn is decided
  from the conversation the runner hands it -- so it works across the CONFIRM
  pause, where the resume leg runs in a fresh worker process.

The plan travels in the run's state blob under ``revert_plan``
(``RunState`` keeps unknown keys), written once when the revert is started.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    FinalResponse,
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

STATE_KEY = "revert_plan"

READ_TOOL = "get_product_information"
WRITE_TOOL = "update_product_listing"
STATUS_TOOL = "check_product_status"

READ_CALL_ID = "revert-read"
WRITE_CALL_ID = "revert-write"
STATUS_CALL_ID = "revert-status"

#: Vietnamese field labels for seller-facing copy.
FIELD_LABELS_VI: Mapping[str, str] = {
    "title": "tiêu đề",
    "description": "mô tả",
    "main_images": "ảnh sản phẩm",
    "price": "giá",
}

#: The listing fields a revert can restore through `update_product_listing`.
RESTORABLE_FIELDS: tuple[str, ...] = ("title", "description", "main_images")

REVERT_LISTING_PLAYBOOK = Playbook(
    workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
    version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
    steps=(
        PlaybookStep(
            step_id="revert-1",
            intent="Read the product's current listing before restoring it.",
            tools=(READ_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
        PlaybookStep(
            step_id="revert-2",
            intent=(
                "Restore the listing fields Juli changed to their values from before "
                "that change, once the seller approves."
            ),
            tools=(WRITE_TOOL,),
            policy=ToolPolicy.CONFIRM,
        ),
        PlaybookStep(
            step_id="revert-3",
            intent="Check the listing's status after the restore.",
            tools=(STATUS_TOOL,),
            policy=ToolPolicy.AUTO,
        ),
    ),
    termination_policy=replace(
        OPTIMIZE_PRODUCT_TERMINATION_POLICY, required_steps=(WRITE_TOOL,), terminal_tools=()
    ),
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


validate_playbook_tools(REVERT_LISTING_PLAYBOOK, _registry())


@dataclass(frozen=True)
class RevertPlan:
    """What a revert run restores, and what the live listing must still hold.

    ``restore``: field -> the value before Juli's write. ``expected``: field ->
    Juli's after-value; the executor refuses the write when the live listing no
    longer holds it (S-FR-8).
    """

    reverts_run_id: str
    restore: dict[str, Any]
    expected: dict[str, Any]
    started_by_user_id: str | None = None
    fields: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.fields:
            object.__setattr__(
                self, "fields", tuple(f for f in RESTORABLE_FIELDS if f in self.restore)
            )

    @property
    def restore_main_image_uris(self) -> tuple[str, ...] | None:
        images = self.restore.get("main_images")
        if not images:
            return None
        return tuple(str(uri) for uri in images)

    def write_arguments(self) -> dict[str, Any]:
        """The `update_product_listing` arguments: the before-values, nothing else.

        Photos are restored from server-held URIs (``restore_main_image_uris``),
        never from model-visible arguments; ``restore_previous_images`` only
        tells the seller's confirmation that the photos come back too.
        """
        arguments: dict[str, Any] = {}
        if "title" in self.restore:
            arguments["title"] = self.restore["title"]
        if "description" in self.restore:
            arguments["description"] = self.restore["description"]
        if "main_images" in self.restore:
            arguments["restore_previous_images"] = True
        return arguments

    def to_state(self) -> dict[str, Any]:
        return {
            "reverts_run_id": self.reverts_run_id,
            "restore": dict(self.restore),
            "expected": dict(self.expected),
            "started_by_user_id": self.started_by_user_id,
        }

    @classmethod
    def from_state(cls, blob: Mapping[str, Any] | None) -> RevertPlan | None:
        """The plan stored on a run's state, or ``None`` for an ordinary run."""
        raw = (blob or {}).get(STATE_KEY)
        if not isinstance(raw, Mapping) or not raw.get("reverts_run_id"):
            return None
        return cls(
            reverts_run_id=str(raw["reverts_run_id"]),
            restore=dict(raw.get("restore") or {}),
            expected=dict(raw.get("expected") or {}),
            started_by_user_id=raw.get("started_by_user_id"),
        )


def revert_plan_from_state(blob: Mapping[str, Any] | None) -> RevertPlan | None:
    return RevertPlan.from_state(blob)


def _labels(fields: Sequence[str]) -> str:
    return ", ".join(FIELD_LABELS_VI.get(name, name) for name in fields)


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=0, output_tokens=0))


def _tool_results(messages: Sequence[Message]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for message in messages:
        if isinstance(message, Mapping) and message.get("role") == "tool":
            results[str(message.get("tool_name"))] = message.get("content")
    return results


def _declined(content: Any) -> bool:
    return (
        isinstance(content, Mapping)
        and isinstance(content.get("confirmation"), Mapping)
        and content["confirmation"].get("decision") == "declined"
    )


def _conflict(content: Any) -> bool:
    return isinstance(content, Mapping) and bool(content.get("conflict"))


def _errored(content: Any) -> bool:
    return isinstance(content, Mapping) and "error" in content


@dataclass
class RevertPlanner:
    """A deterministic ``LLMService`` that drives a revert run (see module docstring).

    Turn by turn: read the product; propose the restore (the runner pauses for
    the seller's consent); check the listing status; say what was restored. A
    declined consent or a listing that changed while waiting ends with an
    honest sentence and nothing written.
    """

    plan: RevertPlan

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        system: str,
        tools: Sequence[ToolDefinition],
        config: LLMConfig,
        tool_choice: str | None = None,
    ) -> AssistantTurn:
        del system, tools, config, tool_choice  # deterministic: the plan decides
        results = _tool_results(messages)
        labels = _labels(self.plan.fields)
        if WRITE_TOOL in results:
            content = results[WRITE_TOOL]
            if _declined(content):
                return _turn(
                    FinalResponse(
                        content=(
                            "Bạn đã từ chối hoàn tác. Sản phẩm giữ nguyên như hiện tại, "
                            "Juli không thay đổi gì."
                        )
                    )
                )
            if _conflict(content):
                return _turn(
                    FinalResponse(
                        content=(
                            "Sản phẩm đã được thay đổi trong lúc chờ xác nhận, nên Juli "
                            "không ghi đè. Chưa có gì được hoàn tác."
                        )
                    )
                )
            if _errored(content):
                return _turn(
                    FinalResponse(
                        content="Juli chưa hoàn tác được thay đổi này. Sản phẩm giữ nguyên."
                    )
                )
            if STATUS_TOOL not in results:
                return _turn(ToolCallBlock(call_id=STATUS_CALL_ID, tool_name=STATUS_TOOL))
            return _turn(
                FinalResponse(content=f"Juli đã khôi phục {labels} về nội dung trước lần thay đổi.")
            )
        if READ_TOOL in results:
            if _errored(results[READ_TOOL]):
                return _turn(
                    FinalResponse(
                        content=(
                            "Juli không đọc được sản phẩm từ TikTok Shop nên chưa hoàn tác. "
                            "Sản phẩm giữ nguyên."
                        )
                    )
                )
            return _turn(
                ToolCallBlock(
                    call_id=WRITE_CALL_ID,
                    tool_name=WRITE_TOOL,
                    arguments=self.plan.write_arguments(),
                )
            )
        return _turn(ToolCallBlock(call_id=READ_CALL_ID, tool_name=READ_TOOL))
