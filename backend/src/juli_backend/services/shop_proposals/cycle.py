"""The manual cycle's state machine (ADR-118): propose → approve → execute → verify.

Every function runs under the caller's shop scope (``with_shop_scope``): the four
tables are tenant-direct, so RLS keeps one shop's records out of another's. Nothing
here commits; the route commits after the audit row.

Status moves only forward:

- ``draft`` → ``sent`` (:func:`send`) or ``withdrawn``;
- ``sent`` → ``approved`` / ``rejected`` / ``changes_requested`` (:func:`record_approval`),
  ``withdrawn`` or ``superseded`` (:func:`revise`);
- ``changes_requested`` → ``superseded`` (:func:`revise`) or ``withdrawn``;
- ``approved`` → ``executed`` (:func:`record_execution`) or ``withdrawn``;
- ``executed`` → ``measured`` (the measurement job, later).

A sent proposal is never edited: :func:`revise` writes a new revision and supersedes the
old one, so every approval points at the exact text the client saw.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import ITEM_LEVEL_VARIATION, PlatformItem
from juli_backend.models.shop_proposals import (
    APPROVAL_CHANNELS,
    CHANNEL_IN_APP,
    DECISIONS,
    EXECUTION_CHANNELS,
    EXECUTOR_ROLES,
    KINDS,
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_SENT,
    STATUS_SUPERSEDED,
    STATUS_WITHDRAWN,
    SUBJECT_ITEM,
    SUBJECT_TYPES,
    VERIFIED_HOW,
    ShopProposal,
    ShopProposalApproval,
    ShopProposalExecution,
)

ERROR_NOT_FOUND = "proposal_not_found"
ERROR_BAD_STATE = "proposal_bad_state"
ERROR_INVALID = "proposal_invalid"
ERROR_UNKNOWN_ITEM = "proposal_unknown_item"

_WITHDRAWABLE = frozenset({STATUS_DRAFT, STATUS_SENT, STATUS_CHANGES_REQUESTED, STATUS_APPROVED})
_REVISABLE = frozenset({STATUS_SENT, STATUS_CHANGES_REQUESTED})


class ProposalError(Exception):
    """A refused cycle step; ``status`` is the HTTP status the route returns."""

    def __init__(self, code: str, status: int, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class ProposalDraft:
    """What an operator writes; ``change_after`` and ``reason`` are seller-readable."""

    cycle: str
    kind: str
    subject_type: str
    subject_label: str
    change_after: dict[str, Any]
    reason: str
    item_id: str | None = None
    change_before: dict[str, Any] = field(default_factory=dict)
    planned_start: date | None = None
    lever_plan_id: uuid.UUID | None = None


def _check_draft(draft: ProposalDraft) -> None:
    if draft.kind not in KINDS:
        raise ProposalError(ERROR_INVALID, 422, f"kind must be one of {', '.join(KINDS)}")
    if draft.subject_type not in SUBJECT_TYPES:
        raise ProposalError(ERROR_INVALID, 422, "subject_type must be item, shop or campaign")
    if (draft.subject_type == SUBJECT_ITEM) != bool(draft.item_id):
        raise ProposalError(ERROR_INVALID, 422, "item_id is required for an item, and only then")
    if not draft.cycle.strip() or not draft.subject_label.strip() or not draft.reason.strip():
        raise ProposalError(ERROR_INVALID, 422, "cycle, subject_label and reason are required")
    if not draft.change_after:
        raise ProposalError(ERROR_INVALID, 422, "change_after is required")


async def _require_item(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, item_id: str
) -> None:
    """An item proposal names an item the shop's own exports listed."""
    found = await session.scalar(
        select(PlatformItem.id).where(
            PlatformItem.shop_id == shop_id,
            PlatformItem.platform == platform,
            PlatformItem.item_id == item_id,
            PlatformItem.variation_id == ITEM_LEVEL_VARIATION,
        )
    )
    if found is None:
        raise ProposalError(ERROR_UNKNOWN_ITEM, 422, "item_id is not in the shop's items")


def _new(
    shop_id: uuid.UUID,
    platform: str,
    draft: ProposalDraft,
    *,
    staff_id: uuid.UUID | None,
    now: datetime,
    revision: int = 1,
    supersedes_id: uuid.UUID | None = None,
) -> ShopProposal:
    return ShopProposal(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform=platform,
        cycle=draft.cycle.strip(),
        kind=draft.kind,
        subject_type=draft.subject_type,
        item_id=draft.item_id,
        subject_label=draft.subject_label.strip(),
        change_before=draft.change_before,
        change_after=draft.change_after,
        reason=draft.reason.strip(),
        planned_start=draft.planned_start,
        status=STATUS_DRAFT,
        revision=revision,
        supersedes_id=supersedes_id,
        lever_plan_id=draft.lever_plan_id,
        proposed_by_staff_id=staff_id,
        created_at=now,
        updated_at=now,
    )


async def create(
    session: AsyncSession,
    shop_id: uuid.UUID,
    platform: str,
    draft: ProposalDraft,
    *,
    staff_id: uuid.UUID | None,
    now: datetime,
) -> ShopProposal:
    """A new ``draft`` proposal."""
    _check_draft(draft)
    if draft.item_id is not None:
        await _require_item(session, shop_id, platform, draft.item_id)
    proposal = _new(shop_id, platform, draft, staff_id=staff_id, now=now)
    session.add(proposal)
    await session.flush()
    return proposal


async def get(session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID) -> ShopProposal:
    proposal = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == proposal_id, ShopProposal.shop_id == shop_id)
    )
    if proposal is None:
        raise ProposalError(ERROR_NOT_FOUND, 404)
    return proposal


def _move(proposal: ShopProposal, allowed: frozenset[str], to: str, now: datetime) -> None:
    if proposal.status not in allowed:
        raise ProposalError(
            ERROR_BAD_STATE, 409, f"cannot move a {proposal.status} proposal to {to}"
        )
    proposal.status = to
    proposal.updated_at = now


async def send(session: AsyncSession, proposal: ShopProposal, *, now: datetime) -> ShopProposal:
    """``draft`` → ``sent``: from here the text is frozen."""
    _move(proposal, frozenset({STATUS_DRAFT}), STATUS_SENT, now)
    proposal.sent_at = now
    await session.flush()
    return proposal


async def withdraw(session: AsyncSession, proposal: ShopProposal, *, now: datetime) -> ShopProposal:
    _move(proposal, _WITHDRAWABLE, STATUS_WITHDRAWN, now)
    await session.flush()
    return proposal


async def revise(
    session: AsyncSession,
    proposal: ShopProposal,
    draft: ProposalDraft,
    *,
    staff_id: uuid.UUID | None,
    now: datetime,
) -> ShopProposal:
    """A sent (or sent-back) proposal changes: the old one is superseded, a new draft starts."""
    _check_draft(draft)
    if draft.item_id is not None:
        await _require_item(session, proposal.shop_id, proposal.platform, draft.item_id)
    _move(proposal, _REVISABLE, STATUS_SUPERSEDED, now)
    successor = _new(
        proposal.shop_id,
        proposal.platform,
        draft,
        staff_id=staff_id,
        now=now,
        revision=proposal.revision + 1,
        supersedes_id=proposal.id,
    )
    session.add(successor)
    await session.flush()
    return successor


def snapshot(proposal: ShopProposal) -> dict[str, Any]:
    """The text the client decides on, stored verbatim with the decision."""
    return {
        "id": str(proposal.id),
        "revision": proposal.revision,
        "cycle": proposal.cycle,
        "kind": proposal.kind,
        "subject_type": proposal.subject_type,
        "item_id": proposal.item_id,
        "subject_label": proposal.subject_label,
        "change_before": proposal.change_before,
        "change_after": proposal.change_after,
        "reason": proposal.reason,
        "planned_start": proposal.planned_start.isoformat() if proposal.planned_start else None,
    }


async def record_approval(
    session: AsyncSession,
    proposal: ShopProposal,
    *,
    decision: str,
    channel: str,
    decided_at: datetime,
    now: datetime,
    decided_by_user_id: uuid.UUID | None = None,
    recorded_by_staff_id: uuid.UUID | None = None,
    evidence_ref: str | None = None,
    note: str | None = None,
) -> ShopProposalApproval:
    """The client's decision on a ``sent`` proposal.

    In the app the client's own user id decides; from an email or a document an operator
    records it and names where the evidence is kept (``evidence_ref``, a pointer, never
    the content).
    """
    if decision not in DECISIONS or channel not in APPROVAL_CHANNELS:
        raise ProposalError(ERROR_INVALID, 422, "unknown decision or channel")
    if channel == CHANNEL_IN_APP and decided_by_user_id is None:
        raise ProposalError(ERROR_INVALID, 422, "an in-app decision needs the client's user")
    if channel != CHANNEL_IN_APP and (
        recorded_by_staff_id is None or not (evidence_ref or "").strip()
    ):
        raise ProposalError(ERROR_INVALID, 422, "a recorded decision needs evidence_ref")
    if decided_at > now:
        raise ProposalError(ERROR_INVALID, 422, "decided_at is in the future")
    _move(proposal, frozenset({STATUS_SENT}), decision, now)
    approval = ShopProposalApproval(
        id=uuid.uuid4(),
        shop_id=proposal.shop_id,
        proposal_id=proposal.id,
        decision=decision,
        channel=channel,
        decided_by_user_id=decided_by_user_id,
        recorded_by_staff_id=recorded_by_staff_id,
        evidence_ref=(evidence_ref or "").strip() or None,
        proposal_snapshot=snapshot(proposal),
        note=note,
        decided_at=decided_at,
        created_at=now,
    )
    session.add(approval)
    await session.flush()
    return approval


async def record_execution(
    session: AsyncSession,
    proposal: ShopProposal,
    *,
    executed_at: datetime,
    executor_role: str,
    channel: str,
    now: datetime,
    executed_by_user_id: uuid.UUID | None = None,
    recorded_by_staff_id: uuid.UUID | None = None,
    recorded_by_user_id: uuid.UUID | None = None,
    evidence_ref: str | None = None,
) -> ShopProposalExecution:
    """The change was made on the shop (by hand today): ``approved`` → ``executed``."""
    if executor_role not in EXECUTOR_ROLES or channel not in EXECUTION_CHANNELS:
        raise ProposalError(ERROR_INVALID, 422, "unknown executor_role or channel")
    if recorded_by_staff_id is None and recorded_by_user_id is None:
        raise ProposalError(ERROR_INVALID, 422, "an execution needs who recorded it")
    if executed_at > now:
        raise ProposalError(ERROR_INVALID, 422, "executed_at is in the future")
    _move(proposal, frozenset({STATUS_APPROVED}), STATUS_EXECUTED, now)
    execution = ShopProposalExecution(
        id=uuid.uuid4(),
        shop_id=proposal.shop_id,
        proposal_id=proposal.id,
        executed_at=executed_at,
        executor_role=executor_role,
        executed_by_user_id=executed_by_user_id,
        recorded_by_staff_id=recorded_by_staff_id,
        recorded_by_user_id=recorded_by_user_id,
        channel=channel,
        evidence_ref=(evidence_ref or "").strip() or None,
        created_at=now,
    )
    session.add(execution)
    await session.flush()
    return execution


async def verify_execution(
    session: AsyncSession,
    shop_id: uuid.UUID,
    execution_id: uuid.UUID,
    *,
    verified_how: str,
    verified_state: dict[str, Any],
    verified_at: datetime,
) -> ShopProposalExecution:
    """The new state was read back (next export, sub-account read); once only."""
    if verified_how not in VERIFIED_HOW:
        raise ProposalError(ERROR_INVALID, 422, "unknown verified_how")
    execution = await session.scalar(
        select(ShopProposalExecution).where(
            ShopProposalExecution.id == execution_id, ShopProposalExecution.shop_id == shop_id
        )
    )
    if execution is None:
        raise ProposalError(ERROR_NOT_FOUND, 404)
    if execution.verified_at is not None:
        raise ProposalError(ERROR_BAD_STATE, 409, "already verified")
    execution.verified_at = verified_at
    execution.verified_how = verified_how
    execution.verified_state = verified_state
    await session.flush()
    return execution


async def list_cycle(
    session: AsyncSession, shop_id: uuid.UUID, cycle: str | None = None
) -> list[dict[str, Any]]:
    """Every proposal (optionally one cycle) with its approvals and executions, newest first."""
    query = select(ShopProposal).where(ShopProposal.shop_id == shop_id)
    if cycle:
        query = query.where(ShopProposal.cycle == cycle)
    proposals = list((await session.scalars(query.order_by(ShopProposal.created_at.desc()))).all())
    ids = [p.id for p in proposals]
    approvals: dict[uuid.UUID, list[ShopProposalApproval]] = {}
    executions: dict[uuid.UUID, list[ShopProposalExecution]] = {}
    if ids:
        for a in await session.scalars(
            select(ShopProposalApproval)
            .where(ShopProposalApproval.proposal_id.in_(ids))
            .order_by(ShopProposalApproval.decided_at)
        ):
            approvals.setdefault(a.proposal_id, []).append(a)
        for e in await session.scalars(
            select(ShopProposalExecution)
            .where(ShopProposalExecution.proposal_id.in_(ids))
            .order_by(ShopProposalExecution.executed_at)
        ):
            executions.setdefault(e.proposal_id, []).append(e)
    return [
        {
            **snapshot(p),
            "status": p.status,
            "platform": p.platform,
            "supersedes_id": str(p.supersedes_id) if p.supersedes_id else None,
            "sent_at": _iso(p.sent_at),
            "created_at": _iso(p.created_at),
            "approvals": [
                {
                    "id": str(a.id),
                    "decision": a.decision,
                    "channel": a.channel,
                    "evidence_ref": a.evidence_ref,
                    "note": a.note,
                    "decided_at": _iso(a.decided_at),
                }
                for a in approvals.get(p.id, [])
            ],
            "executions": [
                {
                    "id": str(e.id),
                    "executed_at": _iso(e.executed_at),
                    "executor_role": e.executor_role,
                    "channel": e.channel,
                    "evidence_ref": e.evidence_ref,
                    "verified_at": _iso(e.verified_at),
                    "verified_how": e.verified_how,
                }
                for e in executions.get(p.id, [])
            ],
        }
        for p in proposals
    ]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None
