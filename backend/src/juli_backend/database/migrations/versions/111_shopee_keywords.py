"""Shopee keyword dashboard: public keyword metrics and the shop's keyword seeds (ADR-119)

Revision ID: 111_shopee_keywords
Revises: 110_ops_shop_platform
Create Date: 2026-11-03

ADR-119 (owner grill D81.4-D81.8, 2026-11-03): Juli Ops "Từ khóa". Keyword combinations are
decomposed from the shop's own product titles; their search volume, CPC and difficulty come
from shopeeanalytics.com lookups the owner makes in their own browser and uploads weekly.

- ``market_keyword_metrics`` -- PUBLIC LANE (ADR-116 §1), no ``shop_id``: one row per
  (source, keyword, seed, collection day). ``seed`` is the keyword that was looked up;
  ``keyword`` is one row of its result (the seed itself or a related keyword). A lookup the
  site refused (``blocked``) or the owner marked empty (``no_match``) is one row with
  ``keyword = seed`` and no numbers -- never a zero. Ops-only like 108's market tables
  (RLS on, the only policy ``TO juli_ops``; ``juli_ops`` SELECT, INSERT, UPDATE: a re-upload
  of the same day replaces its numbers).
- ``shop_keyword_seeds`` -- CLIENT LANE, tenant-direct (RLS by ``app_current_shop_id()``;
  ``juli_app`` SELECT, INSERT, UPDATE): which keyword combinations came from which of the
  shop's items. The operator trims by ``enabled``; rows are never deleted on this path.
  Offboarding removes them with every other ``shop_id`` table (094's purge). ``created_by``
  is a plain staff uuid, not a foreign key into an Ops-only table (as 109).

EXPAND-ONLY AND REVERSIBLE. Tables, indexes, policies and grants; no data change.
``downgrade`` drops them. The deferred write-mode backfill (and the phone cleanup under it)
is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "111_shopee_keywords"
down_revision: str | None = "110_ops_shop_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
METRICS_TABLE = "market_keyword_metrics"
SEEDS_TABLE = "shop_keyword_seeds"

#: Written out rather than imported from the models: a migration must not change when
#: the model does. ``tests/unit/test_shopee_keywords.py`` pins them equal.
PLATFORMS = ("tiktok", "shopee")
SOURCES = ("shopeeanalytics",)
STATUSES = ("ok", "blocked", "no_match")
PATTERNS = (
    "brand_type",
    "brand_function",
    "brand_material",
    "type_function_material",
    "type_function",
    "type_material",
    "function_material",
    "function_size",
    "type_size",
    "common_phrase",
)

UPSERT_VERBS = "SELECT, INSERT, UPDATE"

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _create_metrics() -> None:
    score = sa.Numeric(precision=8, scale=2)
    money = sa.Numeric(precision=14, scale=2)
    op.create_table(
        METRICS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("seed", sa.String(length=200), nullable=False),
        sa.Column("collected_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("cpc_min", money, nullable=True),
        sa.Column("cpc_max", money, nullable=True),
        sa.Column("difficulty", score, nullable=True),
        sa.Column("competition", score, nullable=True),
        sa.Column("opportunity", score, nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{METRICS_TABLE}"),
        sa.UniqueConstraint(
            "source", "keyword", "seed", "collected_on", name=f"uq_{METRICS_TABLE}_key"
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{METRICS_TABLE}_platform"),
        sa.CheckConstraint(f"source IN ({_in(SOURCES)})", name=f"ck_{METRICS_TABLE}_source"),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name=f"ck_{METRICS_TABLE}_status"),
        sa.CheckConstraint(
            "status = 'ok' OR (keyword = seed AND volume IS NULL AND cpc_min IS NULL "
            "AND cpc_max IS NULL AND difficulty IS NULL AND competition IS NULL "
            "AND opportunity IS NULL)",
            name=f"ck_{METRICS_TABLE}_no_numbers",
        ),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name=f"ck_{METRICS_TABLE}_volume"),
    )
    op.create_index(f"ix_{METRICS_TABLE}_keyword", METRICS_TABLE, ["keyword", "collected_on"])
    op.create_index(f"ix_{METRICS_TABLE}_seed", METRICS_TABLE, ["seed", "collected_on"])


def _create_seeds() -> None:
    op.create_table(
        SEEDS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("pattern", sa.String(length=32), nullable=False),
        sa.Column("item_ids", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SEEDS_TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{SEEDS_TABLE}_shop"),
        sa.UniqueConstraint("shop_id", "platform", "keyword", name=f"uq_{SEEDS_TABLE}_key"),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{SEEDS_TABLE}_platform"),
        sa.CheckConstraint(f"pattern IN ({_in(PATTERNS)})", name=f"ck_{SEEDS_TABLE}_pattern"),
    )


def _secure_tenant(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant (088's shape)."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
    for verb in (v.strip() for v in verbs.split(",")):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {_CLAUSES[verb]}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {verbs} ON public.{table} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def _secure_ops(table: str, verbs: str) -> None:
    """RLS on, the only policy ``TO juli_ops``, nothing for any other role (108's shape)."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {table}_ops_only ON public.{table} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM anon';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM authenticated';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT {verbs} ON public.{table} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def upgrade() -> None:
    _create_metrics()
    _create_seeds()
    _secure_ops(METRICS_TABLE, UPSERT_VERBS)
    _secure_tenant(SEEDS_TABLE, UPSERT_VERBS)


def downgrade() -> None:
    for table in (SEEDS_TABLE, METRICS_TABLE):
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {OPS_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
        op.drop_table(table)
