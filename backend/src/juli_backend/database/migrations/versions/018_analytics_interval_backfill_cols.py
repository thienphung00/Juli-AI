"""add live/catalog rollup columns to analytics_performance_intervals (#463)

Revision ID: 018_analytics_interval_backfill_cols
Revises: 017_analytics_perf_intervals
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_analytics_interval_backfill_cols"
down_revision: str | None = "017_analytics_perf_intervals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_performance_intervals",
        sa.Column("live_hours", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "analytics_performance_intervals",
        sa.Column("live_sessions", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_performance_intervals",
        sa.Column("active_products", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_performance_intervals",
        sa.Column("new_products", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analytics_performance_intervals", "new_products")
    op.drop_column("analytics_performance_intervals", "active_products")
    op.drop_column("analytics_performance_intervals", "live_sessions")
    op.drop_column("analytics_performance_intervals", "live_hours")
