"""Public Mock Demo approve -> execute — local/demo records only (#717, B-5).

ADR-037 (Demo no-auth) / ADR-038 §9 (dry-run): a public Demo visitor approving
a Decision (`ActionCard`) must never trigger a real Partner (TikTok) write and
must never require reference-merchant credentials. This module is the *entire*
approve -> execute path for that flow — deliberately an isolated module rather
than a `dry_run` flag threaded onto the real execution path
(`services.execution.dispatch.enqueue_approved_tool` /
`services.execution.runner.run_tool_async`), because a flag is one bad
conditional away from a real Partner write against reference-merchant
credentials. See MODULE.md for the full write-up, including why this module's
own source files must never import `juli_backend.integrations.tiktok` or
`juli_backend.services.execution` (statically verified by
`tests/unit/test_demo_execution_import_boundary.py`, AC3).

Everything here runs synchronously, in-process, against local Postgres rows
only: no Celery task, no TikTok client, no network call of any kind.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, DemoExecutionRecord

Clock = Callable[[], datetime]


class DemoExecutionState(StrEnum):
    """Progress state machine for a demo dry-run execution (#717, B-5, AC2)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"


class DecisionNotFound(ValueError):
    """Raised when the approve target Decision does not exist for the shop."""


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _append_narrative_step(
    narrative: list[dict[str, str]],
    state: DemoExecutionState,
    at: datetime,
    message: str,
) -> None:
    narrative.append({"state": state.value, "message": message, "at": at.isoformat()})


async def approve_decision_dry_run(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    action_card_id: uuid.UUID,
    now: Clock | None = None,
) -> DemoExecutionRecord:
    """Approve a Decision on Demo and run its dry-run execution locally.

    Marks the target `ActionCard` approved (seller-lifecycle `status`/
    `approved_at`, ADR-021 — the first writer of the `"approved"` transition;
    B-3's `IN_FLIGHT_STATUSES` skip-on-rescoring guard already expects it) and
    creates a `DemoExecutionRecord` that progresses `queued -> running -> done`
    synchronously within this call, appending a `{state, message, at}` step to
    `narrative_json` at each transition for Track B UI (#600, execution
    progress card #696/#697) to render.

    Raises `DecisionNotFound` if no `ActionCard` with `action_card_id` exists
    for `shop_id` (tenant-scoped lookup — never leaks another shop's row).
    """
    clock = now or _default_clock

    card = await session.get(ActionCard, action_card_id)
    if card is None or card.shop_id != shop_id:
        raise DecisionNotFound(f"Decision {action_card_id} not found for shop {shop_id}")

    approved_at = clock()
    card.status = "approved"
    card.approved_at = approved_at

    narrative: list[dict[str, str]] = []
    record = DemoExecutionRecord(
        shop_id=shop_id,
        action_card_id=action_card_id,
        workflow_key=card.workflow_key,
        status=DemoExecutionState.QUEUED.value,
        narrative_json="[]",
        started_at=approved_at,
    )
    session.add(record)
    await session.flush()

    _append_narrative_step(
        narrative,
        DemoExecutionState.QUEUED,
        approved_at,
        "Approved — queued for dry-run execution.",
    )

    running_at = clock()
    record.status = DemoExecutionState.RUNNING.value
    _append_narrative_step(
        narrative,
        DemoExecutionState.RUNNING,
        running_at,
        "Simulating execution (dry-run demo — no live Partner calls).",
    )

    done_at = clock()
    record.status = DemoExecutionState.DONE.value
    record.completed_at = done_at
    _append_narrative_step(
        narrative,
        DemoExecutionState.DONE,
        done_at,
        "Dry-run execution complete.",
    )

    record.narrative_json = json.dumps(narrative)
    await session.flush()
    return record


def narrative_steps(record: DemoExecutionRecord) -> list[dict[str, str]]:
    """Decode `record.narrative_json` — convenience for callers (API layer, UI)."""
    return json.loads(record.narrative_json)
