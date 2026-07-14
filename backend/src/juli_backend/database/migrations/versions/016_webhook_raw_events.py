"""add webhook_raw_events for TikTok webhook audit archive (#392)

Revision ID: 016_webhook_raw_events
Revises: 015_tool_execution_fields
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016_webhook_raw_events"
down_revision: str | None = "015_tool_execution_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_raw_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tiktok_shop_id", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("event_id", sa.String(length=255), nullable=True),
        sa.Column("signature_header", sa.Text(), nullable=True),
        sa.Column("headers", sa.Text(), nullable=True),
        sa.Column("raw_body", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column(
            "parse_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_raw_events_received_at",
        "webhook_raw_events",
        ["received_at"],
    )
    op.create_index(
        "ix_webhook_raw_events_tiktok_shop_id",
        "webhook_raw_events",
        ["tiktok_shop_id"],
    )
    op.create_index(
        "ix_webhook_raw_events_event_type",
        "webhook_raw_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_raw_events_event_type", "webhook_raw_events")
    op.drop_index("ix_webhook_raw_events_tiktok_shop_id", "webhook_raw_events")
    op.drop_index("ix_webhook_raw_events_received_at", "webhook_raw_events")
    op.drop_table("webhook_raw_events")
