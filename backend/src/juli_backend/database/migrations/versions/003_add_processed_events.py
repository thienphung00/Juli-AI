"""add processed_events idempotency table (#32)

Revision ID: 003
Revises: 002
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_processed_events_shop", "processed_events", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_processed_events_shop", table_name="processed_events")
    op.drop_table("processed_events")
