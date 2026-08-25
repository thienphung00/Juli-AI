"""widen ck_workflow_runs_stop_reason to accept prompt_version_unrecoverable
(#1359, fail-closed resume guard when stored prompt version is missing or
unparseable).

Revision ID: 042_stop_reason_prompt_pin
Revises: 041_stop_reason_diverged
Create Date: 2026-08-25

``ck_workflow_runs_stop_reason``, created by migration
``034_workflow_runs_table`` and widened by ``041_stop_reason_diverged``,
currently accepts thirteen ``StopReason`` members. ``services/agent/status.py``
gains a fourteenth member, ``prompt_version_unrecoverable`` (#1359,
fail-closed resume on unrecoverable prompt pin), in a follow-on to #1224's
consent-binding work. Verified empirically against real Postgres:
``INSERT ... stop_reason='prompt_version_unrecoverable'`` raises
``CheckViolation`` against a database migrated only through ``041``. That
INSERT is the resume-side fail-closed safety mechanism honestly recording
*why* it refused to continue executing an unknown prompt -- so today the
correct refusal crashes instead of persisting.

This migration widens the constraint only. It does **not** touch
``services/agent/status.py`` (owned by #1359, in review as this lands) and
does **not** touch the ORM ``CheckConstraint`` mirror in ``models/models.py``
(also #1359's, per the issue) -- duplicating either here would collide at
merge. It touches no column, no other table, no other constraint.

A ``CHECK`` constraint cannot be altered in place -- Postgres has no
``ALTER CONSTRAINT`` for a check clause -- so this is
``DROP CONSTRAINT`` / ``ADD CONSTRAINT`` with the widened literal list,
the same shape the issue specifies. This is a pure widening: every value the
thirteen-member constraint already accepted is still accepted, so no existing
row can violate the new constraint and no data migration or backfill is
needed. ``downgrade()`` restores the original thirteen-value list.

Downgrade safety note: rows with ``stop_reason='prompt_version_unrecoverable'``
cannot exist in production at the time this migration is applied, because
the fail-closed code path that writes this value does not exist yet in the
deployed version. The constraint is added in the same commit that adds the
code that writes it. Downgrade is therefore safe for rollback to prior HEAD.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "042_stop_reason_prompt_pin"
down_revision: str | None = "041_stop_reason_diverged"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_STOP_REASONS_041 = (
    "final_response",
    "confirmation_declined",
    "paused_for_confirmation",
    "cancelled_by_seller",
    "confirmation_expired",
    "confirmation_diverged",
    "iteration_cap_exceeded",
    "wall_clock_timeout",
    "tool_error_unrecoverable",
    "llm_error",
    "concurrency_conflict",
    "output_validation_failed",
    "worker_lost",
)

_VALID_STOP_REASONS_042 = (*_VALID_STOP_REASONS_041, "prompt_version_unrecoverable")

_CONSTRAINT_NAME = "ck_workflow_runs_stop_reason"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_042)})",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_041)})",
    )
