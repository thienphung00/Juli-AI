"""silver orders/returns domain cutover (#607)

Revision ID: 025_silver_orders_returns
Revises: 024_gold_kpi_envelopes
Create Date: 2026-07-30

Cutover:
- ``silver.orders`` / ``silver.returns`` are domain SoT with natural keys per shop.
- Legacy ``public.orders`` / ``public.returns`` become read-only after data migration.
- ``order_items.order_id`` FK retargeted to ``silver.orders`` (line items stay public).
- A1 reconcile / cancellation_rate KPI precompute remains out of scope.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025_silver_orders_returns"
down_revision: str | None = "024_gold_kpi_envelopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
SILVER_TABLES: tuple[str, ...] = ("silver.orders", "silver.returns")
LEGACY_ORDERS = "public.orders"
LEGACY_RETURNS = "public.returns"


def _revoke_client_table(table: str) -> None:
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $silver$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    REVOKE ALL ON TABLE {table} FROM {role};
  END IF;
END
$silver$;
"""  # nosec B608 — table/role are fixed module constants
        op.execute(sql)


def _order_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("buyer_id", sa.String(length=100), nullable=True),
        sa.Column("order_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("payment_time", sa.DateTime(), nullable=True),
        sa.Column("ship_time", sa.DateTime(), nullable=True),
        sa.Column("delivery_time", sa.DateTime(), nullable=True),
        sa.Column("tiktok_created_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("is_seller_fault", sa.Boolean(), nullable=True),
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
    ]


def _return_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("tiktok_return_id", sa.String(length=100), nullable=False),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=False),
        sa.Column("buyer_id", sa.String(length=100), nullable=True),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.Column("tiktok_sku_id", sa.String(length=100), nullable=True),
        sa.Column("return_type", sa.String(length=30), nullable=False),
        sa.Column(
            "return_condition",
            sa.String(length=30),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("return_reason", sa.String(length=500), nullable=True),
        sa.Column("refund_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
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
    ]


def _block_legacy_writes(table: str, label: str) -> None:
    fn_name = f"prevent_{label}_writes"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.{fn_name}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                '{table} is read-only after silver cutover (#607); write silver.{label}';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_{label}_no_write
            BEFORE INSERT OR UPDATE OR DELETE
            ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION public.{fn_name}();
        """
    )


def _unblock_legacy_writes(table: str, label: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{label}_no_write ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS public.prevent_{label}_writes()")


def upgrade() -> None:
    op.create_table(
        "orders",
        *_order_columns(),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "tiktok_order_id",
            name="uq_silver_orders_shop_tiktok",
        ),
        schema="silver",
    )
    op.create_index(
        "ix_silver_orders_shop_created",
        "orders",
        ["shop_id", "created_at"],
        schema="silver",
    )

    op.create_table(
        "returns",
        *_return_columns(),
        sa.ForeignKeyConstraint(["order_id"], ["silver.orders.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "tiktok_return_id",
            name="uq_silver_returns_shop_tiktok",
        ),
        schema="silver",
    )
    op.create_index(
        "ix_silver_returns_shop_created",
        "returns",
        ["shop_id", "created_at"],
        schema="silver",
    )

    # Migrate legacy domain rows preserving PKs for order_items FK continuity.
    op.execute(
        """
        INSERT INTO silver.orders (
            id, shop_id, tiktok_order_id, status, buyer_id, order_value,
            total_amount, currency, payment_time, ship_time, delivery_time,
            tiktok_created_at, cancel_reason, is_seller_fault, update_time,
            created_at, updated_at
        )
        SELECT
            id, shop_id, tiktok_order_id, status, buyer_id, order_value,
            total_amount, currency, payment_time, ship_time, delivery_time,
            tiktok_created_at, cancel_reason, is_seller_fault, update_time,
            created_at, updated_at
        FROM public.orders
        ON CONFLICT (shop_id, tiktok_order_id) DO UPDATE SET
            status = EXCLUDED.status,
            buyer_id = EXCLUDED.buyer_id,
            order_value = EXCLUDED.order_value,
            total_amount = EXCLUDED.total_amount,
            currency = EXCLUDED.currency,
            payment_time = EXCLUDED.payment_time,
            ship_time = EXCLUDED.ship_time,
            delivery_time = EXCLUDED.delivery_time,
            tiktok_created_at = EXCLUDED.tiktok_created_at,
            cancel_reason = EXCLUDED.cancel_reason,
            is_seller_fault = EXCLUDED.is_seller_fault,
            update_time = EXCLUDED.update_time,
            updated_at = EXCLUDED.updated_at
        """
    )

    op.execute(
        """
        INSERT INTO silver.returns (
            id, shop_id, order_id, tiktok_return_id, tiktok_order_id, buyer_id,
            tiktok_product_id, tiktok_sku_id, return_type, return_condition,
            return_reason, refund_amount, status, update_time, created_at, updated_at
        )
        SELECT
            id, shop_id, order_id, tiktok_return_id, tiktok_order_id, buyer_id,
            tiktok_product_id, tiktok_sku_id, return_type, return_condition,
            return_reason, refund_amount, status, update_time, created_at, updated_at
        FROM public.returns
        ON CONFLICT (shop_id, tiktok_return_id) DO UPDATE SET
            order_id = EXCLUDED.order_id,
            tiktok_order_id = EXCLUDED.tiktok_order_id,
            buyer_id = EXCLUDED.buyer_id,
            tiktok_product_id = EXCLUDED.tiktok_product_id,
            tiktok_sku_id = EXCLUDED.tiktok_sku_id,
            return_type = EXCLUDED.return_type,
            return_condition = EXCLUDED.return_condition,
            return_reason = EXCLUDED.return_reason,
            refund_amount = EXCLUDED.refund_amount,
            status = EXCLUDED.status,
            update_time = EXCLUDED.update_time,
            updated_at = EXCLUDED.updated_at
        """
    )

    # Retarget order_items FK from public.orders → silver.orders.
    op.drop_constraint("order_items_order_id_fkey", "order_items", type_="foreignkey")
    op.create_foreign_key(
        "order_items_order_id_fkey",
        "order_items",
        "orders",
        ["order_id"],
        ["id"],
        referent_schema="silver",
    )

    for table in SILVER_TABLES:
        _revoke_client_table(table)

    _block_legacy_writes(LEGACY_ORDERS, "orders")
    _block_legacy_writes(LEGACY_RETURNS, "returns")


def downgrade() -> None:
    _unblock_legacy_writes(LEGACY_RETURNS, "returns")
    _unblock_legacy_writes(LEGACY_ORDERS, "orders")

    op.drop_constraint("order_items_order_id_fkey", "order_items", type_="foreignkey")
    op.create_foreign_key(
        "order_items_order_id_fkey",
        "order_items",
        "orders",
        ["order_id"],
        ["id"],
    )

    op.drop_index("ix_silver_returns_shop_created", table_name="returns", schema="silver")
    op.drop_table("returns", schema="silver")
    op.drop_index("ix_silver_orders_shop_created", table_name="orders", schema="silver")
    op.drop_table("orders", schema="silver")
