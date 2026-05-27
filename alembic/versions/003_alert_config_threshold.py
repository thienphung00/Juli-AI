"""Add per-shop alert thresholds on alert_configs."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_alert_config_threshold"
down_revision: str | None = "002_add_commerce_analytics_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert_configs",
        sa.Column("threshold_json", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_alert_configs_shop_type",
        "alert_configs",
        ["shop_id", "alert_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_alert_configs_shop_type", table_name="alert_configs")
    op.drop_column("alert_configs", "threshold_json")
