"""Read-only run detail for staff (D25.9): timeline, LLM output, tokens.

Read under the shop's own scope (the caller wraps it in ``with_shop_scope``).
Nothing here writes. The route masks buyer PII in the whole payload.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WorkflowRun, WorkflowRunEvent

LIST_LIMIT = 50
#: Event types that carry the model's own words.
LLM_EVENT_TYPES = frozenset({"assistant.text"})


class RunNotFound(LookupError):
    pass


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _summary(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "workflow_key": run.workflow_key,
        "status": run.status,
        "stop_reason": run.stop_reason,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
    }


async def list_runs(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.shop_id == shop_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(LIST_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [_summary(run) for run in rows]


def _content_drafts(state: Any) -> list[dict[str, Any]]:
    content = state.get("content_run") if isinstance(state, dict) else None
    drafts = content.get("drafts") if isinstance(content, dict) else None
    return [d for d in drafts or [] if isinstance(d, dict)]


async def run_detail(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.shop_id != shop_id:
        raise RunNotFound(str(run_id))
    events = (
        (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.workflow_run_id == run_id)
                .order_by(WorkflowRunEvent.sequence_number)
            )
        )
        .scalars()
        .all()
    )
    timeline = [
        {
            "sequence": e.sequence_number,
            "type": e.event_type,
            "at": _iso(e.timestamp),
            "payload": e.payload,
        }
        for e in events
    ]
    llm_output = [
        {"sequence": e.sequence_number, "at": _iso(e.timestamp), "text": e.payload.get("text")}
        for e in events
        if e.event_type in LLM_EVENT_TYPES and isinstance(e.payload, dict)
    ]
    for draft in _content_drafts(run.state):
        llm_output.append(
            {
                "draft_version": draft.get("version"),
                "at": draft.get("at"),
                "model": draft.get("model"),
                "script": draft.get("script"),
                "error": draft.get("error"),
                "input_tokens": draft.get("input_tokens"),
                "output_tokens": draft.get("output_tokens"),
            }
        )
    return {**_summary(run), "timeline": timeline, "llm_output": llm_output}
