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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, RunConfirmation
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
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


async def list_runs(session: AsyncSession, shop_id: uuid.UUID, *, limit: int) -> list[RunListItem]:
    """The shop's runs, newest first. A queued run with no events is still listed."""
    result = await session.execute(
        select(WorkflowRunRow, Product)
        .where(WorkflowRunRow.shop_id == shop_id)
        .join(Product, WorkflowRunRow.product_id == Product.id)
        .order_by(WorkflowRunRow.created_at.desc())
        .limit(limit)
    )
    items: list[RunListItem] = []
    for run, product in result.all():
        decision_summary = None
        if run.status == WAITING_APPROVAL_RUN_STATUS:
            decision_summary = await _pending_decision(session, run.id)
        items.append(
            RunListItem(
                id=run.id,
                status=run.status,
                stop_reason=run.stop_reason,
                product_name=product.name,
                created_at=_iso(run.created_at) or "",
                completed_at=_iso(run.completed_at),
                running_seconds_elapsed=run.running_seconds_elapsed,
                latest_narration=await _latest_narration(session, run.id),
                decision_summary=decision_summary,
            )
        )
    return items


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
    payload = result.scalars().first()
    return payload.get("phase_narration") if isinstance(payload, dict) else None


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
    if confirmation is None:
        return None
    return PendingDecision(
        tool_call_id=confirmation.tool_call_id,
        expires_at=_iso(confirmation.expires_at) or str(confirmation.expires_at),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


__all__ = ["PendingDecision", "RunListItem", "STATUS_EVENT_TYPE", "list_runs"]
