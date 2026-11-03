"""Juli Ops: the manual cycle of a shop (ADR-118).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth dependencies
(Cloudflare Access → Supabase → active staff row → role) and PII-masking route class.
Every write runs under the shop's own scope (the four tables are tenant-direct) and is
audited in ``ops_audit_log``.

- ``GET  /v1/ops/shops/{id}/proposals[?cycle=]`` (Xem+) -- proposals with their
  approvals and executions, newest first.
- ``POST /v1/ops/shops/{id}/proposals`` (Vận hành) -- a new draft. An item proposal must
  name an item the shop's exports listed (``platform_items``).
- ``POST .../proposals/{pid}/send`` -- draft → sent; the text is frozen from here.
- ``POST .../proposals/{pid}/revise`` -- a sent (or sent-back) proposal changes: the old
  one is superseded and a new revision starts as a draft.
- ``POST .../proposals/{pid}/withdraw``
- ``POST .../proposals/{pid}/approvals`` -- the client's decision from an email or a
  document, with ``evidence_ref`` (where the evidence is kept). In-app decisions come
  from the seller route, never from here.
- ``POST .../proposals/{pid}/executions`` -- the change was made on the shop.
- ``POST .../proposals/{pid}/executions/{eid}/verify`` -- the new state was read back.
- ``POST .../proposals/{pid}/measure`` -- "Tính lại": measure an executed proposal now
  (the daily beat does it for every shop; the list carries the results).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _shop, operator, viewer
from juli_backend.database import Shop, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.shop_proposals import STATUS_EXECUTED
from juli_backend.services import shop_proposals
from juli_backend.services.ops import audit

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_PROPOSAL_CREATE = "proposal_create"
ACTION_PROPOSAL_SEND = "proposal_send"
ACTION_PROPOSAL_REVISE = "proposal_revise"
ACTION_PROPOSAL_WITHDRAW = "proposal_withdraw"
ACTION_PROPOSAL_APPROVAL = "proposal_approval_record"
ACTION_PROPOSAL_EXECUTION = "proposal_execution_record"
ACTION_PROPOSAL_VERIFY = "proposal_execution_verify"
ACTION_PROPOSAL_MEASURE = "proposal_measure"


class ProposalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle: str = Field(min_length=1, max_length=64)
    kind: str
    subject_type: Literal["item", "shop", "campaign"]
    item_id: str | None = Field(default=None, max_length=64)
    subject_label: str = Field(min_length=1, max_length=255)
    change_before: dict[str, Any] = Field(default_factory=dict)
    change_after: dict[str, Any]
    reason: str = Field(min_length=1)
    planned_start: date | None = None
    lever_plan_id: uuid.UUID | None = None

    def draft(self) -> shop_proposals.ProposalDraft:
        return shop_proposals.ProposalDraft(**self.model_dump())


class ApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected", "changes_requested"]
    channel: Literal["email", "document"]
    evidence_ref: str = Field(min_length=1, max_length=500)
    decided_at: datetime
    note: str | None = None


class ExecutionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executed_at: datetime
    executor_role: Literal["client_representative", "juli_operator"]
    evidence_ref: str | None = Field(default=None, max_length=500)


class VerifyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified_how: Literal["export_readback", "sub_account_read"]
    verified_state: dict[str, Any]
    verified_at: datetime


def _naive_utc(value: datetime) -> datetime:
    """Request times may carry an offset; the tables store naive UTC."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _refused(exc: shop_proposals.ProposalError) -> HTTPException:
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.detail or exc.code}
    )


async def _platform(session: AsyncSession, shop_id: uuid.UUID) -> str:
    await _shop(session, shop_id)
    platform = await session.scalar(select(Shop.platform).where(Shop.id == shop_id))
    return platform or "tiktok"


async def _audited(
    session: AsyncSession,
    ctx: OpsContext,
    shop_id: uuid.UUID,
    action: str,
    after: dict[str, Any],
) -> None:
    await audit.record(session, ctx.staff.actor, action, shop_id=shop_id, after=after)
    await session.commit()


@router.get("/shops/{shop_id}/proposals")
async def ops_list_proposals(
    shop_id: uuid.UUID,
    cycle: str | None = Query(default=None, max_length=64),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        proposals = await shop_proposals.list_cycle(session, shop_id, cycle)
    return {"proposals": proposals}


@router.post("/shops/{shop_id}/proposals", status_code=201)
async def ops_create_proposal(
    shop_id: uuid.UUID,
    body: ProposalWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    platform = await _platform(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            proposal = await shop_proposals.create(
                session, shop_id, platform, body.draft(), staff_id=ctx.staff.id, now=_now()
            )
            after = shop_proposals.snapshot(proposal)
        await _audited(session, ctx, shop_id, ACTION_PROPOSAL_CREATE, after)
    except shop_proposals.ProposalError as exc:
        await session.rollback()
        raise _refused(exc) from None
    return {"proposal": {**after, "status": proposal.status}}


async def _step(
    session: AsyncSession,
    ctx: OpsContext,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    action: str,
    step: Any,
) -> dict[str, Any]:
    """Load the proposal under the shop's scope, run ``step``, audit, commit."""
    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            proposal = await shop_proposals.get(session, shop_id, proposal_id)
            after = await step(proposal)
        await _audited(session, ctx, shop_id, action, after)
    except shop_proposals.ProposalError as exc:
        await session.rollback()
        raise _refused(exc) from None
    return after


@router.post("/shops/{shop_id}/proposals/{proposal_id}/send")
async def ops_send_proposal(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        await shop_proposals.send(session, proposal, now=_now())
        return {"proposal_id": str(proposal.id), "status": proposal.status}

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_SEND, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/withdraw")
async def ops_withdraw_proposal(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        await shop_proposals.withdraw(session, proposal, now=_now())
        return {"proposal_id": str(proposal.id), "status": proposal.status}

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_WITHDRAW, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/revise", status_code=201)
async def ops_revise_proposal(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ProposalWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        successor = await shop_proposals.revise(
            session, proposal, body.draft(), staff_id=ctx.staff.id, now=_now()
        )
        return {
            "superseded_id": str(proposal.id),
            "proposal": {**shop_proposals.snapshot(successor), "status": successor.status},
        }

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_REVISE, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/approvals", status_code=201)
async def ops_record_approval(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ApprovalWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        approval = await shop_proposals.record_approval(
            session,
            proposal,
            decision=body.decision,
            channel=body.channel,
            decided_at=_naive_utc(body.decided_at),
            now=_now(),
            recorded_by_staff_id=ctx.staff.id,
            evidence_ref=body.evidence_ref,
            note=body.note,
        )
        return {
            "proposal_id": str(proposal.id),
            "approval_id": str(approval.id),
            "status": proposal.status,
            "channel": approval.channel,
            "evidence_ref": approval.evidence_ref,
        }

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_APPROVAL, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/executions", status_code=201)
async def ops_record_execution(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ExecutionWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        execution = await shop_proposals.record_execution(
            session,
            proposal,
            executed_at=_naive_utc(body.executed_at),
            executor_role=body.executor_role,
            channel="ops",
            now=_now(),
            recorded_by_staff_id=ctx.staff.id,
            evidence_ref=body.evidence_ref,
        )
        return {
            "proposal_id": str(proposal.id),
            "execution_id": str(execution.id),
            "status": proposal.status,
            "executor_role": execution.executor_role,
        }

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_EXECUTION, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/executions/{execution_id}/verify")
async def ops_verify_execution(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    execution_id: uuid.UUID,
    body: VerifyWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def step(proposal: Any) -> dict[str, Any]:
        execution = await shop_proposals.verify_execution(
            session,
            shop_id,
            execution_id,
            verified_how=body.verified_how,
            verified_state=body.verified_state,
            verified_at=_naive_utc(body.verified_at),
        )
        if execution.proposal_id != proposal.id:
            raise shop_proposals.ProposalError(shop_proposals.ERROR_NOT_FOUND, 404)
        return {
            "proposal_id": str(proposal.id),
            "execution_id": str(execution.id),
            "verified_how": execution.verified_how,
        }

    return await _step(session, ctx, shop_id, proposal_id, ACTION_PROPOSAL_VERIFY, step)


@router.post("/shops/{shop_id}/proposals/{proposal_id}/measure")
async def ops_measure_proposal(
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recompute one executed proposal's result now, ignoring the beat's skip check."""
    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            proposal = await shop_proposals.get(session, shop_id, proposal_id)
        if proposal.status != STATUS_EXECUTED:
            raise shop_proposals.ProposalError(
                shop_proposals.ERROR_BAD_STATE, 409, "only an executed proposal is measured"
            )
        counts = await shop_proposals.measure_shop_proposals(
            session, shop_id, now=_now(), proposal_id=proposal_id, force=True
        )
        after = {
            "proposal_id": str(proposal_id),
            "written": counts.written,
            "measured": counts.measured,
        }
        await _audited(session, ctx, shop_id, ACTION_PROPOSAL_MEASURE, after)
    except shop_proposals.ProposalError as exc:
        await session.rollback()
        raise _refused(exc) from None
    return after
