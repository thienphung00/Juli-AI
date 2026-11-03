"""Shopee profit and history: item snapshots, order lines, fee formulas, rule versions (ADR-120)

Revision ID: 112_shopee_profit_and_history
Revises: 111_shopee_keywords
Create Date: 2026-11-03

ADR-120 (owner-approved 2026-11-03, "broad -> precise"): profit per product and per source,
the red-line floor price, product-page history and the what-if on cards.

CLIENT LANE, tenant-direct (``shop_id``, RLS by ``app_current_shop_id()``):

- ``platform_item_snapshots`` -- append-only history of an item / variation as the platform
  showed it. A writer inserts a row ONLY WHEN a tracked field changed since the latest
  snapshot of that item / variation; that rule lives in the service, SQL cannot express it.
  ``juli_app`` SELECT, INSERT.
- ``product_image_assets`` -- Juli's private copy of each image version, unique per
  (``shop_id``, ``image_hash``). SELECT, INSERT.
- ``shopee_order_lines`` -- one row per order line. PII-free by construction: no column
  exists for a buyer name, phone or address, and ``order_ref`` is a keyed hash made in the
  browser, never the platform's order id (a CHECK cannot tell a hash from an id; the
  gateway mapper owns that). Fees and payout are NULL when the export lacks them, never 0.
  SELECT, INSERT, UPDATE (status and payout move as the order completes).
- ``shop_rule_versions`` -- append-only history of rule values; ``shop_rules`` (078) stays
  the CURRENT projection. SELECT, INSERT.
- ``ad_campaign_purposes`` -- what each ad campaign is for. History is APPEND-ONLY ROWS,
  latest ``set_at`` wins (not a version column: a purpose change has no counter to race
  on). A ``ra_mat`` (launch) purpose must carry a daily budget cap and an end date.
  SELECT, INSERT.

REFERENCE, no ``shop_id``:

- ``platform_fee_formulas`` -- the platform's public fee policy per category, versioned
  by ``effective_from`` / ``effective_to``. ``juli_ops`` writes (SELECT, INSERT, UPDATE:
  closing a version sets ``effective_to``), ``juli_app`` may only read -- it is public
  platform policy, not client data. Classified ``non_tenant`` like ``ops_system_settings``
  (086), the same policy shape.

ALTERED:

- ``shop_keyword_seeds.role`` ('chinh' | 'phu' | 'thuong_hieu' | 'loai_tru', NULL for rows
  written before roles) and ``item_scope`` (the item the role applies to). "At most 5
  'chinh' per item" is a SERVICE rule: a CHECK cannot count rows and a partial unique index
  cannot express a limit of five.
- ``card_events`` accepts ``whatif_adjusted`` (payload: inputs from -> to, outcome shown).
  It is not a single-per-card event: the seller may move a what-if input many times.

EXPAND-ONLY AND REVERSIBLE. Tables, columns, indexes, policies, grants and one widened CHECK;
no data change. ``downgrade`` drops the tables and columns and restores the narrower
``card_events`` CHECK as ``NOT VALID`` (rows written meanwhile keep their value). The
deferred write-mode backfill (and the phone cleanup under it) is re-parented onto this
revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "112_shopee_profit_and_history"
down_revision: str | None = "111_shopee_keywords"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
SNAPSHOTS_TABLE = "platform_item_snapshots"
ASSETS_TABLE = "product_image_assets"
LINES_TABLE = "shopee_order_lines"
FORMULAS_TABLE = "platform_fee_formulas"
VERSIONS_TABLE = "shop_rule_versions"
PURPOSES_TABLE = "ad_campaign_purposes"
SEEDS_TABLE = "shop_keyword_seeds"
EVENTS_TABLE = "card_events"
EVENT_TYPE_CHECK = "ck_card_events_event_type"
SEED_ROLE_CHECK = "ck_shop_keyword_seeds_role"

#: Written out rather than imported from the models: a migration must not change when
#: the model does. ``tests/unit/test_shopee_profit_schema.py`` pins them equal.
PLATFORMS = ("tiktok", "shopee")
PROMO_KINDS = ("none", "voucher", "discount", "flash_sale", "bundle", "add_on")
AD_PURPOSES = ("hien_thi", "luot_vao_shop", "chuyen_doi", "ra_mat")
SET_BY = ("team", "seller")
SEED_ROLES = ("chinh", "phu", "thuong_hieu", "loai_tru")
EVENT_TYPES_095 = (
    "proposed",
    "shown",
    "accepted",
    "edited",
    "dismissed",
    "expired",
    "seller_done",
    "executed",
    "not_executed",
    "reverted",
    "impact_preliminary",
    "impact_final",
    "seller_change",
    "shadow",
    "superseded",
)
EVENT_TYPES = (*EVENT_TYPES_095, "whatif_adjusted")

APPEND_ONLY_VERBS = "SELECT, INSERT"
UPSERT_VERBS = "SELECT, INSERT, UPDATE"

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}

#: Tenant table -> its ``juli_app`` verbs (policy per verb, same list for the GRANT).
TENANT_VERBS: dict[str, str] = {
    SNAPSHOTS_TABLE: APPEND_ONLY_VERBS,
    ASSETS_TABLE: APPEND_ONLY_VERBS,
    LINES_TABLE: UPSERT_VERBS,
    VERSIONS_TABLE: APPEND_ONLY_VERBS,
    PURPOSES_TABLE: APPEND_ONLY_VERBS,
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _shop_column() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False)


def _platform_check(table: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{table}_platform")


def _create_snapshots() -> None:
    money = sa.Numeric(precision=18, scale=2)
    op.create_table(
        SNAPSHOTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("variation_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(), nullable=False),
        sa.Column("image_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("list_price", money, nullable=True),
        sa.Column("current_price", money, nullable=True),
        sa.Column("promo_label", sa.String(length=255), nullable=True),
        sa.Column("promo_start", sa.DateTime(), nullable=True),
        sa.Column("promo_end", sa.DateTime(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("sold_total", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("category_path", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("created_on", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SNAPSHOTS_TABLE}"),
        _platform_check(SNAPSHOTS_TABLE),
    )
    # Unique: one snapshot per item / variation per instant makes a re-ingest idempotent.
    op.create_index(
        f"ix_{SNAPSHOTS_TABLE}_item_time",
        SNAPSHOTS_TABLE,
        ["shop_id", "platform", "item_id", "variation_id", sa.text("captured_at DESC")],
        unique=True,
    )


def _create_assets() -> None:
    op.create_table(
        ASSETS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("image_hash", sa.String(length=128), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{ASSETS_TABLE}"),
        sa.UniqueConstraint("shop_id", "image_hash", name=f"uq_{ASSETS_TABLE}_hash"),
    )


def _create_lines() -> None:
    money = sa.Numeric(precision=18, scale=2)
    op.create_table(
        LINES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("order_ref", sa.String(length=128), nullable=False),
        sa.Column("line_no", sa.SmallInteger(), nullable=False),
        sa.Column("ordered_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("variation_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("original_price", money, nullable=False),
        sa.Column("deal_price", money, nullable=False),
        sa.Column("shop_voucher_share", money, server_default="0", nullable=False),
        sa.Column("platform_voucher_share", money, server_default="0", nullable=False),
        sa.Column("bundle_discount", money, server_default="0", nullable=False),
        sa.Column("promo_kind", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("voucher_code", sa.String(length=64), nullable=True),
        sa.Column("traffic_source", sa.String(length=32), nullable=True),
        sa.Column("affiliate", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("commission", money, nullable=True),
        sa.Column("fee_fixed", money, nullable=True),
        sa.Column("fee_service", money, nullable=True),
        sa.Column("fee_payment", money, nullable=True),
        sa.Column("fee_other", money, nullable=True),
        sa.Column("payout", money, nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{LINES_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "platform", "order_ref", "line_no", name=f"uq_{LINES_TABLE}_key"
        ),
        _platform_check(LINES_TABLE),
        sa.CheckConstraint(
            f"promo_kind IN ({_in(PROMO_KINDS)})", name=f"ck_{LINES_TABLE}_promo_kind"
        ),
        sa.CheckConstraint("qty >= 0", name=f"ck_{LINES_TABLE}_qty"),
    )
    op.create_index(
        f"ix_{LINES_TABLE}_item_time", LINES_TABLE, ["shop_id", "item_id", "ordered_at"]
    )
    op.create_index(f"ix_{LINES_TABLE}_time", LINES_TABLE, ["shop_id", "ordered_at"])


def _create_formulas() -> None:
    op.create_table(
        FORMULAS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("category_path", postgresql.JSONB(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{FORMULAS_TABLE}"),
        sa.UniqueConstraint(
            "platform", "category_path", "effective_from", name=f"uq_{FORMULAS_TABLE}_key"
        ),
        _platform_check(FORMULAS_TABLE),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name=f"ck_{FORMULAS_TABLE}_period",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(components) = 'array'", name=f"ck_{FORMULAS_TABLE}_components"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(category_path) = 'array'", name=f"ck_{FORMULAS_TABLE}_category"
        ),
    )


def _create_versions() -> None:
    op.create_table(
        VERSIONS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("rule_key", sa.String(length=40), nullable=False),
        sa.Column("scope_ref", sa.String(length=100), server_default="", nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("set_by", sa.String(length=10), nullable=False),
        sa.Column("set_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("import_file_hash", sa.String(length=64), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{VERSIONS_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "rule_key", "scope_ref", "version", name=f"uq_{VERSIONS_TABLE}_key"
        ),
        sa.CheckConstraint(f"set_by IN ({_in(SET_BY)})", name=f"ck_{VERSIONS_TABLE}_set_by"),
        sa.CheckConstraint("version >= 1", name=f"ck_{VERSIONS_TABLE}_version"),
    )
    op.create_index(f"ix_{VERSIONS_TABLE}_shop", VERSIONS_TABLE, ["shop_id"])


def _create_purposes() -> None:
    op.create_table(
        PURPOSES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("campaign_key", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("budget_cap_daily", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("set_by", sa.String(length=10), nullable=False),
        sa.Column("set_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PURPOSES_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "platform", "campaign_key", "set_at", name=f"uq_{PURPOSES_TABLE}_key"
        ),
        _platform_check(PURPOSES_TABLE),
        sa.CheckConstraint(f"purpose IN ({_in(AD_PURPOSES)})", name=f"ck_{PURPOSES_TABLE}_purpose"),
        sa.CheckConstraint(f"set_by IN ({_in(SET_BY)})", name=f"ck_{PURPOSES_TABLE}_set_by"),
        sa.CheckConstraint(
            "purpose <> 'ra_mat' OR (budget_cap_daily IS NOT NULL AND ends_on IS NOT NULL)",
            name=f"ck_{PURPOSES_TABLE}_launch_capped",
        ),
    )
    op.create_index(
        f"ix_{PURPOSES_TABLE}_latest",
        PURPOSES_TABLE,
        ["shop_id", "platform", "campaign_key", sa.text("set_at DESC")],
    )


def _secure_tenant(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant (111's shape)."""
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


def _secure_reference(table: str) -> None:
    """RLS on; ``juli_ops`` writes, ``juli_app`` reads (086's ``ops_system_settings`` shape)."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {table}_ops_all ON public.{table} FOR ALL TO {OPS_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {table}_app_select ON public.{table} FOR SELECT TO {APP_ROLE} USING (true)"
    )
    op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM anon';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM authenticated';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT ON public.{table} TO {APP_ROLE}';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OPS_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{table} TO {OPS_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def _revoke(table: str) -> None:
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


def upgrade() -> None:
    _create_snapshots()
    _create_assets()
    _create_lines()
    _create_formulas()
    _create_versions()
    _create_purposes()
    for table, verbs in TENANT_VERBS.items():
        _secure_tenant(table, verbs)
    _secure_reference(FORMULAS_TABLE)

    op.add_column(SEEDS_TABLE, sa.Column("role", sa.String(length=16), nullable=True))
    op.add_column(SEEDS_TABLE, sa.Column("item_scope", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        SEED_ROLE_CHECK, SEEDS_TABLE, f"role IS NULL OR role IN ({_in(SEED_ROLES)})"
    )

    op.drop_constraint(EVENT_TYPE_CHECK, EVENTS_TABLE, type_="check")
    op.create_check_constraint(
        EVENT_TYPE_CHECK, EVENTS_TABLE, f"event_type IN ({_in(EVENT_TYPES)})"
    )


def downgrade() -> None:
    op.drop_constraint(EVENT_TYPE_CHECK, EVENTS_TABLE, type_="check")
    op.execute(
        f"ALTER TABLE public.{EVENTS_TABLE} ADD CONSTRAINT {EVENT_TYPE_CHECK} "
        f"CHECK (event_type IN ({_in(EVENT_TYPES_095)})) NOT VALID"
    )  # nosec B608 - fixed module constants

    op.drop_constraint(SEED_ROLE_CHECK, SEEDS_TABLE, type_="check")
    op.drop_column(SEEDS_TABLE, "item_scope")
    op.drop_column(SEEDS_TABLE, "role")

    for table in (*reversed(tuple(TENANT_VERBS)), FORMULAS_TABLE):
        _revoke(table)
        op.drop_table(table)
