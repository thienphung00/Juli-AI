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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import RunConfirmation
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.status import WorkflowRunStatus

logger = logging.getLogger(__name__)

WAITING_APPROVAL_RUN_STATUS = WorkflowRunStatus.WAITING_APPROVAL.value
PENDING_CONFIRMATION_STATUS = "pending"
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


async def decide_confirmation(
    session: AsyncSession,
    run: WorkflowRunRow,
    *,
    tool_call_id: str,
    decision: str,
    option_id: str | None,
    now: datetime | None = None,
) -> ConfirmationDecision:
    """Walk the ladder for ``run`` and win the transition, or raise :class:`ConfirmationRejected`.

    On approve, the confirmed ``params_sha`` is frozen onto ``run.state`` so
    ``WorkflowRunner.resume`` can re-derive and compare independently before
    executing. The caller must commit.
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
        selected_option_id = _bind_consent(run, confirmation, option_id)
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
    "as_aware_utc",
    "decide_confirmation",
    "transition_confirmation_or_none",
]
