"""`ConversationStore` — the P-CS deferral seam (ADR-073 decision 5, issue
#1118 / AGT-W3A).

`ConversationStore` is the constructor-injected collaborator
`WorkflowRunner` (a later slice, #1119) will use to load/persist
`RunState` (`state.py`, alongside this module). This module ships the
protocol plus its one implementation for now: a JSONB-blob-backed store
that round-trips `RunState` through `workflow_runs.state` (the column
#1117 added).

A full P-CS phase (Redis and/or Postgres chat storage) later swaps the
*implementation* behind this protocol — the protocol itself, and whatever
depends on it, does not change (ADR-073 decision 5: "full Redis/Postgres
chat storage later swaps the implementation, not the runner"). Nothing in
the protocol below assumes a blob, a JSONB column, or SQL at all.

No `WorkflowRunner` here — that's #1119.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import WorkflowRun
from juli_backend.services.agent.runner.state import RunState


@runtime_checkable
class ConversationStore(Protocol):
    """Load/persist a `RunState` for a given `workflow_runs` row.

    Deliberately two methods and nothing else — the minimal surface
    `WorkflowRunner` needs. Keeping the protocol this narrow is what makes
    the P-CS seam real: an implementation only has to satisfy `load` and
    `persist`, so a later chat-store implementation is a straightforward
    swap, not a refactor of every caller.
    """

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        """Return the `RunState` currently persisted for this run."""
        ...

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState) -> None:
        """Persist `state` as this run's current `RunState`."""
        ...


class JsonbConversationStore:
    """`ConversationStore` backed by the `workflow_runs.state` JSONB blob
    (ADR-073 decision 5's stand-in implementation; ADR-073 decision 5:
    "the `workflow_runs.state` blob behind the `ConversationStore`
    protocol is the stand-in; no Redis chat storage, no
    conversations/messages tables").

    Constructor-injected `AsyncSession`, matching the shape of the
    repositories in `juli_backend.repositories.repos` (this module is not
    a repository itself — out of scope for this slice — but follows the
    same collaborator shape so a later promotion is a move, not a
    rewrite).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        run = await self._session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise NotFound(f"WorkflowRun {workflow_run_id} not found")
        return RunState.from_dict(run.state)

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState) -> None:
        run = await self._session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise NotFound(f"WorkflowRun {workflow_run_id} not found")
        run.state = state.to_dict()
        await self._session.flush()
