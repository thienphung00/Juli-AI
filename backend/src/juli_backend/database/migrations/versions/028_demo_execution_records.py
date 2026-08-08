"""Demo dry-run execution records — local/demo only (#717, B-5, ADR-037/038 §9)

Revision ID: 028_demo_execution_records
Revises: 027_decision_emission_budget
Create Date: 2026-08-08

Additive/expand-only, same discipline as 026/027:

- A brand-new table, ``demo_execution_records``, is the entire durability
  boundary for the public Mock Demo approve -> execute dry-run path (#717,
  B-5). It is a standalone table rather than added columns/rows on
  ``tool_executions`` (``ToolExecution``, migration 015): ``tool_executions``
  rows are Celery-dispatched and mean "this really called a TikTok write
  endpoint" via ``services.execution.dispatch.enqueue_approved_tool`` — a
  dry-run row must never be able to be picked up by that Celery/Partner-write
  path, and must never be interleaved with rows a reconciliation job scans
  expecting a real outcome. See ``services/demo_execution/MODULE.md`` for the
  full "why a new table" write-up.
- Because the table is new, its NOT NULL columns constrain no pre-existing
  row (same precedent as 024/025's new gold/silver tables and 027's
  ``decision_emission_novelty_ledger``) and the migration stays additive. No
  existing table (``action_cards``, ``tool_executions``, or otherwise) is
  altered, and no column is dropped, renamed, narrowed, or made NOT NULL.
- Two indexes support the module's own read patterns: a (shop_id, status)
  index for "how many/which dry-runs are currently running for this shop"
  and a (shop_id, action_card_id) index for "what is the latest dry-run
  execution for this Decision" — mirroring ``ix_tool_executions_status`` and
  ``ix_action_cards_shop`` respectively.

The currently-deployed release keeps reading/writing every existing table
completely unchanged while this migration is applied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "028_demo_execution_records"
down_revision: str | None = "027_decision_emission_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_execution_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("action_card_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("narrative_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["action_card_id"], ["action_cards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_demo_execution_records_shop",
        "demo_execution_records",
        ["shop_id"],
    )
    op.create_index(
        "ix_demo_execution_records_shop_status",
        "demo_execution_records",
        ["shop_id", "status"],
    )
    op.create_index(
        "ix_demo_execution_records_action_card",
        "demo_execution_records",
        ["shop_id", "action_card_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_demo_execution_records_action_card",
        table_name="demo_execution_records",
    )
    op.drop_index(
        "ix_demo_execution_records_shop_status",
        table_name="demo_execution_records",
    )
    op.drop_index(
        "ix_demo_execution_records_shop",
        table_name="demo_execution_records",
    )
    op.drop_table("demo_execution_records")
