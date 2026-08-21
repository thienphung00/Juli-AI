"""add workflow_runs.action_card_id (#1269, ADR-082 decision 6, AGT-W5A-DP)

Revision ID: 040_workflow_run_action_card
Revises: 039_run_confirmations
Create Date: 2026-08-21

Additive-only, persistence-only slice (AGT-W5A-DP): one new nullable column
on ``workflow_runs``, no existing column touched, no backfill.

ADR-075 decision 1 has always specified "INSERT the ``workflow_run`` (FK to
the card)", but #1214 -- W5's only other schema slice -- shipped no link in
either direction, and its acceptance criteria never named one. Without this
column an ``action_card_approvals`` row and the ``workflow_run`` it
authorized cannot be joined at all, and P10's five-link outcome chain
(recommendation -> action -> TikTok state change -> observed outcome ->
incremental impact) breaks in the middle.

``action_card_id`` is nullable with NO backfill: runs created before this
column existed have no card, and inventing one would be false data. FK to
``action_cards.id``, indexed for the join, same convention as
``ix_action_card_approvals_action_card`` (migration 039) and
``ix_demo_execution_records_action_card`` (migration 028).

This migration ships schema only. Nothing reads or writes this column yet --
#1222 (the approve-is-run-creation transaction) is the first writer, in a
later slice.

Reversible by ``DROP COLUMN`` (index first). Deployed through
``infra/scripts/safe-alembic-upgrade.sh``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "040_workflow_run_action_card"
down_revision: str | None = "039_run_confirmations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("action_card_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_workflow_runs_action_card_id",
        "workflow_runs",
        "action_cards",
        ["action_card_id"],
        ["id"],
    )
    op.create_index(
        "ix_workflow_runs_action_card",
        "workflow_runs",
        ["action_card_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_action_card", table_name="workflow_runs")
    op.drop_constraint("fk_workflow_runs_action_card_id", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "action_card_id")
