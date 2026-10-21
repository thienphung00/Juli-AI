"""The seller's polled run list (ADR-083 T4, #1310).

A read model, not a resource: each item is assembled from ``workflow_runs``,
the bound product, the latest ``workflow.status`` narration, and -- for a
run paused on a CONFIRM -- its pending confirmation. No tool names, playbook
keys or internal identifiers leave this function.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    WRITE_MODE_SIMULATED,
    Product,
    RunConfirmation,
    ToolExecution,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services import lever_flows
from juli_backend.services.agent_runs.confirmations import (
    PENDING_CONFIRMATION_STATUS,
    WAITING_APPROVAL_RUN_STATUS,
)

STATUS_EVENT_TYPE = "workflow.status"


@dataclass(frozen=True)
class PendingDecision:
    tool_call_id: str
    expires_at: str


@dataclass(frozen=True)
class RunListItem:
    id: uuid.UUID
    status: str
    stop_reason: str | None
    product_name: str
    created_at: str
    completed_at: str | None
    running_seconds_elapsed: int
    latest_narration: str | None
    decision_summary: PendingDecision | None
    #: Fast track P10-B (contract §4/§5): ``photo`` / ``seller_action`` while the
    #: run waits for the seller, else ``None``.
    awaiting: str | None = None
    #: P10 integration: the Quyết định card (``action_cards.id``) this run came
    #: from, so the UI joins runs to cards by id rather than by product name.
    decision_id: uuid.UUID | None = None
    #: Fast track P61-B (D71.2): the run's writes went to the sandbox merchant,
    #: not the seller's shop. The run surface says "chạy thử" instead of
    #: "Đã áp dụng". True only for a run that actually wrote.
    simulated: bool = False


#: A ledger row the agent wrote for a WRITE that went through.
_SUCCEEDED = "succeeded"


async def list_runs(session: AsyncSession, shop_id: uuid.UUID, *, limit: int) -> list[RunListItem]:
    """The shop's runs, newest first. A queued run with no events is still listed.

    Three statements whatever the number of runs (P22): the runs, every run's
    latest narration, every waiting run's pending confirmation. This used to
    read the narration (and the confirmation) once PER RUN -- up to 200
    sequential round trips for the default limit, ~220 ms each in production.
    """
    result = await session.execute(
        select(WorkflowRunRow, Product)
        .where(WorkflowRunRow.shop_id == shop_id)
        .join(Product, WorkflowRunRow.product_id == Product.id)
        .order_by(WorkflowRunRow.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    narrations = await _latest_narrations(session, [run.id for run, _ in rows])
    waiting = [run.id for run, _ in rows if run.status == WAITING_APPROVAL_RUN_STATUS]
    decisions = await _pending_decisions(session, waiting)
    simulated = await _simulated_writes(
        session, [run.id for run, _ in rows if run.write_mode == WRITE_MODE_SIMULATED]
    )
    items: list[RunListItem] = []
    for run, product in rows:
        items.append(
            RunListItem(
                id=run.id,
                status=run.status,
                stop_reason=run.stop_reason,
                product_name=product.name,
                created_at=_iso(run.created_at) or "",
                completed_at=_iso(run.completed_at),
                running_seconds_elapsed=run.running_seconds_elapsed,
                latest_narration=narrations.get(run.id),
                decision_summary=decisions.get(run.id),
                awaiting=lever_flows.awaiting_of(run),
                decision_id=run.action_card_id,
                simulated=run.id in simulated,
            )
        )
    return items


async def _simulated_writes(session: AsyncSession, run_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Of the runs stamped ``simulated``, those that wrote something (one statement)."""
    if not run_ids:
        return set()
    from juli_backend.services.agent import composition

    result = await session.execute(
        select(ToolExecution.workflow_run_id)
        .where(
            ToolExecution.workflow_run_id.in_(run_ids),
            ToolExecution.status == _SUCCEEDED,
            ToolExecution.tool_name.in_(composition.measurable_write_tool_names()),
        )
        .distinct()
    )
    return {run_id for run_id in result.scalars().all() if run_id is not None}


async def _latest_narrations(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Each run's newest ``workflow.status`` narration, in one statement."""
    if not run_ids:
        return {}
    newest = (
        select(
            WorkflowRunEventRow.workflow_run_id.label("run_id"),
            WorkflowRunEventRow.payload.label("payload"),
            func.row_number()
            .over(
                partition_by=WorkflowRunEventRow.workflow_run_id,
                order_by=WorkflowRunEventRow.sequence_number.desc(),
            )
            .label("rank"),
        )
        .where(
            WorkflowRunEventRow.workflow_run_id.in_(run_ids),
            WorkflowRunEventRow.event_type == STATUS_EVENT_TYPE,
        )
        .subquery()
    )
    result = await session.execute(
        select(newest.c.run_id, newest.c.payload).where(newest.c.rank == 1)
    )
    return {run_id: _narration_of(payload) for run_id, payload in result.all()}


def _narration_of(payload: object) -> str | None:
    return payload.get("phase_narration") if isinstance(payload, dict) else None


async def _pending_decisions(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PendingDecision]:
    """Each waiting run's pending confirmation (one per run), in one statement."""
    if not run_ids:
        return {}
    result = await session.execute(
        select(RunConfirmation).where(
            RunConfirmation.workflow_run_id.in_(run_ids),
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
    )
    found: dict[uuid.UUID, PendingDecision] = {}
    for confirmation in result.scalars().all():
        found.setdefault(confirmation.workflow_run_id, _decision_of(confirmation))
    return found


def _decision_of(confirmation: RunConfirmation) -> PendingDecision:
    return PendingDecision(
        tool_call_id=confirmation.tool_call_id,
        expires_at=_iso(confirmation.expires_at) or str(confirmation.expires_at),
    )


async def _latest_narration(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    result = await session.execute(
        select(WorkflowRunEventRow.payload)
        .where(
            WorkflowRunEventRow.workflow_run_id == run_id,
            WorkflowRunEventRow.event_type == STATUS_EVENT_TYPE,
        )
        .order_by(WorkflowRunEventRow.sequence_number.desc())
        .limit(1)
    )
    return _narration_of(result.scalars().first())


async def _pending_decision(session: AsyncSession, run_id: uuid.UUID) -> PendingDecision | None:
    result = await session.execute(
        select(RunConfirmation)
        .where(
            RunConfirmation.workflow_run_id == run_id,
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
        .limit(1)
    )
    confirmation = result.scalars().first()
    return None if confirmation is None else _decision_of(confirmation)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def latest_narration(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    return await _latest_narration(session, run_id)


async def pending_decision(session: AsyncSession, run_id: uuid.UUID) -> PendingDecision | None:
    return await _pending_decision(session, run_id)


__all__ = [
    "PendingDecision",
    "RunListItem",
    "STATUS_EVENT_TYPE",
    "latest_narration",
    "list_runs",
    "pending_decision",
]
