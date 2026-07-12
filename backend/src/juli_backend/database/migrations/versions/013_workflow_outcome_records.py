"""add workflow_outcome_records for P2-B5 outcome tracking (#306)

Revision ID: 013_workflow_outcome_records
Revises: 012_tool_executions
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_workflow_outcome_records"
down_revision: str | None = "012_tool_executions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_outcome_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("execution_status", sa.String(length=20), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["tool_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "execution_id",
            name="uq_workflow_outcome_records_shop_execution",
        ),
    )
    op.create_index(
        "ix_workflow_outcome_records_shop",
        "workflow_outcome_records",
        ["shop_id"],
    )
    op.create_index(
        "ix_workflow_outcome_records_approval",
        "workflow_outcome_records",
        ["shop_id", "approval_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_outcome_records_approval",
        table_name="workflow_outcome_records",
    )
    op.drop_index(
        "ix_workflow_outcome_records_shop",
        table_name="workflow_outcome_records",
    )
    op.drop_table("workflow_outcome_records")
