"""Resolving a seller's decision on a CONFIRM-policy pause (ADR-075 decision 2).

The decision is authorised by a ladder, each rung a distinct failure the
caller can name (``ConfirmationRejected.error_code``):

1. tenant scoping -- done by the caller, since it owns the HTTP 404 shape;
2. the run is ``waiting_approval``;
3. a confirmation row exists for this ``tool_call_id`` and is still pending
   (already-decided is single-use, expired is gone);
4. the wall-clock deadline has not passed -- checked directly, not via the
   reaper, so a decision arriving after expiry is refused even before the
   reaper's sweep has flipped the row;
5. for ``approve``: the option exists, and its ``params_sha`` equals the sha
   re-derived from the run's own reconstructable ``pending_confirmation``
   state -- the exact blob ``WorkflowRunner.resume`` will execute. A mismatch
   is a hard refusal (the change the seller saw is not the change that would
   run), and the row is left pending so nothing downstream can fire.

Winning the transition is a single conditional ``UPDATE ... WHERE status =
'pending'``. Two concurrent decisions both reach it; the database serialises
them and exactly one matches. The loser sees the same fact a sequential
double-submit sees -- "someone already decided this" -- and gets the same
error code.

This module never commits and never enqueues. The caller commits *before*
enqueueing the resume task, so a worker can never observe the row still
pending mid-flight (#1221).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import RunConfirmation
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services import shop_rules
from juli_backend.services.agent import write_approval
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools.listing_rules import (
    ERROR_SOURCE_NAME_NOT_IN_TITLE,
    source_terms_not_in,
)

logger = logging.getLogger(__name__)

WAITING_APPROVAL_RUN_STATUS = WorkflowRunStatus.WAITING_APPROVAL.value
PENDING_CONFIRMATION_STATUS = "pending"
#: The CONFIRM tools whose proposal the seller may edit (title / description): the
#: listing edit, and the sandbox "Tạo sản phẩm" create (P64, D73.3) -> the description
#: limit each tool's own input model accepts.
EDITABLE_TOOL_DESCRIPTION_MAX: dict[str, int] = {
    "update_product_listing": shop_rules.DESCRIPTION_MAX_CHARS,
    "create_product": 5_000,
}
#: P65 (D74): the sandbox "Tạo khuyến mãi" create -- the reviewer may edit the discount
#: % and the end date (validated against the run's own discount range and dates).
PROMOTION_TOOL = "create_product_discount"
PROMOTION_EDITABLE_FIELDS: frozenset[str] = frozenset({"discount_pct", "end_date"})
EXPIRED_CONFIRMATION_STATUS = "expired"

# Machine-readable discriminators. Stable: clients branch on them.
ERROR_RUN_NOT_AWAITING_CONFIRMATION = "run_not_awaiting_confirmation"
ERROR_CONFIRMATION_NOT_FOUND = "confirmation_not_found"
ERROR_CONFIRMATION_ALREADY_DECIDED = "confirmation_already_decided"
ERROR_CONFIRMATION_EXPIRED = "confirmation_expired"
ERROR_INVALID_DECISION = "invalid_decision"
ERROR_OPTION_ID_REQUIRED = "option_id_required"
ERROR_UNKNOWN_OPTION_ID = "unknown_option_id"
ERROR_PARAMS_SHA_MISMATCH = "params_sha_mismatch"
ERROR_RUN_STATE_NOT_RECONSTRUCTABLE = "run_state_not_reconstructable"
#: ADR-116 §6 (D76): an approve by a user who does not belong to the run's shop.
ERROR_APPROVER_NOT_SHOP_MEMBER = "approver_not_shop_member"

# HTTP status each rung maps to. Kept here, beside the codes, so the route
# does not have to know which rung produced which code.
_HTTP_STATUS_FOR_CODE: dict[str, int] = {
    ERROR_RUN_NOT_AWAITING_CONFIRMATION: 409,
    ERROR_CONFIRMATION_NOT_FOUND: 404,
    ERROR_CONFIRMATION_ALREADY_DECIDED: 409,
    ERROR_CONFIRMATION_EXPIRED: 410,
    ERROR_INVALID_DECISION: 422,
    ERROR_OPTION_ID_REQUIRED: 422,
    ERROR_UNKNOWN_OPTION_ID: 422,
    ERROR_PARAMS_SHA_MISMATCH: 409,
    ERROR_RUN_STATE_NOT_RECONSTRUCTABLE: 409,
    ERROR_APPROVER_NOT_SHOP_MEMBER: 403,
}


class ConfirmationRejected(Exception):
    """A rung of the ladder refused the decision. Nothing was written."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = _HTTP_STATUS_FOR_CODE[error_code]


@dataclass(frozen=True)
class ConfirmationDecision:
    """The outcome of a won transition."""

    decision: str  # "approve" | "decline", echoing the request
    approved: bool
    new_status: str  # "approved" | "declined", the row's status now


def as_aware_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime read back from SQLite; pass aware values through.

    ``run_confirmations.expires_at`` is ``timezone=True`` but SQLite returns
    naive values. Every writer seeds UTC, so this restores information rather
    than guessing.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def transition_confirmation_or_none(
    session: AsyncSession,
    confirmation_id: uuid.UUID,
    *,
    new_status: str,
    selected_option_id: str | None,
) -> bool:
    """Flip the row out of ``pending`` atomically; ``True`` iff this call won."""
    stmt = (
        update(RunConfirmation)
        .where(
            RunConfirmation.id == confirmation_id,
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
        .values(
            status=new_status,
            selected_option_id=selected_option_id,
            decided_at=datetime.now(UTC),
        )
    )
    # An UPDATE's runtime result is a CursorResult, where rowcount lives.
    result = cast(CursorResult, await session.execute(stmt))
    return result.rowcount == 1


class EditRejected(Exception):
    """The seller's edited values break a shop rule (fast track P10-A). Nothing was written."""

    def __init__(self, field: str, message_vi: str, code: str = "rule_violation") -> None:
        super().__init__(f"{field}: {message_vi}")
        self.field = field
        self.message_vi = message_vi
        #: The 422's machine-readable ``code`` (``rule_violation`` | ``brand_not_in_source``).
        self.code = code


async def decide_confirmation(
    session: AsyncSession,
    run: WorkflowRunRow,
    *,
    tool_call_id: str,
    decision: str,
    option_id: str | None,
    decided_by_user_id: uuid.UUID | None,
    edited_values: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> ConfirmationDecision:
    """Walk the ladder for ``run`` and win the transition, or raise :class:`ConfirmationRejected`.

    On approve, the confirmed ``params_sha`` is frozen onto ``run.state`` so
    ``WorkflowRunner.resume`` can re-derive and compare independently before
    executing. The caller must commit.

    ``edited_values`` (fast track P10-A, contract p10-quyet-dinh.md §3): the
    seller's own version of the proposed ``title`` / ``description``. After the
    consent binding (the option still matches what Juli proposed), the edit is
    validated against the shop's rules (:class:`EditRejected` -- the row stays
    pending), then replaces those arguments in ``pending_confirmation`` with a
    params sha re-derived over the edited arguments, so the resume executes --
    and its before/after record stores -- exactly the seller's version.
    ``edited_fields`` on the same dict tells the resume to say so.

    ADR-116 §6 (D76, grill D7): an approve is refused (``approver_not_shop_member``,
    403) unless ``decided_by_user_id`` belongs to the run's shop (D73: or is the
    reviewer on its writable sandbox pin). The approved change -- who, when, the
    card approval it rests on, the "before" the seller saw and the exact arguments --
    is frozen onto ``pending_confirmation["approved_change"]``; the live write leg
    checks it (``services/agent/write_approval``).
    """
    if run.status != WAITING_APPROVAL_RUN_STATUS:
        raise ConfirmationRejected(
            ERROR_RUN_NOT_AWAITING_CONFIRMATION,
            f"Run {run.id} is not awaiting a confirmation decision (status={run.status!r}).",
        )

    confirmation = await _pending_confirmation(session, run.id, tool_call_id, now=now)

    if decision == "decline":
        approved, selected_option_id = False, None
    elif decision == "approve":
        try:
            if decided_by_user_id is None:  # no clicking user: never an approval
                raise write_approval.ApproverNotShopMember("no user")
            await write_approval.approver_kind(
                session, shop_id=run.shop_id, user_id=decided_by_user_id
            )
        except write_approval.ApproverNotShopMember:
            raise ConfirmationRejected(
                ERROR_APPROVER_NOT_SHOP_MEMBER,
                "Only a user who belongs to this shop may approve a change to it.",
            ) from None
        selected_option_id = _bind_consent(run, confirmation, option_id)
        if edited_values:
            await _apply_seller_edits(session, run, edited_values)
        await _check_listing_banned_terms(session, run)
        await write_approval.freeze_approved_change(
            session, run, decided_by_user_id=decided_by_user_id
        )
        approved = True
    else:
        raise ConfirmationRejected(
            ERROR_INVALID_DECISION,
            f"decision must be 'approve' or 'decline', got {decision!r}.",
        )

    new_status = "approved" if approved else "declined"
    won = await transition_confirmation_or_none(
        session, confirmation.id, new_status=new_status, selected_option_id=selected_option_id
    )
    if not won:
        raise ConfirmationRejected(
            ERROR_CONFIRMATION_ALREADY_DECIDED,
            f"Confirmation {tool_call_id!r} was already decided.",
        )
    return ConfirmationDecision(decision=decision, approved=approved, new_status=new_status)


async def decline_pending_confirmation(
    session: AsyncSession, run: WorkflowRunRow, *, now: datetime | None = None
) -> ConfirmationDecision:
    """Decline the run's one pending confirmation ("Không thực hiện", fast track P10-A).

    The same ladder as ``decide_confirmation(decision="decline")``, for a caller
    that names the run rather than the tool call.
    """
    if run.status != WAITING_APPROVAL_RUN_STATUS:
        raise ConfirmationRejected(
            ERROR_RUN_NOT_AWAITING_CONFIRMATION,
            f"Run {run.id} is not awaiting a confirmation decision (status={run.status!r}).",
        )
    result = await session.execute(
        select(RunConfirmation.tool_call_id)
        .where(
            RunConfirmation.workflow_run_id == run.id,
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
        .order_by(RunConfirmation.expires_at.desc())
    )
    tool_call_id = result.scalars().first()
    if tool_call_id is None:
        raise ConfirmationRejected(
            ERROR_CONFIRMATION_NOT_FOUND, f"Run {run.id} has no pending confirmation."
        )
    return await decide_confirmation(
        session,
        run,
        tool_call_id=tool_call_id,
        decision="decline",
        option_id=None,
        decided_by_user_id=None,  # a decline writes nothing
        now=now,
    )


def _promotion_edits(
    run_state: Mapping[str, Any], edited_values: Mapping[str, Any]
) -> dict[str, Any]:
    """P65 (D74): the reviewer's discount % / end date for the promotion create, validated
    against the run's own discount range (its opening ``shop_rules.discount``) and the
    allowed dates. :class:`EditRejected` (a 422) otherwise."""
    from juli_backend.services.agent import run_context
    from juli_backend.services.agent.tools import promotion_create

    unknown = sorted(set(edited_values) - PROMOTION_EDITABLE_FIELDS)
    if unknown:
        raise EditRejected(unknown[0], "Bước này chỉ sửa được mức giảm và ngày kết thúc.")
    changed: dict[str, Any] = {}
    if "discount_pct" in edited_values:
        raw = edited_values["discount_pct"]
        if isinstance(raw, bool) or not isinstance(raw, int | float) or int(raw) != raw:
            raise EditRejected("discount_pct", "Mức giảm cần là số nguyên phần trăm.")
        bounds = promotion_create.discount_bounds(
            run_context.opening_shop_rules(run_state).get("discount")
        )
        refusal = promotion_create.check_discount(int(raw), bounds.min_pct, bounds.max_pct)
        if refusal is not None:
            raise EditRejected("discount_pct", refusal + ".")
        changed["discount_pct"] = int(raw)
    if "end_date" in edited_values:
        end = promotion_create.parse_end_date(
            str(edited_values["end_date"]), promotion_create.shop_today()
        )
        if isinstance(end, str):
            raise EditRejected("end_date", end + ".")
        changed["end_date"] = end.isoformat()
    return changed


async def _apply_seller_edits(
    session: AsyncSession, run: WorkflowRunRow, edited_values: Mapping[str, Any]
) -> None:
    """Validate the seller's edit and bind the run's pending call to it (see above)."""
    run_state: dict[str, Any] = run.state if isinstance(run.state, dict) else {}
    pending_state = run_state.get("pending_confirmation")
    if not isinstance(pending_state, dict):
        raise ConfirmationRejected(
            ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
            "Run has no reconstructable pending confirmation state.",
        )
    arguments = pending_state.get("arguments")
    arguments = dict(arguments) if isinstance(arguments, Mapping) else {}
    first_field = next(iter(edited_values))
    tool_name = pending_state.get("tool_name")
    if tool_name == PROMOTION_TOOL:
        promotion_changed = {
            key: value
            for key, value in _promotion_edits(run_state, edited_values).items()
            if arguments.get(key) != value
        }
        _bind_edit(run, run_state, pending_state, arguments, promotion_changed)
        return
    description_max = EDITABLE_TOOL_DESCRIPTION_MAX.get(str(tool_name))
    if description_max is None:
        raise EditRejected(first_field, "Bước này không có nội dung sửa được.")
    # A new listing has no "current" title / description: the protected-terms
    # reference is Juli's proposal (validate_listing_edits' fallback).
    detail = run_state.get("product_detail") if tool_name == "update_product_listing" else None
    try:
        changed = shop_rules.validate_listing_edits(
            edited_values,
            proposed=arguments,
            current=detail if isinstance(detail, Mapping) else None,
            protected_terms=await shop_rules.protected_terms(session, run.shop_id),
            banned_terms=await shop_rules.banned_terms(session, run.shop_id),
            description_max_chars=description_max,
        )
    except shop_rules.ListingEditViolation as violation:
        raise EditRejected(violation.field, violation.message_vi) from None
    _bind_edit(run, run_state, pending_state, arguments, changed)


def _bind_edit(
    run: WorkflowRunRow,
    run_state: dict[str, Any],
    pending_state: dict[str, Any],
    arguments: dict[str, Any],
    changed: Mapping[str, Any],
) -> None:
    """Bind the run's pending call to the edited arguments (a fresh params sha)."""
    if not changed:
        return
    edited_arguments = {**arguments, **changed}
    run.state = {
        **run_state,
        "pending_confirmation": {
            **pending_state,
            "arguments": edited_arguments,
            "params_sha": compute_params_sha(edited_arguments),
            "edited_fields": sorted(changed),
        },
    }


async def _check_listing_banned_terms(session: AsyncSession, run: WorkflowRunRow) -> None:
    """D24.21 (5): no listing write may carry the seller's "Từ không được dùng" --
    nor (P64, D73.5) a name the source title does not carry.

    Applies to the title / description about to be written -- Juli's proposal
    or the seller's edit of it. :class:`EditRejected`; the row stays pending.
    """
    run_state: dict[str, Any] = run.state if isinstance(run.state, dict) else {}
    pending_state = run_state.get("pending_confirmation")
    if (
        not isinstance(pending_state, dict)
        or pending_state.get("tool_name") not in EDITABLE_TOOL_DESCRIPTION_MAX
    ):
        return
    arguments = pending_state.get("arguments")
    if not isinstance(arguments, Mapping):
        return
    banned = await shop_rules.banned_terms(session, run.shop_id)
    try:
        shop_rules.check_banned_terms(arguments, banned)
    except shop_rules.ListingEditViolation as violation:
        raise EditRejected(violation.field, violation.message_vi) from None
    # P64 (D73.5): the built-in rule -- no free-text value or brand name of the source
    # listing that its title (a new listing) or its title and description (an edit)
    # does not already carry. Needs the source as the run read it.
    detail = run_state.get("product_detail")
    if not isinstance(detail, Mapping):
        return
    keys = (
        ("title",)
        if pending_state.get("tool_name") == "create_product"
        else (
            "title",
            "description",
        )
    )
    reference = " ".join(str(detail.get(key) or "") for key in keys)
    hit = shop_rules.find_term(arguments, source_terms_not_in(detail, reference))
    if hit is not None:
        field, term = hit
        label = shop_rules.FIELD_LABELS_VI[field]
        raise EditRejected(
            field,
            f'{label} có "{term}" — không có trong tiêu đề sản phẩm gốc. '
            f"{shop_rules.SOURCE_NAMES_RULE_VI} Hãy bỏ từ này.",
            code=ERROR_SOURCE_NAME_NOT_IN_TITLE,
        )


async def _pending_confirmation(
    session: AsyncSession, run_id: uuid.UUID, tool_call_id: str, *, now: datetime | None
) -> RunConfirmation:
    """Rungs 3 and 4: the row for this tool call, pending and not past its deadline."""
    result = await session.execute(
        select(RunConfirmation).where(
            RunConfirmation.workflow_run_id == run_id,
            RunConfirmation.tool_call_id == tool_call_id,
        )
    )
    confirmation = result.scalars().first()
    if confirmation is None:
        raise ConfirmationRejected(
            ERROR_CONFIRMATION_NOT_FOUND,
            f"No confirmation for tool_call_id={tool_call_id!r} on run {run_id}.",
        )
    expired_message = "This confirmation has expired; the run is left for the reaper."
    if confirmation.status == EXPIRED_CONFIRMATION_STATUS:
        raise ConfirmationRejected(ERROR_CONFIRMATION_EXPIRED, expired_message)
    if confirmation.status != PENDING_CONFIRMATION_STATUS:
        raise ConfirmationRejected(
            ERROR_CONFIRMATION_ALREADY_DECIDED,
            f"Confirmation {tool_call_id!r} was already decided ({confirmation.status}).",
        )
    if as_aware_utc(confirmation.expires_at) <= (now or datetime.now(UTC)):
        raise ConfirmationRejected(ERROR_CONFIRMATION_EXPIRED, expired_message)
    return confirmation


def _bind_consent(run: WorkflowRunRow, confirmation: RunConfirmation, option_id: str | None) -> str:
    """Rung 5: the chosen option must match what the run would actually execute."""
    if option_id is None:
        raise ConfirmationRejected(
            ERROR_OPTION_ID_REQUIRED, "An approve decision requires option_id."
        )

    options = confirmation.options if isinstance(confirmation.options, list) else []
    selected = next((option for option in options if option.get("option_id") == option_id), None)
    if selected is None:
        raise ConfirmationRejected(
            ERROR_UNKNOWN_OPTION_ID,
            f"option_id={option_id!r} is not one of this confirmation's options.",
        )

    run_state: dict[str, Any] = run.state if isinstance(run.state, dict) else {}
    pending_state = run_state.get("pending_confirmation")
    if not isinstance(pending_state, dict) or "arguments" not in pending_state:
        raise ConfirmationRejected(
            ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
            "Run has no reconstructable pending confirmation state.",
        )

    expected_params_sha = compute_params_sha(pending_state["arguments"])
    if selected.get("params_sha") != expected_params_sha:
        logger.warning(
            "agent_confirmation_params_sha_mismatch",
            extra={
                "shop_id": str(run.shop_id),
                "run_id": str(run.id),
                "tool_call_id": confirmation.tool_call_id,
                "option_id": option_id,
            },
        )
        raise ConfirmationRejected(
            ERROR_PARAMS_SHA_MISMATCH,
            "The proposed change no longer matches the run's current state; "
            "refusing to execute an unconsented change.",
        )

    # Reassigned, not mutated in place, so the JSON column registers the change.
    run.state = {
        **run_state,
        "pending_confirmation": {**pending_state, "params_sha": expected_params_sha},
    }
    return option_id


__all__ = [
    "ERROR_APPROVER_NOT_SHOP_MEMBER",
    "ERROR_CONFIRMATION_ALREADY_DECIDED",
    "ERROR_CONFIRMATION_EXPIRED",
    "ERROR_CONFIRMATION_NOT_FOUND",
    "ERROR_INVALID_DECISION",
    "ERROR_OPTION_ID_REQUIRED",
    "ERROR_PARAMS_SHA_MISMATCH",
    "ERROR_RUN_NOT_AWAITING_CONFIRMATION",
    "ERROR_RUN_STATE_NOT_RECONSTRUCTABLE",
    "ERROR_UNKNOWN_OPTION_ID",
    "EXPIRED_CONFIRMATION_STATUS",
    "PENDING_CONFIRMATION_STATUS",
    "WAITING_APPROVAL_RUN_STATUS",
    "ConfirmationDecision",
    "ConfirmationRejected",
    "EditRejected",
    "as_aware_utc",
    "decide_confirmation",
    "decline_pending_confirmation",
    "transition_confirmation_or_none",
]
