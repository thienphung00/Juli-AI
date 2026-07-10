"""add merchant capability columns to tiktok_credentials (P2-A1 #296)

Revision ID: 008_merchant_capability
Revises: 007_order_items_returns
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_merchant_capability"
down_revision: str | None = "007_order_items_returns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tiktok_credentials",
        sa.Column("merchant_authorization_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column("capability", sa.String(50), nullable=True),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column("shop_cipher", sa.String(200), nullable=True),
    )
    op.create_index(
        "ix_tiktok_credentials_merchant_capability",
        "tiktok_credentials",
        ["merchant_authorization_id", "capability"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tiktok_credentials_merchant_capability",
        table_name="tiktok_credentials",
    )
    op.drop_column("tiktok_credentials", "shop_cipher")
    op.drop_column("tiktok_credentials", "capability")
    op.drop_column("tiktok_credentials", "merchant_authorization_id")
