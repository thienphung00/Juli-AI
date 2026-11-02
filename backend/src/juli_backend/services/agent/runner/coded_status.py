"""The run panel's coded status line (fast track P85, D78 step 2, D78.2).

Live sandbox runs d7b5d16c and 6a3dd6fd (01-02/11, prompt v4) streamed the model's own
narration to the seller: long Vietnamese with Markdown headings and bold, English words
("Next-steps", "CONFIRM", "playbook") and talk of "tool của mình". D78.2: the run panel
shows a coded Juli status line only, never free model text.

So the model no longer narrates to the seller. It reports codes through one strict tool,
``report_status``, offered by the runner itself (not a playbook step: the playbook table
every released prompt version renders stays byte-identical). Juli turns the codes into
one Vietnamese line from its own templates (``coded_status_copy.py``) and emits it as a
``workflow.status`` whose ``status_code`` carries the codes.

Why a tool and not a strict ``text.format`` final answer: the runner is a tool loop on
gpt-5.4-nano. A ``text.format`` schema constrains every output text of every turn (the
text beside a tool call too), arrives only when the model stops calling tools (after the
seller's decision, so too late for the panel), and is not part of the ``LLMService``
protocol. A strict function call rides the turn that proposes the change (parallel tool
calls), is answered like any tool call, and is checked by the same strict-schema gate as
every other tool (D78.5).

**Faithful by construction.** Juli never shows a code it cannot back:

* a reason code is shown only when this run's own reads flagged it (TikTok's
  ``get_product_diagnoses`` codes, or the ``edit_codes`` of ``get_product_information``);
* the plan is read from the listing proposal in the same turn when there is one (which
  fields its edits touch), and is ``nothing_to_change`` when the turn concludes without
  changes -- the model's ``plan_code`` is used only when the turn carries neither.

Pure: no I/O, no event emission (the runner emits).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from juli_backend.services.agent.events import CodedStatusPayload
from juli_backend.services.agent.llm import ToolCallBlock, ToolDefinition
from juli_backend.services.agent.runner.coded_status_copy import coded_status_line_vi
from juli_backend.services.agent.tools.diagnosis_labels import diagnosis_label_vi

REPORT_STATUS_TOOL_NAME = "report_status"

#: The workflows whose prompt teaches ``report_status`` (Optimize Product, prompt v5+).
#: Every other model-driven run still has no free narration (``coded_narration``); it
#: simply has no coded line beyond Juli's step labels.
CODED_STATUS_WORKFLOWS = frozenset({"optimize_product_2"})

#: How many reason labels one line names; the rest are counted, not listed.
MAX_REASON_LABELS = 3

_LISTING_TOOL = "update_product_listing"
_CONCLUDE_TOOL = "conclude_without_changes"
_DIAGNOSES_TOOL = "get_product_diagnoses"
_PRODUCT_TOOL = "get_product_information"


class ReasonCode(StrEnum):
    """A diagnosis code Juli has a Vietnamese label for (``DIAGNOSIS_CODE_LABELS_VI``;
    ``test_p85_coded_narration`` pins the two sets equal)."""

    TITLE_LESS_THAN_40_CHARACTERS = "TITLE_LESS_THAN_40_CHARACTERS"
    SEO_DIAGNOSTIC_ITEM = "SEO_DIAGNOSTIC_ITEM"
    DESC_LESS_THAN_FIVE_HUNDRED_CHARS = "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"
    DESC_NO_NEW_LINE = "DESC_NO_NEW_LINE"
    DESCRIPTION_INCLUDE_INVALID_IMAGE = "DESCRIPTION_INCLUDE_INVALID_IMAGE"
    MAIN_IMG_DUPLICATE = "MAIN_IMG_DUPLICATE"
    MAIN_IMG_NUMBER_LESS_THAN_FIVE = "MAIN_IMG_NUMBER_LESS_THAN_FIVE"
    MAIN_IMG_FIRST_IMG_BACKGROUND_UNTIDY = "MAIN_IMG_FIRST_IMG_BACKGROUND_UNTIDY"
    MAIN_IMG_FIRST_IMG_BLACK_BORDER = "MAIN_IMG_FIRST_IMG_BLACK_BORDER"
    MAIN_IMG_FIRST_IMG_WHITE_BORDER = "MAIN_IMG_FIRST_IMG_WHITE_BORDER"
    MAIN_IMG_FIRST_IMG_FAKE_MODEL = "MAIN_IMG_FIRST_IMG_FAKE_MODEL"
    MAIN_IMG_FIRST_IMG_INCLUDE_NON_LOCAL_LANGUAGE = "MAIN_IMG_FIRST_IMG_INCLUDE_NON_LOCAL_LANGUAGE"
    MAIN_IMG_FIRST_IMG_LOW_QUALITY = "MAIN_IMG_FIRST_IMG_LOW_QUALITY"
    MAIN_IMG_FIRST_IMG_MISSING_PRODUCT_SUBSTANCE = "MAIN_IMG_FIRST_IMG_MISSING_PRODUCT_SUBSTANCE"
    MAIN_IMG_FIRST_IMG_NOT_CLEAR = "MAIN_IMG_FIRST_IMG_NOT_CLEAR"
    MAIN_IMG_FIRST_IMG_PRODUCT_SUBJECT_NOT_COMPLETE = (
        "MAIN_IMG_FIRST_IMG_PRODUCT_SUBJECT_NOT_COMPLETE"
    )
    MAIN_IMG_FIRST_IMG_SPLICED_PICTURE = "MAIN_IMG_FIRST_IMG_SPLICED_PICTURE"
    MAIN_IMG_FIRST_IMG_TEXT_OVERLOAD = "MAIN_IMG_FIRST_IMG_TEXT_OVERLOAD"


class PlanCode(StrEnum):
    """What Juli will change on the listing."""

    TITLE = "title"
    DESCRIPTION = "description"
    TITLE_AND_DESCRIPTION = "title_and_description"
    PHOTOS_NEEDED = "photos_needed"
    NOTHING_TO_CHANGE = "nothing_to_change"


class ImpactCode(StrEnum):
    """What the change is expected to do."""

    FIXES_FLAGGED_ISSUES = "fixes_flagged_issues"
    EASIER_TO_FIND = "easier_to_find"
    EASIER_TO_READ = "easier_to_read"
    NONE = "none"


class ReportStatusInput(BaseModel):
    """Codes only: the seller-facing words are Juli's own templates."""

    model_config = ConfigDict(extra="forbid")

    reason_codes: list[ReasonCode] = Field(
        description=(
            "The diagnosis codes this change fixes, copied from edit_codes or the "
            "diagnoses read. Empty when nothing is flagged."
        ),
        max_length=8,
    )
    plan_code: PlanCode = Field(description="What you change on the listing.")
    impact_code: ImpactCode = Field(description="The expected effect of the change.")


REPORT_STATUS_DESCRIPTION = (
    "Report this run's status to the seller as codes; Juli writes the words. Call it "
    "once, in the same turn as update_product_listing or conclude_without_changes. "
    "It changes nothing on the listing."
)


def report_status_tool_definition() -> ToolDefinition:
    """The model-facing definition (sent strict by the adapter, like every tool)."""
    return {
        "name": REPORT_STATUS_TOOL_NAME,
        "description": REPORT_STATUS_DESCRIPTION,
        "input_schema": ReportStatusInput.model_json_schema(),
    }


def flagged_codes(window: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """The diagnosis codes this run's own reads flagged (TikTok's and Juli's check)."""
    found: set[str] = set()
    for message in window:
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(content, Mapping):
            continue
        name = message.get("tool_name")
        if name == _DIAGNOSES_TOOL:
            found.update(_codes_of(content.get("codes")))
        elif name == _PRODUCT_TOOL:
            block = content.get("edit_codes")
            if isinstance(block, Mapping):
                found.update(_codes_of(block.get("title_codes")))
                found.update(_codes_of(block.get("description_codes")))
                found.update(c for c in block.get("not_for_text") or () if isinstance(c, str))
    return frozenset(found)


def _codes_of(entries: Any) -> Iterable[str]:
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, Mapping) and isinstance(entry.get("code"), str):
            yield entry["code"]


def plan_from_turn(blocks: Iterable[object]) -> PlanCode | None:
    """The plan the same turn's proposal shows, or None when the turn has none."""
    for block in blocks:
        if not isinstance(block, ToolCallBlock):
            continue
        if block.tool_name == _CONCLUDE_TOOL:
            return PlanCode.NOTHING_TO_CHANGE
        if block.tool_name == _LISTING_TOOL:
            return _listing_plan(block.arguments)
    return None


def _listing_plan(arguments: Mapping[str, Any]) -> PlanCode | None:
    edits = arguments.get("edits")
    if isinstance(edits, Mapping):
        title = bool(edits.get("title_ops"))
        description = bool(edits.get("description_ops"))
    else:
        title = bool(arguments.get("title"))
        description = bool(arguments.get("description"))
    if title and description:
        return PlanCode.TITLE_AND_DESCRIPTION
    if title:
        return PlanCode.TITLE
    if description:
        return PlanCode.DESCRIPTION
    return None


def coded_status(
    report: ReportStatusInput,
    *,
    window: Sequence[Mapping[str, Any]],
    turn_blocks: Iterable[object] = (),
) -> tuple[str, CodedStatusPayload]:
    """The seller-facing line and the codes behind it, both from facts Juli holds."""
    flagged = flagged_codes(window)
    reasons = list(dict.fromkeys(code.value for code in report.reason_codes if code in flagged))
    plan = plan_from_turn(turn_blocks) or report.plan_code
    impact = report.impact_code
    if plan is PlanCode.NOTHING_TO_CHANGE:
        impact = ImpactCode.NONE
    line = coded_status_line_vi(
        reason_labels=[diagnosis_label_vi(code) for code in reasons],
        plan_code=plan.value,
        impact_code=impact.value,
        max_labels=MAX_REASON_LABELS,
    )
    payload = CodedStatusPayload(
        reason_codes=reasons, plan_code=plan.value, impact_code=impact.value
    )
    return line, payload


__all__ = [
    "CODED_STATUS_WORKFLOWS",
    "MAX_REASON_LABELS",
    "REPORT_STATUS_DESCRIPTION",
    "REPORT_STATUS_TOOL_NAME",
    "ImpactCode",
    "PlanCode",
    "ReasonCode",
    "ReportStatusInput",
    "coded_status",
    "flagged_codes",
    "plan_from_turn",
    "report_status_tool_definition",
]
