"""`ToolExecutionLedger` — the idempotent mutation-execution boundary
(ADR-073 decision 3, issue #1121 / AGT-W3A).

`ToolExecution` (`models/models.py`) was promoted from an audit-only row to
an idempotency ledger by #1117: it now carries `workflow_run_id`,
`tool_call_id`, `operation`, and a unique constraint over the three. This
module is the SELECT -> {replay | verify-then-decide | claim-and-execute}
machinery keyed by that triple, wired into `ToolExecutor`
(`tool_executor.py`) for WRITE-classified tool calls only — `READ` calls
never construct or call this class at all, which is how "reads skip the
ledger entirely" is satisfied: the skip lives in the caller, not here.

**The three-state machine (ADR-073 decision 3).** A key with no row is a
fresh dispatch: INSERT `in_flight` (durably committed before the vendor call
— a crash between INSERT and UPDATE must find the row on the next attempt)
-> call the vendor -> UPDATE to `succeeded` (with the sanitized result) or
`failed`. A `succeeded` row replays its stored result with **zero** vendor
calls — the retried conversation replays byte-identically. An `in_flight` OR
`failed` row (both are "we don't actually know if the vendor mutation
landed" states — a crash can happen on either side of the vendor call, and a
worker can be redelivered mid-call) go through **verify-then-decide**: the
caller-supplied `verify_applied` read-back callable reports `APPLIED` (mark
`succeeded` retroactively, no re-execution), `NOT_APPLIED` (re-execute
exactly once), or the check itself is inconclusive — errors, times out, or
returns `UNVERIFIABLE` — in which case this module **fails closed**
(`ToolExecutionUnrecoverableError`) rather than ever guessing. This is
ADR-073 decision 3's single most important behaviour: "never a
maybe-duplicate write."

**Why `failed` gets the same verify-then-decide treatment as `in_flight`,
not a blind re-execute.** ADR-073's prose names `in_flight` explicitly;
`failed` is this module's own extension of the same reasoning, not settled
by the issue text — flagged here as a judgment call. A `failed` row means a
prior attempt's `perform()` raised, but that says nothing about whether the
vendor mutation itself landed before the exception was raised (a timeout
after the write committed on TikTok's side but before the response reached
this process is exactly the ambiguous case ADR-073 is written for) — so a
`failed` row is exactly as untrustworthy as an `in_flight` one and gets the
identical read-back treatment.

**Why this module's DB access is a synchronous `sqlalchemy.orm.Session`,
not the `AsyncSession` the rest of this codebase uses
(`database/database.py`).** `ToolExecutor.execute` (`tool_executor.py`,
#1119) is a plain, unawaited method — `WorkflowRunner._dispatch_tool_call`
(`core.py`) calls it synchronously from inside an already-running event
loop, exactly the way it already calls the synchronous vendor SDK
(`resources.products.edit`, etc.). Making this module's DB access async
would require either awaiting `ToolExecutor.execute` (a `core.py` change
out of this issue's bounds) or bridging with `asyncio.run()` from inside a
coroutine already running on that same loop, which raises immediately
("cannot run event loop while another is running"). A synchronous session
over `psycopg2` (already a pinned dependency — `backend/pyproject.toml`,
otherwise reserved for Alembic per `core/config/runtime.py`'s
`sync_database_url`) matches `ToolExecutor`'s existing synchronous contract
instead. This is a deliberate, scoped exception for this one seam, not a
precedent for the request/worker async surfaces elsewhere — see
`workers/tasks/database.py` for why *those* surfaces must stay async
(#741: sync psycopg2 crashes inside `asyncio.run()`-per-task worker code,
a different hazard than the one here).
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from juli_backend.models.models import ToolExecution


class LedgerStatus(str, enum.Enum):
    """ADR-073 decision 3's ledger vocabulary: `in_flight -> succeeded |
    failed`. String-compatible with, but deliberately distinct from,
    `services.execution.types.ExecutionStatus`'s queued/running/succeeded/
    failed vocabulary for this same table's legacy Celery-approval rows
    (`ToolExecution`'s docstring) — the two never collide because they are
    selected by whether a row carries the ledger key columns at all, never
    by a shared status value.
    """

    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VerifyOutcome(str, enum.Enum):
    """What a caller-supplied read-back check concluded about an
    `in_flight`/`failed` row found on retry (ADR-073 decision 3,
    "verify-then-decide")."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class VerifyReadBack:
    """The result a `verify_applied` callable reports back to
    `ToolExecutionLedger.execute_write`.

    `result` is only meaningful when `outcome` is `APPLIED`: the
    caller-reconstructed sanitized-shape result equivalent to what the
    original vendor call would have returned, so a *third* retry of the
    same key — landing on the now-`succeeded` row — has a real stored
    result to replay byte-identically instead of an empty stand-in. Left
    `None` for `NOT_APPLIED`/`UNVERIFIABLE`, where no such result exists.
    """

    outcome: VerifyOutcome
    result: Mapping[str, Any] | None = None


class ToolExecutionUnrecoverableError(RuntimeError):
    """Fail-closed signal (ADR-073 decision 3: "never a maybe-duplicate
    write"): an `in_flight`/`failed` ledger row could not be resolved by
    read-back — the check itself errored, timed out, or reported
    `UNVERIFIABLE`. `execute_write` raises this instead of ever guessing;
    the row is left `failed` so a later retry re-attempts verify-then-decide
    rather than silently treating the ambiguity as success.
    """

    def __init__(self, *, workflow_run_id: uuid.UUID, tool_call_id: str, operation: str) -> None:
        self.workflow_run_id = workflow_run_id
        self.tool_call_id = tool_call_id
        self.operation = operation
        super().__init__(
            f"Cannot verify the prior attempt for (workflow_run_id={workflow_run_id!s}, "
            f"tool_call_id={tool_call_id!r}, operation={operation!r}) by read-back — "
            "failing closed rather than risking a duplicate write (ADR-073 decision 3)."
        )


class ToolExecutionLedger:
    """The ADR-073 decision-3 idempotency boundary `ToolExecutor` routes
    WRITE-classified tool calls through.

    Constructed once per run (or per request — it is cheap and stateless
    beyond the injected `Session`) with the `shop_id` the ledger rows belong
    to. `session` is a plain synchronous `sqlalchemy.orm.Session` — see the
    module docstring for why. Every method that touches the database is a
    small, individually overridable bound method (`_select`,
    `_insert_in_flight`, `_mark_succeeded`, `_mark_succeeded_retroactive`,
    `_mark_failed`) precisely so a test can spy on the ordering of "the
    ledger's DB access boundary" without reaching into SQLAlchemy internals.
    """

    def __init__(
        self,
        session: Session,
        *,
        shop_id: uuid.UUID,
        approval_id_prefix: str = "agent-ledger",
    ) -> None:
        self._session = session
        self._shop_id = shop_id
        self._approval_id_prefix = approval_id_prefix

    def execute_write(
        self,
        *,
        workflow_run_id: uuid.UUID,
        tool_call_id: str,
        operation: str,
        perform: Callable[[], Mapping[str, Any]],
        verify_applied: Callable[[], VerifyReadBack] | None = None,
    ) -> Mapping[str, Any]:
        """Resolve one WRITE tool call through the ledger.

        `_select` is unconditionally this call's first DB access, strictly
        before `perform` (the vendor call) ever runs, on every branch below
        — including the fresh-dispatch branch, where `_insert_in_flight`
        follows the SELECT and is itself strictly before `perform`, with
        `_mark_succeeded`/`_mark_failed` strictly after.
        """
        row = self._select(workflow_run_id, tool_call_id, operation)

        if row is not None:
            return self._resolve_existing(row, perform=perform, verify_applied=verify_applied)

        return self._claim_and_execute(
            workflow_run_id=workflow_run_id,
            tool_call_id=tool_call_id,
            operation=operation,
            perform=perform,
            verify_applied=verify_applied,
        )

    # --- DB-access boundary (individually spy-able) -------------------------

    def _select(
        self, workflow_run_id: uuid.UUID, tool_call_id: str, operation: str
    ) -> ToolExecution | None:
        stmt = select(ToolExecution).where(
            ToolExecution.workflow_run_id == workflow_run_id,
            ToolExecution.tool_call_id == tool_call_id,
            ToolExecution.operation == operation,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def _insert_in_flight(
        self, workflow_run_id: uuid.UUID, tool_call_id: str, operation: str
    ) -> ToolExecution:
        """INSERT the claim row and commit it durably before the vendor call
        runs — a crash between here and `_mark_succeeded`/`_mark_failed`
        must leave a row the next attempt's `_select` finds, never nothing.

        Raises `sqlalchemy.exc.IntegrityError` on the unique-constraint
        violation (ADR-073 decision 3: "a concurrent duplicate loses on the
        unique index") when another attempt claimed this exact key first —
        the caller (`_claim_and_execute`) is what handles that, never this
        method.
        """
        row = ToolExecution(
            shop_id=self._shop_id,
            approval_id=f"{self._approval_id_prefix}:{tool_call_id}"[:255],
            tool_name=operation,
            status=LedgerStatus.IN_FLIGHT.value,
            workflow_run_id=workflow_run_id,
            tool_call_id=tool_call_id,
            operation=operation,
        )
        self._session.add(row)
        self._session.flush()
        self._session.commit()
        return row

    def _mark_succeeded(
        self, row: ToolExecution, *, result: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        row.status = LedgerStatus.SUCCEEDED.value
        row.outcome_json = json.dumps(dict(result))
        row.error_message = None
        self._session.flush()
        self._session.commit()
        return result

    def _mark_succeeded_retroactive(
        self, row: ToolExecution, *, result: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        stored: Mapping[str, Any] = dict(result) if result is not None else {}
        row.status = LedgerStatus.SUCCEEDED.value
        row.outcome_json = json.dumps(dict(stored))
        row.error_message = None
        self._session.flush()
        self._session.commit()
        return stored

    def _mark_failed(self, row: ToolExecution, *, error_message: str) -> None:
        row.status = LedgerStatus.FAILED.value
        row.error_message = error_message[:2000]
        self._session.flush()
        self._session.commit()

    # --- orchestration --------------------------------------------------

    def _resolve_existing(
        self,
        row: ToolExecution,
        *,
        perform: Callable[[], Mapping[str, Any]],
        verify_applied: Callable[[], VerifyReadBack] | None,
    ) -> Mapping[str, Any]:
        if row.status == LedgerStatus.SUCCEEDED.value:
            # Stored sanitized result, byte-identical, zero vendor calls.
            return json.loads(row.outcome_json) if row.outcome_json else {}

        # in_flight or failed: both ambiguous-outcome states (module
        # docstring) — verify-then-decide governs both identically.
        read_back = self._safe_verify(verify_applied)

        if read_back.outcome is VerifyOutcome.APPLIED:
            return self._mark_succeeded_retroactive(row, result=read_back.result)

        if read_back.outcome is VerifyOutcome.NOT_APPLIED:
            return self._perform_and_finalize(row, perform=perform)

        # UNVERIFIABLE — fail closed, never a maybe-duplicate write.
        self._mark_failed(row, error_message="in_flight/failed read-back unverifiable")
        raise ToolExecutionUnrecoverableError(
            workflow_run_id=row.workflow_run_id,
            tool_call_id=row.tool_call_id,
            operation=row.operation,
        )

    def _claim_and_execute(
        self,
        *,
        workflow_run_id: uuid.UUID,
        tool_call_id: str,
        operation: str,
        perform: Callable[[], Mapping[str, Any]],
        verify_applied: Callable[[], VerifyReadBack] | None,
    ) -> Mapping[str, Any]:
        try:
            row = self._insert_in_flight(workflow_run_id, tool_call_id, operation)
        except IntegrityError:
            # Lost the unique-index race (ADR-073 decision 3): never fall
            # through to a second vendor call — resolve through the
            # winner's row exactly like any other retry that finds a row.
            self._session.rollback()
            winner = self._select(workflow_run_id, tool_call_id, operation)
            if winner is None:  # pragma: no cover - defensive, should be unreachable
                raise
            return self._resolve_existing(winner, perform=perform, verify_applied=verify_applied)

        return self._perform_and_finalize(row, perform=perform)

    def _perform_and_finalize(
        self, row: ToolExecution, *, perform: Callable[[], Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        try:
            result = perform()
        except Exception as exc:
            self._mark_failed(row, error_message=str(exc))
            raise
        return self._mark_succeeded(row, result=result)

    @staticmethod
    def _safe_verify(verify_applied: Callable[[], VerifyReadBack] | None) -> VerifyReadBack:
        """Never let a broken/timing-out read-back check escape as an
        exception — an errored check is exactly as ambiguous as one that
        explicitly reports `UNVERIFIABLE`, per ADR-073 decision 3."""
        if verify_applied is None:
            return VerifyReadBack(outcome=VerifyOutcome.UNVERIFIABLE)
        try:
            outcome = verify_applied()
        except Exception:
            return VerifyReadBack(outcome=VerifyOutcome.UNVERIFIABLE)
        if not isinstance(outcome, VerifyReadBack):  # pragma: no cover - defensive
            return VerifyReadBack(outcome=VerifyOutcome.UNVERIFIABLE)
        return outcome


__all__ = [
    "LedgerStatus",
    "ToolExecutionLedger",
    "ToolExecutionUnrecoverableError",
    "VerifyOutcome",
    "VerifyReadBack",
]
