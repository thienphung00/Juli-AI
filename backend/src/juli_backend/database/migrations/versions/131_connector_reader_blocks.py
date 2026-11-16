"""The Connector's reader blocks on its state row (Connector 0.3.22)

Revision ID: 131_connector_reader_blocks
Revises: 130_businesses
Create Date: 2026-11-16

A login wall or CAPTCHA on one Seller Centre page now blocks that page only and the Connector's
run goes on. The run report (``POST /v1/ingest/connector-ticks``) names each blocked page; the
ticks route keeps the last daily run's blocks on ``shopee_connector_state`` so the seller's app
reads them through the tenant path (``ops_audit_log`` stays ops-only).

- ``reader_blocks`` -- nullable JSON (JSONB on Postgres): ``[{section, reason, readers}]`` of the
  last daily run, ``[]`` when it had none; NULL until a 0.3.22 run reports.
- ``reader_blocks_at`` -- nullable timestamp: when that run's report arrived.

EXPAND-ONLY AND REVERSIBLE: two nullable columns, no default, no row is moved. The table's RLS
policies and ``juli_app`` grants (128) already cover them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "131_connector_reader_blocks"
down_revision: str | None = "130_businesses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopee_connector_state",
        sa.Column(
            "reader_blocks",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "shopee_connector_state",
        sa.Column("reader_blocks_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shopee_connector_state", "reader_blocks_at")
    op.drop_column("shopee_connector_state", "reader_blocks")
