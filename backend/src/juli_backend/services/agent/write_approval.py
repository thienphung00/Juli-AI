"""A change to a client's shop needs that shop's own click (ADR-116 §6, D76, grill D7).

Two halves, both in the service layer (RLS is not the check: a reviewer's request runs
under the pinned shop's owner GUC, so the database cannot tell the reviewer from the owner).

**Who may click (:func:`approver_kind`).** Approving a card (``approve_action_card``) and
approving the exact change at the CONFIRM pause (``agent_runs.decide_confirmation``) are
refused unless the user belongs to the shop. Shop membership in this codebase is
``shops.user_id`` -- one owner per shop, no member table -- so "belongs" means "is the
owner". The one exception is D73: the partner reviewer, on a reviewer request, may approve
its pinned shop while that pin is Juli's writable TikTok **sandbox** shop (an active
reviewer account, ``REVIEWER_SHOP_ID`` = this shop, ``classify_pin`` = sandbox with writes
on). Ops / staff sessions never reach these routes (``/v1/ops`` is separate) and, owning
no client shop, would be refused here anyway. There is no operator-recorded approval path.

**What the executor needs before a live write (:func:`verify_write_approval`).** On the
resume leg of a run whose shop is production-enabled, before any authorization is looked
up (so a refusal spends nothing), the run must carry:

1. the frozen ``approved_change`` the CONFIRM click recorded (:func:`freeze_approved_change`):
   who clicked, when, the card approval it rests on (id + SHA-256 of its ``card_snapshot``),
   the field values the seller saw as "before", the exact arguments as "after", and a
   SHA-256 over all of it;
2. the card's own ``action_card_approvals`` row when the run came from a card;
3. both clicks by the shop's owner (re-checked at write time);
4. both clicks younger than :data:`APPROVAL_TTL_HOURS` -- otherwise the card goes back to
   ``active`` (pending, needs re-approval) and nothing is written;
5. an exact match: the arguments about to be written equal the approved "after", the card
   approval's snapshot still hashes to what was approved, the block's own hash holds.

Then the executor's before-read (``ProductToolExecutor``, immediately before the vendor
call) must still equal the approved "before" (D11-1 made enforcing, not only recorded).
Every refusal is an append-only ``production_write_audit`` row with its reason code
(``PreconditionName``) and the run ends with nothing written to the shop.

Phase 1: Juli does not write to a client's shop; nothing here adds a path that would.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCardApproval, Shop
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.runner.write_capture import FIELDS_BY_OPERATION, field_values

logger = logging.getLogger(__name__)

#: D7.3 (owner, 2026-10-26): an approval older than this no longer authorizes a write.
APPROVAL_TTL_HOURS = 72
APPROVAL_TTL = timedelta(hours=APPROVAL_TTL_HOURS)

#: The key on ``run.state["pending_confirmation"]`` the CONFIRM click freezes.
APPROVED_CHANGE_KEY = "approved_change"
APPROVED_CHANGE_VERSION = 1

APPROVER_SHOP_OWNER = "shop_owner"
APPROVER_SANDBOX_REVIEWER = "sandbox_reviewer"


class ApproverNotShopMember(Exception):
    """The user clicking approve does not belong to the shop (no write, no run)."""


class WriteApprovalRefused(RuntimeError):
    """A live write's approval failed a D7 check; nothing is written.

    ``reason`` is the ``PreconditionName`` value audited in ``production_write_audit``.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"write approval refused: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason


@dataclass(frozen=True)
class ApprovedWrite:
    """What a verified approval hands the executor: the "before" the read-back must equal."""

    before: dict[str, Any]
    before_hashes: dict[str, str | None] = field(default_factory=dict)
    action_card_approval_id: str | None = None


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def canonical_sha256(value: Any) -> str:
    """SHA-256 of ``value`` as canonical JSON (sorted keys, no whitespace, UTF-8)."""
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def card_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(snapshot))


def _block_sha256(block: Mapping[str, Any]) -> str:
    return canonical_sha256({k: v for k, v in block.items() if k != "sha256"})


# -- who may click ---------------------------------------------------------------------------


async def is_shop_owner(session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether ``user_id`` owns ``shop_id`` (``shops.user_id``: the shop's only member)."""
    owner = (
        await session.execute(select(Shop.user_id).where(Shop.id == shop_id))
    ).scalar_one_or_none()
    return owner is not None and owner == user_id


async def _is_pinned_sandbox_reviewer(
    session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """D73: an active reviewer, on a reviewer request, approving its writable sandbox pin."""
    from juli_backend.integrations.tiktok import reviewer_session_active
    from juli_backend.services import reviewer as reviewer_service

    if not reviewer_session_active():
        return False
    if reviewer_service.config.reviewer_shop_id() != shop_id:
        return False
    account = await reviewer_service.accounts.load_account(session, user_id)
    if account is None or account.status() != reviewer_service.accounts.STATUS_ACTIVE:
        return False
    pinned = reviewer_service.pin_cache.cached(shop_id)
    pin = pinned.pin if pinned is not None else None
    if pin is None:
        pin = await reviewer_service.sandbox.classify_pin(session, shop_id)
    return pin.sandbox and pin.writes_enabled


async def approver_kind(session: AsyncSession, *, shop_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """:data:`APPROVER_SHOP_OWNER` / :data:`APPROVER_SANDBOX_REVIEWER`, else raise
    :class:`ApproverNotShopMember`."""
    if await is_shop_owner(session, shop_id, user_id):
        return APPROVER_SHOP_OWNER
    if await _is_pinned_sandbox_reviewer(session, shop_id, user_id):
        return APPROVER_SANDBOX_REVIEWER
    logger.warning(
        "approval_refused_not_shop_member",
        extra={"shop_id": str(shop_id), "user_id": str(user_id)},
    )
    raise ApproverNotShopMember(f"User {user_id} does not belong to shop {shop_id}")


# -- the frozen approval -----------------------------------------------------------------------


async def latest_card_approval(
    session: AsyncSession, action_card_id: uuid.UUID
) -> ActionCardApproval | None:
    return (
        (
            await session.execute(
                select(ActionCardApproval)
                .where(ActionCardApproval.action_card_id == action_card_id)
                .order_by(ActionCardApproval.approved_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


def approved_before_values(
    run_state: Mapping[str, Any], tool_name: str, arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The values the seller saw as "before" for the fields this write sets, and their hashes.

    A "Hoàn tác" run restores fields that must still hold Juli's after-values (its plan's
    ``expected`` / ``expected_hashes``); any other run's "before" is the product detail the
    run read before drafting (``run.state["product_detail"]``), for the fields the
    arguments set.
    """
    from juli_backend.services.run_changes import revert_plan_from_state

    fields = FIELDS_BY_OPERATION.get(tool_name, ())
    plan = revert_plan_from_state(run_state)
    if plan is not None:
        hashes = dict(plan.expected_hashes or {})
        before = {f: plan.expected[f] for f in fields if f in plan.expected}
        return before, {f: hashes.get(f) for f in before}
    detail = run_state.get("product_detail")
    if not isinstance(detail, Mapping):
        return {}, {}
    values = field_values(tool_name, detail)
    return {f: values.get(f) for f in fields if f in arguments}, {}


def approved_change_block(
    run_state: Mapping[str, Any],
    *,
    decided_by_user_id: uuid.UUID,
    decided_at: datetime,
    card_approval: ActionCardApproval | None,
) -> dict[str, Any]:
    """The ``approved_change`` block for the run's pending call (pure; see the caller)."""
    pending = run_state["pending_confirmation"]
    tool_name = str(pending.get("tool_name") or "")
    arguments = dict(pending["arguments"])
    before, before_hashes = approved_before_values(run_state, tool_name, arguments)
    block: dict[str, Any] = {
        "version": APPROVED_CHANGE_VERSION,
        "tool_name": tool_name,
        "decided_by_user_id": str(decided_by_user_id),
        "decided_at": _naive_utc(decided_at).isoformat(),
        "action_card_approval_id": str(card_approval.id) if card_approval else None,
        "card_snapshot_sha256": (
            card_snapshot_sha256(card_approval.card_snapshot) if card_approval else None
        ),
        "before": before,
        "before_hashes": before_hashes,
        "after": arguments,
    }
    block["sha256"] = _block_sha256(block)
    return block


async def freeze_approved_change(
    session: AsyncSession,
    run: WorkflowRunRow,
    *,
    decided_by_user_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Freeze what the CONFIRM click approved onto ``pending_confirmation`` (no commit).

    Called after the consent binding and any seller edit, so ``arguments`` is exactly what
    the resume will execute. Returns the block, or ``None`` when the run has no pending call.
    """
    state: dict[str, Any] = run.state if isinstance(run.state, dict) else {}
    pending = state.get("pending_confirmation")
    if not isinstance(pending, dict) or not isinstance(pending.get("arguments"), dict):
        return None
    card_approval = (
        await latest_card_approval(session, run.action_card_id)
        if run.action_card_id is not None
        else None
    )
    block = approved_change_block(
        state,
        decided_by_user_id=decided_by_user_id,
        decided_at=now or utc_now_naive(),
        card_approval=card_approval,
    )
    run.state = {**state, "pending_confirmation": {**pending, APPROVED_CHANGE_KEY: block}}
    return block


# -- the executor's check ----------------------------------------------------------------------


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _naive_utc(value)
    try:
        return _naive_utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


async def return_card_to_pending(session: AsyncSession, run: WorkflowRunRow) -> bool:
    """D7.3: an expired approval sends the run's card back to ``active`` (needs re-approval).

    The run ends ``failed`` on this refusal, so this is the one card transition for that
    (``card_reactivation.reactivate_card_for_ended_run``), written now -- with the refusal's
    audit row -- rather than only by the crash handler. In a SAVEPOINT: a newer active card
    for the same subject (the partial unique index) keeps that one. Returns whether the
    card moved.
    """
    from juli_backend.services.agent.card_reactivation import reactivate_card_for_ended_run
    from juli_backend.services.agent.status import WorkflowRunStatus

    try:
        async with session.begin_nested():
            return await reactivate_card_for_ended_run(session, run, WorkflowRunStatus.FAILED)
    except IntegrityError:
        logger.warning(
            "approval_expired_card_not_reopened",
            extra={"shop_id": str(run.shop_id), "action_card_id": str(run.action_card_id)},
        )
        return False


async def verify_write_approval(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    tool_name: str,
    pending: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> ApprovedWrite:
    """Raise :class:`WriteApprovalRefused` unless the run carries a valid D7 approval."""
    from juli_backend.services.execution.production_write_resolver import PreconditionName

    clock = _naive_utc(now or utc_now_naive())
    run = await session.get(WorkflowRunRow, run_id)
    block = pending.get(APPROVED_CHANGE_KEY) if isinstance(pending, Mapping) else None
    if run is None or run.shop_id != shop_id or not isinstance(block, Mapping):
        raise WriteApprovalRefused(PreconditionName.NO_SHOP_MEMBER_APPROVAL.value)

    card_approval: ActionCardApproval | None = None
    if run.action_card_id is not None:
        card_approval = await latest_card_approval(session, run.action_card_id)
        if card_approval is None:
            raise WriteApprovalRefused(PreconditionName.NO_SHOP_MEMBER_APPROVAL.value, "card")

    decided_by = _uuid_or_none(block.get("decided_by_user_id"))
    approvers = [decided_by] + ([card_approval.approved_by_user_id] if card_approval else [])
    for approver in approvers:
        if approver is None or not await is_shop_owner(session, shop_id, approver):
            raise WriteApprovalRefused(PreconditionName.APPROVER_NOT_SHOP_MEMBER.value)

    clicks = [_datetime_or_none(block.get("decided_at"))] + (
        [_naive_utc(card_approval.approved_at)] if card_approval else []
    )
    if any(at is None or clock - at > APPROVAL_TTL for at in clicks):
        await return_card_to_pending(session, run)
        raise WriteApprovalRefused(PreconditionName.APPROVAL_EXPIRED.value)

    arguments = pending.get("arguments") if isinstance(pending, Mapping) else None
    before = block.get("before")
    mismatch = (
        block.get("sha256") != _block_sha256(block)
        or block.get("tool_name") != tool_name
        or not isinstance(arguments, Mapping)
        or canonical_sha256(block.get("after")) != canonical_sha256(dict(arguments))
        or not isinstance(before, Mapping)
        or not before
    )
    if card_approval is not None and not mismatch:
        mismatch = block.get("action_card_approval_id") != str(card_approval.id) or block.get(
            "card_snapshot_sha256"
        ) != card_snapshot_sha256(card_approval.card_snapshot)
    if mismatch:
        raise WriteApprovalRefused(PreconditionName.APPROVAL_SNAPSHOT_MISMATCH.value)

    assert isinstance(before, Mapping)  # narrowed by the mismatch check
    hashes = block.get("before_hashes")
    return ApprovedWrite(
        before=dict(before),
        before_hashes=dict(hashes) if isinstance(hashes, Mapping) else {},
        action_card_approval_id=str(card_approval.id) if card_approval else None,
    )


__all__ = [
    "APPROVAL_TTL",
    "APPROVAL_TTL_HOURS",
    "APPROVED_CHANGE_KEY",
    "APPROVER_SANDBOX_REVIEWER",
    "APPROVER_SHOP_OWNER",
    "ApprovedWrite",
    "ApproverNotShopMember",
    "WriteApprovalRefused",
    "approved_before_values",
    "approved_change_block",
    "approver_kind",
    "canonical_sha256",
    "card_snapshot_sha256",
    "freeze_approved_change",
    "is_shop_owner",
    "latest_card_approval",
    "return_card_to_pending",
    "verify_write_approval",
]
