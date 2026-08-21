"""add run_confirmations and action_card_approvals tables (#1214, ADR-075
decisions 1-2, AGT-W5A-DP)

Revision ID: 039_run_confirmations
Revises: 038_credential_refresh_cols
Create Date: 2026-08-21

Additive-only, persistence-only slice (AGT-W5A-DP): two brand-new tables, no
existing table/column anywhere touched. Nothing in this slice reads or
writes either table yet -- the runner/route callers that will land in
later W5-A slices (#1221-#1225).

Numbering correction: the issue body (written before W4 landed) says this
migration is ``037_*`` on top of ``036_cancel_requested_column``. That is
stale -- W4 landed ``037_required_steps_completed`` and
``038_credential_refresh_cols`` after the issue was written, so this
migration is ``039_*``, chained onto ``038_credential_refresh_cols``. Item 3
of the issue (``workflow_runs.required_steps_completed``) already shipped in
``037_required_steps_completed`` (#1235, W4) and is NOT touched again here.

``run_confirmations`` (ADR-075 decision 2): the decision request a CONFIRM
pause writes -- one row per pause. ``options`` is JSONB: a list of
``{option_id, proposed_change, rationale, params_sha}``, where
``proposed_change`` is stored VERBATIM -- the audit is what was shown to the
seller, never a re-derivation from later state. ``status`` is a plain
check-constrained string (``pending`` | ``approved`` | ``declined`` |
``expired``) rather than a native DB enum -- the same "string + CHECK, not
``ALTER TYPE``" choice ``workflow_runs.status`` made in migration 034, so a
later vocabulary addition (there is none planned) stays an additive
migration. The partial unique index ``uq_run_confirmations_pending_run`` on
``(workflow_run_id)`` filtered to ``status = 'pending'`` is the structural
guard behind the confirmation-authorization ladder's "tool_call_id matches
THE pending confirmation" step (ADR-075 decision 2): a run can have any
number of terminal (approved/declined/expired) confirmation rows over its
lifetime, but never a second open one -- mirrors the
``uq_workflow_runs_active_shop_product`` partial-index precedent at
``034_workflow_runs_table.py:138``.

``action_card_approvals`` -- the approval audit record ADR-075 decision 1
calls for ("who, when, card snapshot"). Design choice, recorded here per the
executor brief: a NEW TABLE, not additive columns on ``action_cards``.
Reasons:

  1. ``ActionCard`` already carries ``approved_at``/``executed_at``/
     ``dismissed_at``/``surfaced_at`` from #716 (models.py:834-864) for the
     Decision emission-budget lifecycle. Those are seller-lifecycle state on
     the card itself, not an audit trail, and issue #1214 explicitly says
     they must not be repurposed.
  2. "Must survive the card later changing" (the deciding constraint) means
     the audit needs to freeze a snapshot independent of the live row it
     describes. A column added to ``action_cards`` IS the live row -- there
     is nothing for it to be a snapshot of; the card mutating in place would
     silently mutate its own "audit". A separate table with its own
     immutable ``card_snapshot`` JSONB column is a real, independent copy
     that a later change to ``action_cards`` cannot touch.
  3. ``action_cards`` has a ``uq_action_cards_shop_workflow`` unique
     constraint (one row per ``(shop_id, workflow_key)``), so columns on
     that table could only ever hold the *most recent* approval fact,
     silently overwriting any prior approval history. A separate table is
     append-only and keeps every approval event, which is what an audit
     record means.

``approved_by_user_id`` (FK ``users.id``, NOT NULL) is "who";
``approved_at`` (server-default ``now()``) is "when"; ``card_snapshot``
(JSONB, NOT NULL) is the card as shown, verbatim, at approval time --
mirrors ``run_confirmations.options[].proposed_change``'s "audit is what
was shown" discipline. ``action_card_id`` is indexed for the FK join, same
convention as ``ix_demo_execution_records_action_card``
(028_demo_execution_records.py).

Reversible by ``DROP TABLE`` (both tables, indexes first). Deployed through
``infra/scripts/safe-alembic-upgrade.sh``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "039_run_confirmations"
down_revision: str | None = "038_credential_refresh_cols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_RUN_CONFIRMATION_STATUSES = ("pending", "approved", "declined", "expired")


def upgrade() -> None:
    op.create_table(
        "run_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("selected_option_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _VALID_RUN_CONFIRMATION_STATUSES)})",
            name="ck_run_confirmations_status",
        ),
    )
    op.create_index(
        "ix_run_confirmations_workflow_run",
        "run_confirmations",
        ["workflow_run_id"],
    )
    op.create_index(
        "uq_run_confirmations_pending_run",
        "run_confirmations",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "action_card_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_card_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("card_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["action_card_id"], ["action_cards.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_card_approvals_action_card",
        "action_card_approvals",
        ["action_card_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_card_approvals_action_card", table_name="action_card_approvals")
    op.drop_table("action_card_approvals")

    op.drop_index("uq_run_confirmations_pending_run", table_name="run_confirmations")
    op.drop_index("ix_run_confirmations_workflow_run", table_name="run_confirmations")
    op.drop_table("run_confirmations")
