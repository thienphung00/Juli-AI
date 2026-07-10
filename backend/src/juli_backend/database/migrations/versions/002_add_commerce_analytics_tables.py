"""add commerce + analytics tables (#28)

Revision ID: 002
Revises: 001
Create Date: 2026-05-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Commerce tables ---

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("buyer_id", sa.String(100), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_shop_created", "orders", ["shop_id", "created_at"])
    op.create_index("ix_orders_shop_tiktok", "orders", ["shop_id", "tiktok_order_id"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_shop_created", "products", ["shop_id", "created_at"])
    op.create_index("ix_products_shop_tiktok", "products", ["shop_id", "tiktok_product_id"], unique=True)

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(100), nullable=False),
        sa.Column("tiktok_sku_id", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.String(100), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_shop_created", "inventory_items", ["shop_id", "created_at"])
    op.create_index("ix_inventory_shop_sku", "inventory_items", ["shop_id", "tiktok_sku_id"], unique=True)

    op.create_table(
        "settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_settlement_id", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("settlement_time", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_settlements_shop_created", "settlements", ["shop_id", "created_at"])
    op.create_index("ix_settlements_shop_tiktok", "settlements", ["shop_id", "tiktok_settlement_id"], unique=True)

    # --- Analytics tables ---

    op.create_table(
        "creators",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_creator_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creators_shop_tiktok", "creators", ["shop_id", "tiktok_creator_id"], unique=True)

    op.create_table(
        "livestreams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_livestream_id", sa.String(100), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("viewer_count", sa.Integer(), nullable=True),
        sa.Column("order_count", sa.Integer(), nullable=True),
        sa.Column("revenue", sa.Numeric(18, 2), nullable=True),
        sa.Column("update_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_livestreams_shop_tiktok", "livestreams", ["shop_id", "tiktok_livestream_id"], unique=True)

    op.create_table(
        "alert_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_configs_shop", "alert_configs", ["shop_id"])

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("alert_config_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["alert_config_id"], ["alert_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_history_shop", "alert_history", ["shop_id"])
    op.create_index("ix_alert_history_config", "alert_history", ["alert_config_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendations_shop", "recommendations", ["shop_id"])

    # --- RLS policies for Supabase (seller isolation) ---

    for table in (
        "orders", "products", "inventory_items", "settlements",
        "creators", "livestreams", "alert_configs", "alert_history",
        "recommendations",
    ):
        # `table` is drawn from the fixed tuple literal above (migration-time DDL), never
        # from user/request input, so there is no injection surface here.
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY {table}_isolation ON {table}
                USING (shop_id IN (
                    SELECT id FROM shops
                    WHERE user_id = current_setting('app.current_user_id')::uuid
                ));
        """)  # nosec B608


def downgrade() -> None:
    for table in reversed([
        "orders", "products", "inventory_items", "settlements",
        "creators", "livestreams", "alert_configs", "alert_history",
        "recommendations",
    ]):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_recommendations_shop", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index("ix_alert_history_config", table_name="alert_history")
    op.drop_index("ix_alert_history_shop", table_name="alert_history")
    op.drop_table("alert_history")

    op.drop_index("ix_alert_configs_shop", table_name="alert_configs")
    op.drop_table("alert_configs")

    op.drop_index("ix_livestreams_shop_tiktok", table_name="livestreams")
    op.drop_table("livestreams")

    op.drop_index("ix_creators_shop_tiktok", table_name="creators")
    op.drop_table("creators")

    op.drop_index("ix_settlements_shop_tiktok", table_name="settlements")
    op.drop_index("ix_settlements_shop_created", table_name="settlements")
    op.drop_table("settlements")

    op.drop_index("ix_inventory_shop_sku", table_name="inventory_items")
    op.drop_index("ix_inventory_shop_created", table_name="inventory_items")
    op.drop_table("inventory_items")

    op.drop_index("ix_products_shop_tiktok", table_name="products")
    op.drop_index("ix_products_shop_created", table_name="products")
    op.drop_table("products")

    op.drop_index("ix_orders_shop_tiktok", table_name="orders")
    op.drop_index("ix_orders_shop_created", table_name="orders")
    op.drop_table("orders")
