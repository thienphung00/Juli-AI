"""widen ck_workflow_runs_stop_reason to accept confirmation_diverged
(#1274, AGT-W5A-DP, blocking follow-on to #1224)

Revision ID: 041_stop_reason_diverged
Revises: 040_workflow_run_action_card
Create Date: 2026-08-21

``ck_workflow_runs_stop_reason``, created by migration
``034_workflow_runs_table``, enumerates the twelve ``StopReason`` members
that existed at the time. ``services/agent/status.py``'s ``StopReason``
gains a thirteenth member, ``confirmation_diverged`` (#1224, consent-binding
refusal on resume), on a sibling branch. Verified empirically against real
Postgres: ``INSERT ... stop_reason='confirmation_diverged'`` raises
``CheckViolation`` against a database migrated only through ``040``. That
INSERT is the resume-side consent check honestly recording *why* it refused
to write a change the seller never approved -- so today the correct refusal
crashes instead of persisting.

This migration widens the constraint only. It does **not** touch
``services/agent/status.py`` (owned by #1224, in review as this lands) and
does **not** touch the ORM ``CheckConstraint`` mirror in ``models/models.py``
(also #1224's, per the issue) -- duplicating either here would collide at
merge. It touches no column, no other table, no other constraint.

A ``CHECK`` constraint cannot be altered in place -- Postgres has no
``ALTER CONSTRAINT`` for a check clause -- so this is
``DROP CONSTRAINT`` / ``ADD CONSTRAINT`` with the widened literal list,
the same shape the issue specifies. This is a pure widening: every value the
twelve-member constraint already accepted is still accepted, so no existing
row can violate the new constraint and no data migration or backfill is
needed. ``downgrade()`` restores the original twelve-value list.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "041_stop_reason_diverged"
down_revision: str | None = "040_workflow_run_action_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_STOP_REASONS_034 = (
    "final_response",
    "confirmation_declined",
    "paused_for_confirmation",
    "cancelled_by_seller",
    "confirmation_expired",
    "iteration_cap_exceeded",
    "wall_clock_timeout",
    "tool_error_unrecoverable",
    "llm_error",
    "concurrency_conflict",
    "output_validation_failed",
    "worker_lost",
)

_VALID_STOP_REASONS_041 = (*_VALID_STOP_REASONS_034, "confirmation_diverged")

_CONSTRAINT_NAME = "ck_workflow_runs_stop_reason"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_041)})",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_034)})",
    )
