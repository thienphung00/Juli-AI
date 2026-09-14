"""The async seam where a completed agent write records its outcome
(issue #1939, W8-F / P10-8).

**Why this module exists at all.** `workflow_outcome_records` had never held
a row: `services/operations/outcome_tracking.py::record_workflow_outcome` was
only ever called from the legacy Celery-approval path
(`services/execution/worker.py`), and the agent runner dispatches its writes
through `ToolExecutionLedger` instead. #1655's outcome chain therefore read
the state-change link as `missing` after every real agent write — an honest
report of a fact nobody recorded.

**Why the recorder is NOT called from `ToolExecutionLedger.execute_write`,
which is where the issue's prose points.** That method is synchronous by
construction — a `sqlalchemy.orm.Session` over psycopg2, called by
`ToolExecutor.execute` from inside an already-running event loop (see
`ledger.py`'s module docstring). `record_workflow_outcome` is `async def`
over an `AsyncSession`; bridging the two with `asyncio.run()` from inside
that loop raises on the spot ("cannot run event loop while another is
running" — #733, #741). So the seam is here instead: `WorkflowRunner`
(`core.py`) already awaits its collaborators, already knows the tool call
reached its terminal state, and already takes optional collaborators
(`cancel_check`, `concurrency_guard`) the task shell wires in. One more
optional collaborator is how an async recorder reaches a synchronous ledger's
terminal path without either of them changing shape.

**The session is a factory, not the runner's own.** `PersistingEventSink`'s
reasoning applies verbatim: an outcome row for a write that really happened
must survive whatever the run does next, including the crash handler's
`session.rollback()`. A fresh session per record, committed on its own, is
durable independently of the runner's transaction — and taking a FACTORY
rather than a session is what lets `agent_workflow._shop_scoped_session_factory`
hand it a session that already holds a sticky shop scope (#1883).
`workflow_outcome_records` is a direct `shop_id` tenant table (migration 045)
whose INSERT policy refuses a row written with no `app_current_shop_id()`, and
`record_workflow_outcome`'s idempotency read (`get_by_execution_id`) is itself
RLS-gated — run it unscoped and it returns nothing, the follow-on INSERT
fires, and `uq_workflow_outcome_records_shop_execution` raises a duplicate-key
error that is really a scope bug.

**Reuse by reference, never a second recorder.** `record_workflow_outcome` is
imported and called; its idempotency (read-then-insert, `is_duplicate=True` on
a hit), its metrics envelope and `extract_workflow_id`'s validation are
untouched, and the legacy caller stays exactly where it is. This adds a second
caller, it does not move the first.

**The accounting never kills the write.** `record_workflow_outcome` raises
`ValueError` when the execution payload carries no recognised `workflow_id` —
the case for every legacy row and for every agent row written before this
slice, since `ToolExecutionRequestPayload` had no such field and
`payload_json` defaults to `"{}"`. That is skipped and logged here, exactly as
`services/execution/worker.py` skips and logs it, never raised into a write
that already succeeded. Database failures are logged for the same reason: an
outcome record is accounting, and accounting that fails must not undo a
mutation TikTok has already applied.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.services.operations import record_workflow_outcome

logger = logging.getLogger(__name__)

#: What the caller hands in: something that opens a fresh `AsyncSession` per
#: record and closes it afterwards. `agent_workflow._shop_scoped_session_factory`
#: is the production one; it yields a session already holding a sticky shop
#: scope.
AsyncSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class WriteOutcomeRecorder(Protocol):
    """One `record`-shaped seam, structurally typed like `ToolExecutor` and
    `EventSink`, so `WorkflowRunner` and any implementation satisfy it
    independently with no shared base class.

    Implementations are **best effort by contract**: `record` never raises for
    a recording failure, because it is called from the terminal path of a write
    that has already happened.
    """

    async def record(
        self,
        *,
        workflow_run_id: uuid.UUID,
        tool_call_id: str,
        operation: str,
        execution_status: str,
        error_message: str | None = None,
    ) -> None: ...


class LedgerWriteOutcomeRecorder:
    """Resolves the `tool_executions` row the ledger just wrote for this
    `(workflow_run_id, tool_call_id, operation)` key and hands it to
    `record_workflow_outcome`.

    The lookup is the ledger's own unique key — the row is found by exactly the
    triple `ToolExecutionLedger._select` uses, narrowed additionally to this
    recorder's `shop_id` so a resolution can never cross a tenant even if RLS
    were somehow absent. No row means nothing to record: a WRITE that never
    reached the ledger (a concurrency conflict short-circuits
    `ProductToolExecutor.execute` before it, and a runner built without a
    ledger never routes through it at all) has no execution to join an outcome
    to.
    """

    def __init__(self, session_factory: AsyncSessionFactory, *, shop_id: uuid.UUID) -> None:
        self._session_factory = session_factory
        self._shop_id = shop_id

    async def record(
        self,
        *,
        workflow_run_id: uuid.UUID,
        tool_call_id: str,
        operation: str,
        execution_status: str,
        error_message: str | None = None,
    ) -> None:
        context = {
            "shop_id": str(self._shop_id),
            "workflow_run_id": str(workflow_run_id),
            "tool_call_id": tool_call_id,
            "operation": operation,
            "execution_status": execution_status,
        }
        try:
            async with self._session_factory() as session:
                execution = await self._resolve_execution(
                    session, workflow_run_id, tool_call_id, operation
                )
                if execution is None:
                    logger.info("workflow_outcome_skipped_no_execution", extra=context)
                    return
                result = await record_workflow_outcome(
                    session,
                    execution,
                    execution_status=execution_status,
                    error_message=error_message,
                )
                await session.commit()
        except ValueError as exc:
            # The payload carries no recognised `workflow_id` — the legacy row
            # and the pre-#1939 agent row. Skipped and logged exactly as
            # `services/execution/worker.py` skips it.
            logger.warning("workflow_outcome_skipped", extra={**context, "error": str(exc)})
            return
        except SQLAlchemyError:
            logger.exception("workflow_outcome_record_failed", extra=context)
            return

        if result.is_duplicate:
            logger.info(
                "workflow_outcome_already_recorded",
                extra={**context, "record_id": str(result.record_id)},
            )

    async def _resolve_execution(
        self,
        session: AsyncSession,
        workflow_run_id: uuid.UUID,
        tool_call_id: str,
        operation: str,
    ) -> ToolExecution | None:
        stmt = select(ToolExecution).where(
            ToolExecution.shop_id == self._shop_id,
            ToolExecution.workflow_run_id == workflow_run_id,
            ToolExecution.tool_call_id == tool_call_id,
            ToolExecution.operation == operation,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


__all__ = [
    "AsyncSessionFactory",
    "LedgerWriteOutcomeRecorder",
    "WriteOutcomeRecorder",
]
