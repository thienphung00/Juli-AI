"""add action_cards for manual-refresh pipeline persistence (#303, ADR-021)

Revision ID: 014_action_cards
Revises: 013_workflow_outcome_records
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_action_cards"
down_revision: str | None = "013_workflow_outcome_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation_payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "shop_id",
            "workflow_key",
            name="uq_action_cards_shop_workflow",
        ),
    )
    op.create_index("ix_action_cards_shop", "action_cards", ["shop_id"])
    op.create_index(
        "ix_action_cards_shop_status",
        "action_cards",
        ["shop_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_cards_shop_status", table_name="action_cards")
    op.drop_index("ix_action_cards_shop", table_name="action_cards")
    op.drop_table("action_cards")
