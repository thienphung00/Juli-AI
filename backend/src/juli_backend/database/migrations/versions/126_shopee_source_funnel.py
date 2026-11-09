"""The Shopee funnel per traffic source, per day (P98 / ADR-122 d.3)

Revision ID: 126_shopee_source_funnel
Revises: 125_reco_plan_groups
Create Date: 2026-11-09

One tenant-direct table, SELECT / INSERT / UPDATE under RLS for ``juli_app`` (additive, no data
step; rows are upserted, never deleted):

- ``shopee_source_metrics_daily`` -- one row per (shop, GMT+7 day, item or NULL = the shop,
  source): lượt xem / lượt nhấp from the traffic tables; đơn / GMV / lợi nhuận allocated from
  ShopMetrics so the six sources of a scope add up to its shop (or product) row exactly, the
  residual in ``chenh_lech_nguon``; the "trong đó Quảng cáo" share on ``the_san_pham_khac``.

The natural key (shop, day, item, source) is two partial unique indexes: ``item_id IS NULL`` (the
shop rows) and ``item_id IS NOT NULL`` (product rows), because NULLs never collide in a plain
unique constraint.

EXPAND-ONLY AND REVERSIBLE. Fill an existing shop with ``python scripts/backfill_shopee_metrics.py``
after upgrading (the same script as migration 123).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "126_shopee_source_funnel"
down_revision: str | None = "125_reco_plan_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
SOURCE = "shopee_source_metrics_daily"
TENANT_TABLES = (SOURCE,)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}
_SOURCES = "'the_san_pham_khac', 'trang_shop', 'live', 'video', 'lien_ket', 'chenh_lech_nguon'"


def _money(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 2), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        SOURCE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        _money("gmv", nullable=False),
        _money("profit"),
        sa.Column("ads_views", sa.Integer(), nullable=True),
        sa.Column("ads_clicks", sa.Integer(), nullable=True),
        sa.Column("ads_orders", sa.Integer(), nullable=True),
        _money("ads_gmv"),
        _money("ads_spend"),
        sa.Column("scaled_to_totals", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("built_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SOURCE}"),
        sa.CheckConstraint(f"source IN ({_SOURCES})", name="ck_shopee_source_metrics_daily_source"),
    )
    op.create_index(
        "uq_shopee_source_metrics_daily_shop",
        SOURCE,
        ["shop_id", "day", "source"],
        unique=True,
        postgresql_where=sa.text("item_id IS NULL"),
    )
    op.create_index(
        "uq_shopee_source_metrics_daily_item",
        SOURCE,
        ["shop_id", "day", "item_id", "source"],
        unique=True,
        postgresql_where=sa.text("item_id IS NOT NULL"),
    )
    op.create_index("ix_shopee_source_metrics_daily_item", SOURCE, ["shop_id", "item_id", "day"])
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
    op.drop_index("ix_shopee_source_metrics_daily_item", table_name=SOURCE)
    op.drop_index("uq_shopee_source_metrics_daily_item", table_name=SOURCE)
    op.drop_index("uq_shopee_source_metrics_daily_shop", table_name=SOURCE)
    op.drop_table(SOURCE)
