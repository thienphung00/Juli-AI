"""add analytics_backfill_partitions for resumable backfill (#464)

Revision ID: 019_analytics_backfill_partitions
Revises: 017_analytics_perf_intervals
Create Date: 2026-07-22

NOTE: When #463 (018_analytics_interval_cols) merges first, rebase down_revision
to 018 before merge so Alembic head stays linear.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019_analytics_backfill_partitions"
down_revision: str | None = "017_analytics_perf_intervals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_BUCKETS = ("revenue", "product", "live", "catalog")
_VALID_STATUSES = ("pending", "complete", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "analytics_backfill_partitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(20), nullable=False),
        sa.Column("partition_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "bucket",
            "partition_date",
            name="uq_analytics_backfill_partitions_shop_bucket_date",
        ),
        sa.CheckConstraint(
            f"bucket IN ({', '.join(repr(b) for b in _VALID_BUCKETS)})",
            name="ck_analytics_backfill_partitions_bucket",
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _VALID_STATUSES)})",
            name="ck_analytics_backfill_partitions_status",
        ),
    )
    op.create_index(
        "ix_analytics_backfill_partitions_shop_bucket_date",
        "analytics_backfill_partitions",
        ["shop_id", "bucket", "partition_date"],
    )

    op.execute("""
        ALTER TABLE analytics_backfill_partitions ENABLE ROW LEVEL SECURITY;
        CREATE POLICY analytics_backfill_partitions_isolation
            ON analytics_backfill_partitions
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)  # nosec B608


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS analytics_backfill_partitions_isolation "
        "ON analytics_backfill_partitions"
    )
    op.execute("ALTER TABLE analytics_backfill_partitions DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_analytics_backfill_partitions_shop_bucket_date",
        table_name="analytics_backfill_partitions",
    )
    op.drop_table("analytics_backfill_partitions")
