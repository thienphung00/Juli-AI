"""widen ck_workflow_runs_stop_reason to accept concluded_without_changes and
required_steps_unfulfilled (#1373, ADR-088 consent pause guarantee).

Revision ID: 043_stop_reason_consent_pause
Revises: 042_stop_reason_prompt_pin
Create Date: 2026-08-26

``ck_workflow_runs_stop_reason``, created by migration
``034_workflow_runs_table`` and widened by ``041_stop_reason_diverged``
and ``042_stop_reason_prompt_pin``, currently accepts fourteen ``StopReason``
members. ``services/agent/status.py`` gains two additional members
(#1373, ADR-088 consent pause guarantee): ``concluded_without_changes``
(the honest negative when the model explicitly calls the terminal tool
to end a run without proposing changes) and ``required_steps_unfulfilled``
(forced retry spent, still no call made). Verified empirically against
real Postgres: ``INSERT ... stop_reason='concluded_without_changes'``
raises ``CheckViolation`` against a database migrated only through ``042``.

This migration widens the constraint only. It does **not** touch
``services/agent/status.py`` (owned by #1373, already merged) and
does **not** touch the ORM ``CheckConstraint`` mirror in ``models/models.py``
(also #1373's, per the issue) -- duplicating either here would collide at
merge. It touches no column, no other table, no other constraint.

A ``CHECK`` constraint cannot be altered in place -- Postgres has no
``ALTER CONSTRAINT`` for a check clause -- so this is
``DROP CONSTRAINT`` / ``ADD CONSTRAINT`` with the widened literal list,
the same shape the issue specifies. This is a pure widening: every value
the fourteen-member constraint already accepted is still accepted, so no
existing row can violate the new constraint and no data migration or
backfill is needed. ``downgrade()`` restores the original fourteen-value
list.

Upgrade safety: rows with ``stop_reason='concluded_without_changes'`` or
``'required_steps_unfulfilled'`` cannot exist when this migration is
applied, because the code paths that write these values ship in the same
commit as the constraint.

Downgrade safety: a downgrade runs *after* the new code has been live,
so rows may by then carry these values. When any do, ``create_check_constraint``
in ``downgrade()`` fails loudly on the existing data rather than corrupting
it -- which is the correct behaviour.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "043_stop_reason_consent_pause"
down_revision: str | None = "042_stop_reason_prompt_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_STOP_REASONS_042 = (
    "final_response",
    "confirmation_declined",
    "paused_for_confirmation",
    "cancelled_by_seller",
    "confirmation_expired",
    "confirmation_diverged",
    "prompt_version_unrecoverable",
    "iteration_cap_exceeded",
    "wall_clock_timeout",
    "tool_error_unrecoverable",
    "llm_error",
    "concurrency_conflict",
    "output_validation_failed",
    "worker_lost",
)

_VALID_STOP_REASONS_043 = (
    *_VALID_STOP_REASONS_042,
    "concluded_without_changes",
    "required_steps_unfulfilled",
)

_CONSTRAINT_NAME = "ck_workflow_runs_stop_reason"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_043)})",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "workflow_runs", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "workflow_runs",
        "stop_reason IS NULL OR stop_reason IN ("
        f"{', '.join(repr(r) for r in _VALID_STOP_REASONS_042)})",
    )
