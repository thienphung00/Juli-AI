"""order items + returns tables (P2 revenue leakage)

Revision ID: 007_order_items_returns
Revises: 006_commerce_graph
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_order_items_returns"
down_revision: str | None = "006_commerce_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(100), nullable=False),
        sa.Column("tiktok_product_id", sa.String(100), nullable=True),
        sa.Column("tiktok_sku_id", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_shop_order", "order_items", ["shop_id", "order_id"])
    op.create_index(
        "ix_order_items_shop_order_sku",
        "order_items",
        ["shop_id", "tiktok_order_id", "tiktok_sku_id"],
        unique=True,
    )

    op.create_table(
        "returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("tiktok_return_id", sa.String(100), nullable=False),
        sa.Column("tiktok_order_id", sa.String(100), nullable=False),
        sa.Column("buyer_id", sa.String(100), nullable=True),
        sa.Column("tiktok_product_id", sa.String(100), nullable=True),
        sa.Column("tiktok_sku_id", sa.String(100), nullable=True),
        sa.Column("return_type", sa.String(30), nullable=False),
        sa.Column(
            "return_condition",
            sa.String(30),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("return_reason", sa.String(500), nullable=True),
        sa.Column("refund_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_returns_shop_created", "returns", ["shop_id", "created_at"])
    op.create_index(
        "ix_returns_shop_tiktok",
        "returns",
        ["shop_id", "tiktok_return_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_returns_shop_tiktok", table_name="returns")
    op.drop_index("ix_returns_shop_created", table_name="returns")
    op.drop_table("returns")
    op.drop_index("ix_order_items_shop_order_sku", table_name="order_items")
    op.drop_index("ix_order_items_shop_order", table_name="order_items")
    op.drop_table("order_items")
