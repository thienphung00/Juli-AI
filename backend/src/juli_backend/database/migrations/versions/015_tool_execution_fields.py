"""add idempotency_key and error_category to tool_executions (#305 reopened)

Revision ID: 015_tool_execution_fields
Revises: 014_action_cards
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_tool_execution_fields"
down_revision: str | None = "014_action_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_executions",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tool_executions",
        sa.Column("error_category", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_executions", "error_category")
    op.drop_column("tool_executions", "idempotency_key")
