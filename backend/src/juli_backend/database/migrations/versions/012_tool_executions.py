"""add tool_executions for Celery-backed approved tool calls (#305)

Revision ID: 012_tool_executions
Revises: 011_workflow_webhook_signals
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_tool_executions"
down_revision: str | None = "011_workflow_webhook_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("outcome_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_executions_shop", "tool_executions", ["shop_id"])
    op.create_index(
        "ix_tool_executions_status",
        "tool_executions",
        ["shop_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_executions_status", table_name="tool_executions")
    op.drop_index("ix_tool_executions_shop", table_name="tool_executions")
    op.drop_table("tool_executions")
