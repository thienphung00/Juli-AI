"""add analytics_kpi_envelopes for Demo Analytics precompute SoT (#525)

Revision ID: 020_analytics_kpi_envelopes
Revises: 019_backfill_partitions
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "020_analytics_kpi_envelopes"
down_revision: str | None = "019_backfill_partitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_kpi_envelopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("envelope_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "kind",
            name="uq_analytics_kpi_envelopes_shop_kind",
        ),
    )

    op.execute("""
        ALTER TABLE analytics_kpi_envelopes ENABLE ROW LEVEL SECURITY;
        CREATE POLICY analytics_kpi_envelopes_isolation
            ON analytics_kpi_envelopes
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)  # nosec B608


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS analytics_kpi_envelopes_isolation ON analytics_kpi_envelopes")
    op.execute("ALTER TABLE analytics_kpi_envelopes DISABLE ROW LEVEL SECURITY")
    op.drop_table("analytics_kpi_envelopes")
