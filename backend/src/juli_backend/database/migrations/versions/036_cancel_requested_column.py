"""add workflow_runs.cancel_requested column (#1160, split from #1145)

Revision ID: 036_cancel_requested_column
Revises: 035_workflow_run_events_table
Create Date: 2026-08-17

Additive-only: a single nullable-false boolean column with a server default,
so existing ``workflow_runs`` rows backfill in place with no separate
``UPDATE`` pass. No existing column anywhere is dropped, renamed, narrowed,
or made nullable.

``WorkflowRunner`` already carries the checkpoint-cancellation seam --
``cancel_check: Callable[[], bool]`` polled at every checkpoint and fed to
``evaluate_checkpoint(cancel_requested=...)`` in
``services/agent/runner/termination.py``, which yields
``stop_reason=cancelled_by_seller`` -- but no column ever recorded that a
seller asked to cancel, so the seam could only ever read ``False``. This
migration adds the storage only; nothing in this slice reads or writes it.
#1145 wires the ``POST /v1/demo/runs/{run_id}/cancel`` route and the
runner's ``cancel_check`` to this column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036_cancel_requested_column"
down_revision: str | None = "035_workflow_run_events_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "cancel_requested")
