"""Product-grain click and per-content-type breakdown columns.

Revision ID: 075_analytics_breakdown
Revises: 073_waiting_external
Create Date: 2026-10-05

Adds nullable ``clicks`` (derived: round(impressions * ctr)), ``traffic_breakdown``
(content_type -> impressions/ctr/clicks) and ``sales_breakdown`` (content_type ->
gmv/items_sold) to ``analytics_performance_intervals``. No backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "075_analytics_breakdown"
down_revision: str | None = "073_waiting_external"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "analytics_performance_intervals"


def upgrade() -> None:
    op.add_column(TABLE_NAME, sa.Column("clicks", sa.Integer(), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("traffic_breakdown", sa.JSON(), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("sales_breakdown", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE_NAME, "sales_breakdown")
    op.drop_column(TABLE_NAME, "traffic_breakdown")
    op.drop_column(TABLE_NAME, "clicks")
