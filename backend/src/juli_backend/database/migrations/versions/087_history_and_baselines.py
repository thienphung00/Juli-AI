"""Product history, promotions, external changes, run baselines (fast track P23).

Revision ID: 087_history_and_baselines
Revises: 086_ops_cost_and_terms
Create Date: 2026-10-12

DECISIONS D30.1 (record history from now, baselines) and D30.4 (external changes).

WHAT IT ADDS. Five tenant tables, each like 085's / 086's: RLS on, one policy
per granted verb through ``app_current_shop_id()``; ``juli_app`` gets only the
verbs the code needs.

- ``product_snapshots``: a product's content (title, description or its hash,
  main images, attributes hash) and SKU prices when they changed. Unique per
  (shop, product, local day, ``state_hash``) so a replayed read is stored once
  but a change and its revert on later days both stay. Append-only: SELECT,
  INSERT.
- ``promotion_activities`` + ``promotion_activity_products``: every activity of
  any status (incl. EXPIRED / DEACTIVATED) with dates and per-product / SKU
  activity price, upserted: SELECT, INSERT, UPDATE (a removed product keeps
  its row with ``removed_at``; nothing is deleted).
- ``external_changes``: what changed on a product (or the shop's promotions),
  when, from which source, and whether it was Juli's own write. Append-only,
  deduplicated on ``(shop_id, dedup_key)``: SELECT, INSERT.
- ``run_baselines``: a run's 14-day metric pre-series, price, active
  promotions, content hash and listing codes at approval and at execution
  start; ``quality_score`` stays NULL until the D30.2 algorithm fills it:
  SELECT, INSERT, UPDATE.

EXPAND-ONLY AND REVERSIBLE. New tables, policies and grants only; no data
change. ``downgrade`` drops them. The deferred phone-cleanup step is
re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "087_history_and_baselines"
down_revision: str | None = "086_ops_cost_and_terms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
SNAPSHOTS_TABLE = "product_snapshots"
ACTIVITIES_TABLE = "promotion_activities"
ACTIVITY_PRODUCTS_TABLE = "promotion_activity_products"
CHANGES_TABLE = "external_changes"
BASELINES_TABLE = "run_baselines"

#: Append-only history: no UPDATE, no DELETE.
APPEND_ONLY_VERBS = "SELECT, INSERT"
#: Upserted (promotions) or filled later (``run_baselines.quality_score``): no DELETE.
UPSERT_VERBS = "SELECT, INSERT, UPDATE"

#: table -> granted verbs. Every table here is tenant-direct.
GRANTS: dict[str, str] = {
    SNAPSHOTS_TABLE: APPEND_ONLY_VERBS,
    ACTIVITIES_TABLE: UPSERT_VERBS,
    ACTIVITY_PRODUCTS_TABLE: UPSERT_VERBS,
    CHANGES_TABLE: APPEND_ONLY_VERBS,
    BASELINES_TABLE: UPSERT_VERBS,
}

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}

CHANGE_KINDS_SQL = (
    "kind IN ('content', 'price', 'promotion', 'category', 'status', 'creation', 'inventory')"
)


def _create_snapshots() -> None:
    op.create_table(
        SNAPSHOTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("description_hash", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("main_images", sa.JSON(), nullable=True),
        sa.Column("attributes_hash", sa.String(length=64), nullable=True),
        sa.Column("skus", sa.JSON(), nullable=True),
        sa.Column("category_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("tiktok_update_time", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_product_snapshots"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_product_snapshots_shop"),
        sa.UniqueConstraint(
            "shop_id",
            "tiktok_product_id",
            "snapshot_date",
            "state_hash",
            name="uq_product_snapshots_day_state",
        ),
    )
    op.create_index(
        "ix_product_snapshots_product_taken",
        SNAPSHOTS_TABLE,
        ["shop_id", "tiktok_product_id", "taken_at"],
    )


def _create_activities() -> None:
    op.create_table(
        ACTIVITIES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.String(length=100), nullable=False),
        sa.Column("activity_type", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("product_level", sa.String(length=30), nullable=True),
        sa.Column("begin_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("tiktok_create_time", sa.DateTime(), nullable=True),
        sa.Column("tiktok_update_time", sa.DateTime(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(), nullable=False),
        sa.Column("detail_fetched_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_activities"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_promotion_activities_shop"),
        sa.UniqueConstraint("shop_id", "activity_id", name="uq_promotion_activities_activity"),
    )
    op.create_index(
        "ix_promotion_activities_shop_window",
        ACTIVITIES_TABLE,
        ["shop_id", "begin_time", "end_time"],
    )
    op.create_table(
        ACTIVITY_PRODUCTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.String(length=100), nullable=False),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=False),
        sa.Column("tiktok_sku_id", sa.String(length=100), nullable=False),
        sa.Column("activity_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("discount_pct", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_activity_products"),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name="fk_promotion_activity_products_shop"
        ),
        sa.UniqueConstraint(
            "shop_id",
            "activity_id",
            "tiktok_product_id",
            "tiktok_sku_id",
            name="uq_promotion_activity_products_sku",
        ),
    )
    op.create_index(
        "ix_promotion_activity_products_product",
        ACTIVITY_PRODUCTS_TABLE,
        ["shop_id", "tiktok_product_id"],
    )


def _create_changes() -> None:
    op.create_table(
        CHANGES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("juli_write", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_external_changes"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_external_changes_shop"),
        sa.UniqueConstraint("shop_id", "dedup_key", name="uq_external_changes_dedup"),
        sa.CheckConstraint(CHANGE_KINDS_SQL, name="ck_external_changes_kind"),
    )
    op.create_index(
        "ix_external_changes_product_time",
        CHANGES_TABLE,
        ["shop_id", "tiktok_product_id", "occurred_at"],
    )


def _create_baselines() -> None:
    op.create_table(
        BASELINES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("action_card_id", sa.Uuid(), nullable=True),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("metrics_pre", sa.JSON(), nullable=True),
        sa.Column("price", sa.JSON(), nullable=True),
        sa.Column("active_promotions", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("listing_codes", sa.JSON(), nullable=True),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_run_baselines"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_baselines_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_baselines_run"
        ),
        sa.ForeignKeyConstraint(
            ["action_card_id"], ["action_cards.id"], name="fk_run_baselines_card"
        ),
        sa.UniqueConstraint("workflow_run_id", "phase", name="uq_run_baselines_run_phase"),
        sa.CheckConstraint("phase IN ('approval', 'execution')", name="ck_run_baselines_phase"),
    )
    op.create_index("ix_run_baselines_shop_id", BASELINES_TABLE, ["shop_id"])


def _secure(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    for verb in (v.strip() for v in verbs.split(",")):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} "
            f"FOR {verb} {_CLAUSES[verb]}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {verbs} ON public.{table} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_snapshots()
    _create_activities()
    _create_changes()
    _create_baselines()
    for table, verbs in GRANTS.items():
        _secure(table, verbs)


def downgrade() -> None:
    for table in GRANTS:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608
    op.drop_index("ix_run_baselines_shop_id", table_name=BASELINES_TABLE)
    op.drop_table(BASELINES_TABLE)
    op.drop_index("ix_external_changes_product_time", table_name=CHANGES_TABLE)
    op.drop_table(CHANGES_TABLE)
    op.drop_index("ix_promotion_activity_products_product", table_name=ACTIVITY_PRODUCTS_TABLE)
    op.drop_table(ACTIVITY_PRODUCTS_TABLE)
    op.drop_index("ix_promotion_activities_shop_window", table_name=ACTIVITIES_TABLE)
    op.drop_table(ACTIVITIES_TABLE)
    op.drop_index("ix_product_snapshots_product_taken", table_name=SNAPSHOTS_TABLE)
    op.drop_table(SNAPSHOTS_TABLE)
