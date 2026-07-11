"""add tiktok_sync_state for Fujiwa polling cursors (#298)

Revision ID: 009_tiktok_sync_state
Revises: 008_merchant_capability
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_tiktok_sync_state"
down_revision: str | None = "008_merchant_capability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiktok_sync_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(length=50), nullable=False),
        sa.Column("last_update_time", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tiktok_sync_state_shop_endpoint",
        "tiktok_sync_state",
        ["shop_id", "endpoint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tiktok_sync_state_shop_endpoint",
        table_name="tiktok_sync_state",
    )
    op.drop_table("tiktok_sync_state")
