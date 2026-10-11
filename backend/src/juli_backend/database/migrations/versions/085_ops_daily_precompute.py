"""Juli Ops daily precompute, hourly commerce, audit merging + retention (fast track P18).

Revision ID: 085_ops_daily_precompute
Revises: 084_onboarding_speed
Create Date: 2026-10-11

DECISIONS D27 (Juli Ops: speed, confirmations, audit log).

WHAT IT ADDS.

- ``shop_daily_streams`` (D27.2): one row per shop × stream × day -- the raw
  impressions / clicks / SKU orders / GMV the diagnosis report computes
  (``report.daily_streams``), written when the report is built. The Ops
  "Mô phỏng" reads it instead of merging every stored report's JSON.
- ``shop_daily_products``: the same per product for each stream's top products
  (``report.daily_products``), with the row label (title, seller SKU) -- the
  volatility rows.
  Both are tenant tables like 082: RLS on, one policy per verb through
  ``app_current_shop_id()``; ``juli_app`` gets SELECT / INSERT / UPDATE (the
  write is an upsert). No DELETE: the history is kept.
- ``ops_shop_daily_summary`` (D27.1): one row per shop, the Tổng quan numbers
  computed once a day after the shop's analytics pass (or on "Làm mới").
  Ops-only like 083's tables: RLS on, the only policy ``FOR ALL TO juli_ops``,
  no grant to ``juli_app``.
- ``ops_audit_log.merged_count`` and ``ops_audit_log.field`` (D27.6: the one
  setting / rule a change touched, which merging matches on) and the grants that merging and the
  nightly retention job need: ``juli_ops`` may now UPDATE (merge an edit into
  the previous row) and DELETE (an edit reverted within 10 minutes; rows past
  retention, D27.4). An index on ``at`` serves the retention delete; the
  (shop_id, at) index already exists (083).
- ``ops_find_shop(uuid)``: ``ops_list_shops()`` for one shop (SECURITY
  DEFINER, ADR-089 shape, EXECUTE to ``juli_ops`` only), so a per-shop ops
  route no longer lists every shop.
- ``shop_ingestion_state.commerce_last_run_at`` (D27.3): the commerce steps
  run at most once per ``SHOP_COMMERCE_INTERVAL_MINUTES`` (60) per shop.

EXPAND-ONLY AND REVERSIBLE. Three new tables, three nullable / defaulted
columns, one index, one function, grants. No data change. ``downgrade`` drops them and
revokes the new grants. The deferred phone-cleanup step is re-parented onto
this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "085_ops_daily_precompute"
down_revision: str | None = "084_onboarding_speed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
TENANT_TABLES: tuple[str, ...] = ("shop_daily_streams", "shop_daily_products")
TENANT_VERBS = "SELECT, INSERT, UPDATE"
SUMMARY_TABLE = "ops_shop_daily_summary"
SUMMARY_VERBS = "SELECT, INSERT, UPDATE, DELETE"
AUDIT_TABLE = "ops_audit_log"
AUDIT_NEW_VERBS = "UPDATE, DELETE"


def _counts() -> list[sa.Column]:
    return [
        sa.Column("impressions", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("clicks", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("orders", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("gmv", sa.Numeric(precision=18, scale=2), nullable=False),
    ]


def _create_tenant_tables() -> None:
    op.create_table(
        "shop_daily_streams",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *_counts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", "stream", "day", name="pk_shop_daily_streams"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_shop_daily_streams_shop"),
    )
    op.create_table(
        "shop_daily_products",
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("product_id", sa.String(length=100), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *_counts(),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("seller_sku", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "shop_id", "stream", "product_id", "day", name="pk_shop_daily_products"
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_shop_daily_products_shop"),
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        for verb, clause in (
            ("SELECT", "USING (shop_id = app_current_shop_id())"),
            (
                "UPDATE",
                "USING (shop_id = app_current_shop_id()) "
                "WITH CHECK (shop_id = app_current_shop_id())",
            ),
            ("DELETE", "USING (shop_id = app_current_shop_id())"),
            ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
        ):
            op.execute(  # nosec B608 - table, verb and clause are fixed module constants
                f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {clause}"
            )
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'GRANT {TENANT_VERBS} ON public.{table} TO {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608


def _create_summary_table() -> None:
    op.create_table(
        SUMMARY_TABLE,
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("data_through", sa.Date(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name="pk_ops_shop_daily_summary"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ops_shop_daily_summary_shop"),
    )
    op.execute(f"ALTER TABLE public.{SUMMARY_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {SUMMARY_TABLE}_ops_only ON public.{SUMMARY_TABLE} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON public.{SUMMARY_TABLE} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{SUMMARY_TABLE} FROM {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {SUMMARY_VERBS} ON public.{SUMMARY_TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _audit_merge_and_retention() -> None:
    op.add_column(
        AUDIT_TABLE,
        sa.Column("merged_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(AUDIT_TABLE, sa.Column("field", sa.String(length=160), nullable=True))
    op.create_index("ix_ops_audit_log_at", AUDIT_TABLE, ["at"])
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {AUDIT_NEW_VERBS} ON public.{AUDIT_TABLE} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


FIND_SHOP_FN = "public.ops_find_shop(uuid)"


def _create_find_shop() -> None:
    """``ops_list_shops()`` for ONE shop: the per-shop routes no longer list every shop."""
    op.execute("""
    CREATE OR REPLACE FUNCTION public.ops_find_shop(p_shop_id uuid)
    RETURNS TABLE (
        out_shop_id uuid,
        out_shop_name varchar,
        out_tiktok_shop_id varchar,
        out_is_active boolean,
        out_created_at timestamp,
        out_owner_user_id uuid,
        out_owner_email varchar,
        out_owner_consent_at timestamp
    )
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $fn$
        SELECT s.id, s.shop_name, s.tiktok_shop_id, s.is_active, s.created_at,
               u.id, u.email, u.staff_access_consent_at
        FROM public.shops s
        JOIN public.users u ON u.id = s.user_id
        WHERE s.id = p_shop_id
    $fn$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {FIND_SHOP_FN} FROM PUBLIC")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION {FIND_SHOP_FN} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_tenant_tables()
    _create_summary_table()
    _audit_merge_and_retention()
    _create_find_shop()
    op.add_column(
        "shop_ingestion_state", sa.Column("commerce_last_run_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FIND_SHOP_FN}")
    op.drop_column("shop_ingestion_state", "commerce_last_run_at")
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'REVOKE {AUDIT_NEW_VERBS} ON public.{AUDIT_TABLE} FROM {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_index("ix_ops_audit_log_at", table_name=AUDIT_TABLE)
    op.drop_column(AUDIT_TABLE, "field")
    op.drop_column(AUDIT_TABLE, "merged_count")
    op.drop_table(SUMMARY_TABLE)
    for table in reversed(TENANT_TABLES):
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608
        op.drop_table(table)
