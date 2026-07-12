"""add workflow_webhook_signals for Phase 2 catalog (#354)

Revision ID: 011_workflow_webhook_signals
Revises: 010_canonical_product_fields
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_workflow_webhook_signals"
down_revision: str | None = "010_canonical_product_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_webhook_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_shop_id", sa.String(length=100), nullable=False),
        sa.Column("catalog_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("workflow_keys", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_workflow_webhook_signals_shop",
        "workflow_webhook_signals",
        ["shop_id"],
    )
    op.create_index(
        "ix_workflow_webhook_signals_catalog",
        "workflow_webhook_signals",
        ["catalog_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_webhook_signals_catalog", "workflow_webhook_signals")
    op.drop_index("ix_workflow_webhook_signals_shop", "workflow_webhook_signals")
    op.drop_table("workflow_webhook_signals")
