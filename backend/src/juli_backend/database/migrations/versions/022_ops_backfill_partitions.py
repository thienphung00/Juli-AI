"""move analytics_backfill_partitions to ops schema (#604)

Revision ID: 022_ops_backfill_partitions
Revises: 021_medallion_schemas
Create Date: 2026-07-30

Moves public.analytics_backfill_partitions → ops.analytics_backfill_partitions
with data copy. ops schema and grant isolation were created in 021; this revision
only relocates the backfill partition table to its canonical ops home (ADR-046).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "022_ops_backfill_partitions"
down_revision: str | None = "021_medallion_schemas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_BUCKETS = ("revenue", "product", "live", "catalog")
_VALID_STATUSES = ("pending", "complete", "failed", "skipped")
POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")


def _revoke_client_table(table: str) -> None:
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $ops_backfill$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    REVOKE ALL ON TABLE {table} FROM {role};
  END IF;
END
$ops_backfill$;
"""  # nosec B608 — table/role are fixed module constants
        op.execute(sql)


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
        schema="ops",
    )
    op.create_index(
        "ix_analytics_backfill_partitions_shop_bucket_date",
        "analytics_backfill_partitions",
        ["shop_id", "bucket", "partition_date"],
        schema="ops",
    )

    op.execute(
        """
        INSERT INTO ops.analytics_backfill_partitions (
            id, shop_id, bucket, partition_date, status,
            attempt_count, last_error, retryable, updated_at
        )
        SELECT
            id, shop_id, bucket, partition_date, status,
            attempt_count, last_error, retryable, updated_at
        FROM public.analytics_backfill_partitions
        """
    )

    op.execute(
        "DROP POLICY IF EXISTS analytics_backfill_partitions_isolation "
        "ON public.analytics_backfill_partitions"
    )
    op.execute("ALTER TABLE public.analytics_backfill_partitions DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_analytics_backfill_partitions_shop_bucket_date",
        table_name="analytics_backfill_partitions",
    )
    op.drop_table("analytics_backfill_partitions")

    op.execute("""
        ALTER TABLE ops.analytics_backfill_partitions ENABLE ROW LEVEL SECURITY;
        CREATE POLICY analytics_backfill_partitions_isolation
            ON ops.analytics_backfill_partitions
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)  # nosec B608

    _revoke_client_table("ops.analytics_backfill_partitions")


def downgrade() -> None:
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

    op.execute(
        """
        INSERT INTO public.analytics_backfill_partitions (
            id, shop_id, bucket, partition_date, status,
            attempt_count, last_error, retryable, updated_at
        )
        SELECT
            id, shop_id, bucket, partition_date, status,
            attempt_count, last_error, retryable, updated_at
        FROM ops.analytics_backfill_partitions
        """
    )

    op.execute(
        "DROP POLICY IF EXISTS analytics_backfill_partitions_isolation "
        "ON ops.analytics_backfill_partitions"
    )
    op.execute("ALTER TABLE ops.analytics_backfill_partitions DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_analytics_backfill_partitions_shop_bucket_date",
        table_name="analytics_backfill_partitions",
        schema="ops",
    )
    op.drop_table("analytics_backfill_partitions", schema="ops")

    op.execute("""
        ALTER TABLE analytics_backfill_partitions ENABLE ROW LEVEL SECURITY;
        CREATE POLICY analytics_backfill_partitions_isolation
            ON analytics_backfill_partitions
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)  # nosec B608
