"""When the agent run approved from a card confirmed its TikTok write (fast track P67, D75 Q1).

An agent run (ADR-083) moves its card to ``approved`` and never stamps the card's
``executed_at``: the write's confirmation lives on the run's ledger row
(``tool_executions.status == "succeeded"``, ADR-073 decision 3). The revision ladder
(``persist._card_still_stands``) reads an ``approved`` row with no ``executed_at`` as
"still in flight", forever -- so a (product, lever) Juli edited once kept every later
proposal for that lever suppressed as ``active_card_exists`` (the sandbox's August
title / description edits held both listing chains of its two best sellers, and the
operator-forced quick scan had nothing left to write).

:func:`confirmed_write_at` answers from the ledger: the run is over (``completed``)
and its WRITE went through (a refused write, ``ok: false``, never counts). The
ladder then treats the card as executed at that moment: the chain reopens after the
usual cooldown, exactly as ADR-087 decision 6 intends for an executed card.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, ToolExecution, WorkflowRun

#: The run finished normally (failed / cancelled / timed-out runs hand the card back).
_COMPLETED = "completed"
#: The ledger row of a WRITE that went through.
_SUCCEEDED = "succeeded"


def _refused(outcome_json: str | None) -> bool:
    """A stored tool result that says TikTok refused the write (``ok: false``)."""
    if not outcome_json:
        return False
    try:
        outcome = json.loads(outcome_json)
    except (TypeError, ValueError):
        return False
    return isinstance(outcome, dict) and outcome.get("ok") is False


async def confirmed_write_at(session: AsyncSession, card: ActionCard) -> datetime | None:
    """When a completed run approved from ``card`` had its last WRITE confirmed, else None."""
    rows = await session.execute(
        select(ToolExecution.updated_at, ToolExecution.outcome_json)
        .join(WorkflowRun, ToolExecution.workflow_run_id == WorkflowRun.id)
        .where(
            WorkflowRun.action_card_id == card.id,
            WorkflowRun.shop_id == card.shop_id,
            WorkflowRun.status == _COMPLETED,
            ToolExecution.status == _SUCCEEDED,
        )
    )
    confirmed = [at for at, outcome in rows.all() if at is not None and not _refused(outcome)]
    return max(confirmed) if confirmed else None


__all__ = ["confirmed_write_at"]
