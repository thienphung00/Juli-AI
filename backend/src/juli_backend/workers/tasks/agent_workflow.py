"""Celery task shells for agent workflow execution (#1129, ADR-074 decision 4).

Thin shells only (ADR-073 decision 1's rejected alternative is exactly "loop
inline in the Celery task"): **load context -> construct runner -> run**. No
loop or state-machine logic lives in this module — that lives in
``WorkflowRunner`` (`services/agent/runner/`, #1119 / W3-A).

At authoring time this worktree is stacked on #1117 -> #1125 only; #1119 has
not landed and ``services/agent/runner`` exports only the
``WorkflowRunStatus``/``StopReason`` vocabulary (`status.py`), not
``WorkflowRunner`` itself. ``_construct_runner`` below imports it lazily from
the exact module path it is pinned to land at
(``juli_backend.services.agent.runner``, interface I5/I6 per
``docs/handoffs/2026-08-12-agent-execution-implementation-handoff.md``) — once
#1119 merges and exports a ``WorkflowRunner`` matching ``_RunnerProtocol``
below, this file needs no other change; the import resolves and production
traffic starts flowing. Until then, ``_load_context``/``_construct_runner``
are the two seams tests monkeypatch with a fake runner shaped like
``_RunnerProtocol`` (I6's run-state-blob shape: everything the runner needs
comes back out of the reloaded ``workflow_runs`` row, nothing is cached
task-side between invocations).

Both tasks are ``acks_late=True, max_retries=1`` (ADR-074 decision 4): a
worker crash redelivers the task once, and the retried worker reconstructs
entirely from ``workflow_runs.state`` — at-least-once delivery is safe
because the idempotent event emit (ADR-074 decision 1) and the
``ToolExecution`` ledger (ADR-073 decision 1/I7) absorb the replay. Nothing in
this module deduplicates a retry itself; ``_load_context`` simply re-reads
the row fresh on every invocation, so a redelivered task naturally resumes
from wherever the row currently is instead of restarting from scratch.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import WorkflowRun
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url


class _RunnerProtocol(Protocol):
    """The narrow shape this module needs from a constructed runner.

    Placeholder for ``WorkflowRunner`` (#1119 / W3-A) — matches I6's
    run-state-blob contract closely enough to build against without
    inlining any loop logic here. P8-9's live gate (real ``WorkflowRunner``
    behind ``_construct_runner``) replaces this once W3-A merges; this
    Protocol itself is deleted at that point, not "graduated".
    """

    async def run(self) -> None: ...

    async def resume(self, tool_call_id: str, decision: str) -> None: ...


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _load_context(run_id: str) -> WorkflowRun:
    """Load the current ``workflow_runs`` row — the run-state blob (I6).

    Reads fresh on every call, including on a redelivered retry: there is no
    task-local cache of run state anywhere in this module, which is exactly
    what makes the retry-reconstructs-from-the-blob guarantee true rather
    than aspirational.
    """
    factory = _ensure_session_factory()
    async with factory() as session:
        run = await session.get(WorkflowRun, uuid.UUID(run_id))
        if run is None:
            raise LookupError(f"workflow_runs row not found for run_id={run_id}")
        return run


def _construct_runner(context: WorkflowRun) -> _RunnerProtocol:
    """Construct the runner for ``context`` — the one-line wiring point.

    ``WorkflowRunner`` does not exist on this stack yet (#1119 / W3-A
    unmerged at authoring time). This import is intentionally the real,
    pinned package (``juli_backend.services.agent.runner``, imported via its
    public ``services.agent`` root per ``.importlinter.toml``'s
    cross-package deep-import cap) rather than a permanent local fallback:
    once #1119 lands and exports ``WorkflowRunner``, this line resolves and
    no other change is needed here.
    """
    from juli_backend.services.agent import runner as runner_module

    return runner_module.WorkflowRunner(context)  # type: ignore[attr-defined]


async def _run_agent_workflow_async(run_id: str) -> None:
    context = await _load_context(run_id)
    runner = _construct_runner(context)
    await runner.run()


async def _resume_agent_workflow_async(run_id: str, tool_call_id: str, decision: str) -> None:
    context = await _load_context(run_id)
    runner = _construct_runner(context)
    await runner.resume(tool_call_id, decision)


def run_agent_workflow_sync(run_id: str) -> None:
    asyncio.run(_run_agent_workflow_async(run_id))


def resume_agent_workflow_sync(run_id: str, tool_call_id: str, decision: str) -> None:
    asyncio.run(_resume_agent_workflow_async(run_id, tool_call_id, decision))


@celery_app.task(name="juli_backend.run_agent_workflow", acks_late=True, max_retries=1)
def run_agent_workflow(run_id: str) -> None:
    """Run (or continue) an agent workflow run outside the HTTP request cycle."""
    run_agent_workflow_sync(run_id)


@celery_app.task(name="juli_backend.resume_agent_workflow", acks_late=True, max_retries=1)
def resume_agent_workflow(run_id: str, tool_call_id: str, decision: str) -> None:
    """Resume a ``waiting_approval`` run with an approval decision.

    Enqueued by the confirmation-authorization endpoint (P9 / #W4-A) — this
    task only carries the already-made ``decision`` through to the runner;
    it does not itself validate or authorize it.
    """
    resume_agent_workflow_sync(run_id, tool_call_id, decision)
