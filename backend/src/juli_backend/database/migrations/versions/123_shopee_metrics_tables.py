"""Materialized Shopee metrics and the frozen plan base (P97 D85.2 / D85.4)

Revision ID: 123_shopee_metrics_tables
Revises: 121_shop_members
Create Date: 2026-11-09

NOTE FOR INTEGRATION: the owner's chain is 121 -> 122_shopee_affiliate_lines (T1) -> this revision.
T1's migration is not in this branch, so the parent is temporarily ``121_shop_members``; rebase
``down_revision`` to ``122_shopee_affiliate_lines`` when the two branches meet.

Three tenant-direct tables, SELECT / INSERT / UPDATE under RLS for ``juli_app`` (additive, no data
step; rows are upserted, never deleted):

- ``shopee_shop_metrics_daily`` -- the shop's day: GMV, đơn, AOV, funnel, ads, profit, source tags.
- ``shopee_product_metrics_daily`` -- the day's product rows scaled to the shop row (+ residual).
- ``shopee_plan_base_snapshots`` -- the versioned base a draft plan is evaluated on.

Backfill an existing shop with ``python scripts/backfill_shopee_metrics.py`` after upgrading.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "123_shopee_metrics_tables"
down_revision: str | None = "121_shop_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
SHOP = "shopee_shop_metrics_daily"
PRODUCT = "shopee_product_metrics_daily"
SNAP = "shopee_plan_base_snapshots"
TENANT_TABLES = (SHOP, PRODUCT, SNAP)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}
_ORDER_TYPES = "'placed', 'paid', 'confirmed'"


def _jsonb() -> sa.types.TypeEngine:
    from sqlalchemy.dialects.postgresql import JSONB

    return JSONB()


def _money(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 2), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        SHOP,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("order_type", sa.String(length=12), nullable=False),
        _money("gmv"),
        sa.Column("orders", sa.Integer(), nullable=True),
        _money("aov"),
        sa.Column("units", sa.Integer(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("visitors", sa.Integer(), nullable=True),
        sa.Column("product_clicks", sa.Integer(), nullable=True),
        _money("ads_spend"),
        _money("ads_gmv"),
        _money("profit"),
        _money("margin_profit"),
        _money("buyer_paid_known"),
        sa.Column("cogs_coverage", sa.Numeric(7, 4), nullable=True),
        _money("line_gmv"),
        sa.Column("line_orders", sa.Integer(), nullable=True),
        sa.Column("sources", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("detail", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("built_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SHOP}"),
        sa.UniqueConstraint("shop_id", "day", "order_type", name="uq_shopee_shop_metrics_daily"),
        sa.CheckConstraint(
            f"order_type IN ({_ORDER_TYPES})", name="ck_shopee_shop_metrics_daily_order_type"
        ),
    )
    op.create_index("ix_shopee_shop_metrics_daily_complete", SHOP, ["shop_id", "complete", "day"])
    op.create_table(
        PRODUCT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("order_type", sa.String(length=12), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("variation_id", sa.String(length=64), nullable=True),
        _money("gmv", nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        _money("ads_spend"),
        _money("profit"),
        _money("line_gmv", nullable=False),
        sa.Column("line_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("scaled_to_totals", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("built_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PRODUCT}"),
        sa.UniqueConstraint(
            "shop_id", "day", "order_type", "item_id", name="uq_shopee_product_metrics_daily"
        ),
        sa.CheckConstraint(
            f"order_type IN ({_ORDER_TYPES})", name="ck_shopee_product_metrics_daily_order_type"
        ),
    )
    op.create_index("ix_shopee_product_metrics_daily_item", PRODUCT, ["shop_id", "item_id", "day"])
    op.create_table(
        SNAP,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("shop_reco_plans.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("base", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("created_by", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SNAP}"),
        sa.UniqueConstraint("plan_id", "version", name="uq_shopee_plan_base_snapshots_version"),
    )
    op.create_index("ix_shopee_plan_base_snapshots_shop", SNAP, ["shop_id", "plan_id"])
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
        for verb in ("SELECT", "INSERT", "UPDATE"):
            op.execute(  # nosec B608 - fixed module constants
                f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {_CLAUSES[verb]}"
            )
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{table} TO {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_index("ix_shopee_plan_base_snapshots_shop", table_name=SNAP)
    op.drop_table(SNAP)
    op.drop_index("ix_shopee_product_metrics_daily_item", table_name=PRODUCT)
    op.drop_table(PRODUCT)
    op.drop_index("ix_shopee_shop_metrics_daily_complete", table_name=SHOP)
    op.drop_table(SHOP)
