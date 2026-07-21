"""add analytics_performance_intervals for poll ETL (#425)

Revision ID: 017_analytics_performance_intervals
Revises: 016_webhook_raw_events
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017_analytics_performance_intervals"
down_revision: str | None = "016_webhook_raw_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_performance_intervals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_key", sa.String(300), nullable=False),
        sa.Column("grain", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("hour_index", sa.Integer(), nullable=True),
        sa.Column("tiktok_product_id", sa.String(100), nullable=True),
        sa.Column("tiktok_sku_id", sa.String(100), nullable=True),
        sa.Column("tiktok_live_id", sa.String(100), nullable=True),
        sa.Column("gmv", sa.Numeric(18, 2), nullable=True),
        sa.Column("gmv_currency", sa.String(10), nullable=True),
        sa.Column("ctr", sa.Numeric(10, 6), nullable=True),
        sa.Column("click_through_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("click_order_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("click_to_order_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("sku_orders", sa.Integer(), nullable=True),
        sa.Column("items_sold", sa.Integer(), nullable=True),
        sa.Column("orders_count", sa.Integer(), nullable=True),
        sa.Column("customers", sa.Integer(), nullable=True),
        sa.Column("visitors", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_perf_shop_snapshot",
        "analytics_performance_intervals",
        ["shop_id", "snapshot_key"],
        unique=True,
    )
    op.create_index(
        "ix_analytics_perf_shop_grain_date",
        "analytics_performance_intervals",
        ["shop_id", "grain", "start_date"],
    )

    op.execute("""
        ALTER TABLE analytics_performance_intervals ENABLE ROW LEVEL SECURITY;
        CREATE POLICY analytics_performance_intervals_isolation
            ON analytics_performance_intervals
            USING (shop_id IN (
                SELECT id FROM shops
                WHERE user_id = current_setting('app.current_user_id')::uuid
            ));
    """)  # nosec B608


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS analytics_performance_intervals_isolation "
        "ON analytics_performance_intervals"
    )
    op.execute("ALTER TABLE analytics_performance_intervals DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_analytics_perf_shop_grain_date",
        table_name="analytics_performance_intervals",
    )
    op.drop_index(
        "ix_analytics_perf_shop_snapshot",
        table_name="analytics_performance_intervals",
    )
    op.drop_table("analytics_performance_intervals")
