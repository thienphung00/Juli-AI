"""add livestream/creator/settlement fields for API #38

Adds:
- livestreams.peak_concurrent_viewers
- livestreams.click_count
- creators.total_gmv
- creators.commission_rate
- settlements.platform_commission
- settlements.affiliate_commission
- settlements.shipping_fee

Revision ID: 004
Revises: 003
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "livestreams",
        sa.Column("peak_concurrent_viewers", sa.Integer(), nullable=True),
    )
    op.add_column(
        "livestreams",
        sa.Column("click_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "creators",
        sa.Column(
            "total_gmv",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "creators",
        sa.Column(
            "commission_rate",
            sa.Numeric(10, 4),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "settlements",
        sa.Column(
            "platform_commission",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "settlements",
        sa.Column(
            "affiliate_commission",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "settlements",
        sa.Column(
            "shipping_fee",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("settlements", "shipping_fee")
    op.drop_column("settlements", "affiliate_commission")
    op.drop_column("settlements", "platform_commission")
    op.drop_column("creators", "commission_rate")
    op.drop_column("creators", "total_gmv")
    op.drop_column("livestreams", "click_count")
    op.drop_column("livestreams", "peak_concurrent_viewers")
