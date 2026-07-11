"""add canonical ETL fields for product and order normalization (#299)

Revision ID: 010_canonical_product_fields
Revises: 009_tiktok_sync_state
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_canonical_product_fields"
down_revision: str | None = "009_tiktok_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("order_value", sa.Numeric(18, 2), nullable=True))
    op.add_column("orders", sa.Column("payment_time", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("ship_time", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("delivery_time", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("tiktok_created_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("cancel_reason", sa.String(length=500), nullable=True))
    op.add_column("orders", sa.Column("is_seller_fault", sa.Boolean(), nullable=True))

    op.add_column("products", sa.Column("title", sa.String(length=500), nullable=True))
    op.add_column("products", sa.Column("category", sa.String(length=200), nullable=True))
    op.add_column("products", sa.Column("category_id", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("price", sa.Numeric(18, 2), nullable=True))
    op.add_column("products", sa.Column("price_currency", sa.String(length=10), nullable=True))
    op.add_column("products", sa.Column("inventory", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("audit_status", sa.String(length=30), nullable=True))
    op.add_column("products", sa.Column("tiktok_created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "tiktok_created_at")
    op.drop_column("products", "audit_status")
    op.drop_column("products", "inventory")
    op.drop_column("products", "price_currency")
    op.drop_column("products", "price")
    op.drop_column("products", "category_id")
    op.drop_column("products", "category")
    op.drop_column("products", "title")
    op.drop_column("orders", "is_seller_fault")
    op.drop_column("orders", "cancel_reason")
    op.drop_column("orders", "tiktok_created_at")
    op.drop_column("orders", "delivery_time")
    op.drop_column("orders", "ship_time")
    op.drop_column("orders", "payment_time")
    op.drop_column("orders", "order_value")
