"""add workflow_runs.required_steps_completed column (issue #1220)

Revision ID: 037_required_steps_completed
Revises: 036_cancel_requested_column
Create Date: 2026-08-20

Additive-only: a single nullable Boolean column, no server default and no
backfill pass, so every existing ``workflow_runs`` row reads NULL --
"not yet determined" -- rather than a guessed True/False for a run this
column never scored. No existing column anywhere is dropped, renamed,
narrowed, or made non-nullable.

**This is an outcome fact, not a termination signal (ADR-073 decision 2).**
``stop_reason`` records *how* a run's loop ended; this column records a
separate fact -- whether every operation named by the active `Playbook`'s
``TerminationPolicy.required_steps`` completed successfully during the run
-- feeding the execution-quality metric. A `final_response` (or any other
`stop_reason`) with `required_steps_completed = False` is honest outcome
data, never a synthetic failure; `stop_reason`/`status` are computed
exactly as before this migration, unchanged by this column's presence.

Written wherever a run's terminal `status`/`stop_reason` are already
written -- `WorkflowRunner` via
``services/agent/runner/conversation_store.py::JsonbConversationStore.persist``,
and the reaper via ``workers/tasks/reaper.py::_ReaperEventSink.emit`` --
never a second, independent write path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037_required_steps_completed"
down_revision: str | None = "036_cancel_requested_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "required_steps_completed",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "required_steps_completed")
