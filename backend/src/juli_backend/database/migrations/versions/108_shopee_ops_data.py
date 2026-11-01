"""Shopee Seller Centre files, contract KPIs and the public market lane (ADR-117).

Revision ID: 108_shopee_ops_data
Revises: 107_ops_pooled_consent
Create Date: 2026-11-01

ADR-117 (owner grill G1-G11, 2026-10-30): the Juli Ops Shopee dashboards. Files the
seller exports from Seller Centre go through the ingest gateway on the same keys the
Shopee API will use; contract KPIs, lever plans and forecasts are Ops-only; public
search pages are the public lane (ADR-116 §1).

WHAT IT ADDS.

- ``platform_daily_metrics.mapper_version`` (SMALLINT NULL): the server mapping version
  that produced the row (ADR-112's known-at). NULL = written before ADR-117.
- Four CLIENT-LANE tables, tenant-direct like 088's (RLS on, one policy per granted verb
  through ``app_current_shop_id()``; ``juli_app`` SELECT, INSERT, UPDATE):

  - ``platform_period_metrics`` -- totals over a period (one day .. one month) per item x
    variation x stream x segment x order type (``parentskudetail``, monthly source files).
    A period is never written as a fake day in ``platform_daily_metrics`` (ADR-117 §2).
  - ``platform_items`` -- the platform's items and variations (name, SKU, status).
    ``products`` stays TikTok-shaped (``tiktok_product_id`` NOT NULL).
  - ``platform_product_flags`` -- Shopee's per-item flags for a period (new product,
    price (un)competitive, ads grow / optimize / track).
  - ``platform_promotions`` -- one row per promotion program x export period x order
    type. Shopee exports no program id and two programs can share a name and run
    times, so ``ordinal`` (the row's place among such twins in one export) is in the key.

- Six OPS-ONLY tables (like 083 / 107: RLS on, the only policy ``FOR ALL TO juli_ops``,
  nothing for ``juli_app`` / ``anon`` / ``authenticated``): ``kpi_contracts`` (one row
  per contract version), ``kpi_targets``, ``kpi_adjustments``, ``kpi_exclusions``,
  ``lever_plans``, ``kpi_forecasts``. Contract terms and forecasts are never shown to a
  seller (disclosure rule, D42 G4). Append-only tables get SELECT, INSERT only;
  offboarding deletes as the migration role (ADR-117 §4).
- Two PUBLIC-LANE tables, no ``shop_id`` (ADR-116 §1), Ops-only until a seller reader
  exists: ``market_listing_snapshots`` (one row per search card seen) and
  ``market_keyword_snapshots`` (one row per keyword x sort x collection day). The
  platform's shop id is ``platform_shop_id`` so the tenant sweep never reads it as
  Juli's ``shop_id``.

EXPAND-ONLY AND REVERSIBLE. One nullable column, tables, indexes, policies and grants;
no data change. ``downgrade`` drops them. The deferred write-mode backfill (and the phone
cleanup under it) is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "108_shopee_ops_data"
down_revision: str | None = "107_ops_pooled_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
OPS_ROLE = "juli_ops"
DAILY_TABLE = "platform_daily_metrics"
RAW_TABLE = "ingest_raw_payloads"

PERIOD_TABLE = "platform_period_metrics"
ITEMS_TABLE = "platform_items"
FLAGS_TABLE = "platform_product_flags"
PROMOTIONS_TABLE = "platform_promotions"

CONTRACTS_TABLE = "kpi_contracts"
TARGETS_TABLE = "kpi_targets"
ADJUSTMENTS_TABLE = "kpi_adjustments"
EXCLUSIONS_TABLE = "kpi_exclusions"
LEVERS_TABLE = "lever_plans"
FORECASTS_TABLE = "kpi_forecasts"

LISTINGS_TABLE = "market_listing_snapshots"
KEYWORDS_TABLE = "market_keyword_snapshots"

#: Written out rather than imported from the models: a migration must not change when
#: the model does. ``tests/unit/test_shopee_ops_data_schema.py`` pins them equal.
PLATFORMS = ("tiktok", "shopee")
ORDER_TYPES = ("none", "placed", "paid", "confirmed")
FLAGS = (
    "new_product",
    "price_competitive",
    "price_uncompetitive",
    "ads_grow",
    "ads_optimize",
    "ads_track",
)
CONTRACT_STATUSES = ("draft", "sent", "signed", "superseded")
TARGET_ROLES = ("kpi", "tracking")

UPSERT_VERBS = "SELECT, INSERT, UPDATE"
APPEND_ONLY_VERBS = "SELECT, INSERT"
EDITABLE_VERBS = "SELECT, INSERT, UPDATE, DELETE"

#: Client-lane table -> ``juli_app`` verbs. Every table here is tenant-direct.
TENANT_GRANTS: dict[str, str] = {
    PERIOD_TABLE: UPSERT_VERBS,
    ITEMS_TABLE: UPSERT_VERBS,
    FLAGS_TABLE: UPSERT_VERBS,
    PROMOTIONS_TABLE: UPSERT_VERBS,
}
#: Ops-only table -> ``juli_ops`` verbs; ``juli_app`` gets nothing.
OPS_GRANTS: dict[str, str] = {
    CONTRACTS_TABLE: UPSERT_VERBS,
    TARGETS_TABLE: APPEND_ONLY_VERBS,
    ADJUSTMENTS_TABLE: APPEND_ONLY_VERBS,
    EXCLUSIONS_TABLE: APPEND_ONLY_VERBS,
    LEVERS_TABLE: EDITABLE_VERBS,
    FORECASTS_TABLE: APPEND_ONLY_VERBS,
    LISTINGS_TABLE: UPSERT_VERBS,
    KEYWORDS_TABLE: UPSERT_VERBS,
}

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _metric_columns() -> list[sa.Column]:
    """088's KPI columns, so a period row reads like a daily one."""
    count = sa.Numeric(precision=20, scale=4)
    rate = sa.Numeric(precision=12, scale=8)
    return [
        sa.Column("impressions", count, nullable=True),
        sa.Column("clicks", count, nullable=True),
        sa.Column("ctr", rate, nullable=True),
        sa.Column("orders", count, nullable=True),
        sa.Column("gmv", count, nullable=True),
        sa.Column("buyers", count, nullable=True),
        sa.Column("visitors", count, nullable=True),
        sa.Column("add_to_cart", count, nullable=True),
        sa.Column("units", count, nullable=True),
        sa.Column("page_views", count, nullable=True),
        sa.Column("bounce_rate", rate, nullable=True),
    ]


def _source_columns(table: str) -> list[sa.Column | sa.Constraint]:
    """Where a client-lane row came from: 088's source fields plus ``mapper_version``."""
    return [
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("mapper_version", sa.SmallInteger(), nullable=True),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{table}_shop"),
        sa.ForeignKeyConstraint(["raw_payload_id"], [f"{RAW_TABLE}.id"], name=f"fk_{table}_raw"),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{table}_platform"),
    ]


def _create_period() -> None:
    op.create_table(
        PERIOD_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("item_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("variation_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("stream", sa.String(length=24), nullable=False),
        sa.Column("platform_source", sa.String(length=64), nullable=True),
        sa.Column("segment", sa.String(length=16), server_default="all", nullable=False),
        sa.Column("order_type", sa.String(length=16), server_default="none", nullable=False),
        *_metric_columns(),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        *_source_columns(PERIOD_TABLE),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PERIOD_TABLE}"),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "dataset",
            "period_start",
            "period_end",
            "item_id",
            "variation_id",
            "stream",
            "segment",
            "order_type",
            name=f"uq_{PERIOD_TABLE}_key",
        ),
        sa.CheckConstraint("period_end >= period_start", name=f"ck_{PERIOD_TABLE}_period"),
        sa.CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})", name=f"ck_{PERIOD_TABLE}_order_type"
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'estimated')", name=f"ck_{PERIOD_TABLE}_confidence"
        ),
    )
    op.create_index(
        f"ix_{PERIOD_TABLE}_item", PERIOD_TABLE, ["shop_id", "platform", "item_id", "period_start"]
    )


def _create_items() -> None:
    op.create_table(
        ITEMS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("variation_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("variation_name", sa.String(length=255), nullable=True),
        sa.Column("seller_sku", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("first_seen_on", sa.Date(), nullable=True),
        sa.Column("last_seen_on", sa.Date(), nullable=True),
        *_source_columns(ITEMS_TABLE),
        sa.PrimaryKeyConstraint("id", name=f"pk_{ITEMS_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "platform", "item_id", "variation_id", name=f"uq_{ITEMS_TABLE}_key"
        ),
    )


def _create_flags() -> None:
    op.create_table(
        FLAGS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("flag", sa.String(length=32), nullable=False),
        *_source_columns(FLAGS_TABLE),
        sa.PrimaryKeyConstraint("id", name=f"pk_{FLAGS_TABLE}"),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "item_id",
            "period_start",
            "period_end",
            "flag",
            name=f"uq_{FLAGS_TABLE}_key",
        ),
        sa.CheckConstraint(f"flag IN ({_in(FLAGS)})", name=f"ck_{FLAGS_TABLE}_flag"),
        sa.CheckConstraint("period_end >= period_start", name=f"ck_{FLAGS_TABLE}_period"),
    )


def _create_promotions() -> None:
    count = sa.Numeric(precision=20, scale=4)
    op.create_table(
        PROMOTIONS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("promo_type", sa.String(length=32), nullable=False),
        sa.Column("program_name", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("ordinal", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("gmv", count, nullable=True),
        sa.Column("orders", count, nullable=True),
        sa.Column("units", count, nullable=True),
        sa.Column("buyers", count, nullable=True),
        *_source_columns(PROMOTIONS_TABLE),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PROMOTIONS_TABLE}"),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "promo_type",
            "program_name",
            "starts_at",
            "ordinal",
            "period_start",
            "period_end",
            "order_type",
            name=f"uq_{PROMOTIONS_TABLE}_key",
        ),
        sa.CheckConstraint(
            f"order_type IN ({_in(ORDER_TYPES)})", name=f"ck_{PROMOTIONS_TABLE}_order_type"
        ),
        sa.CheckConstraint("period_end >= period_start", name=f"ck_{PROMOTIONS_TABLE}_period"),
    )
    op.create_index(
        f"ix_{PROMOTIONS_TABLE}_dates", PROMOTIONS_TABLE, ["shop_id", "platform", "period_start"]
    )


def _create_contracts() -> None:
    op.create_table(
        CONTRACTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("contract_ref", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sent_on", sa.Date(), nullable=True),
        sa.Column("signed_on", sa.Date(), nullable=True),
        sa.Column("measure_start", sa.Date(), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("email_ref", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{CONTRACTS_TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{CONTRACTS_TABLE}_shop"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["ops_staff.id"], name=f"fk_{CONTRACTS_TABLE}_created_by"
        ),
        sa.UniqueConstraint("shop_id", "contract_ref", "version", name=f"uq_{CONTRACTS_TABLE}_ver"),
        sa.CheckConstraint(
            f"status IN ({_in(CONTRACT_STATUSES)})", name=f"ck_{CONTRACTS_TABLE}_status"
        ),
        sa.CheckConstraint("version >= 1", name=f"ck_{CONTRACTS_TABLE}_version"),
    )


def _create_contract_children() -> None:
    num = sa.Numeric(precision=20, scale=6)
    op.create_table(
        TARGETS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("baseline", num, nullable=True),
        sa.Column("d_pct", num, nullable=True),
        sa.Column("pass_level", num, nullable=True),
        sa.Column("target_level", num, nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TARGETS_TABLE}"),
        sa.ForeignKeyConstraint(
            ["contract_id"], [f"{CONTRACTS_TABLE}.id"], name=f"fk_{TARGETS_TABLE}_contract"
        ),
        sa.UniqueConstraint("contract_id", "flow", "metric", name=f"uq_{TARGETS_TABLE}_key"),
        sa.CheckConstraint(f"role IN ({_in(TARGET_ROLES)})", name=f"ck_{TARGETS_TABLE}_role"),
    )
    op.create_table(
        ADJUSTMENTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", num, nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("email_ref", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{ADJUSTMENTS_TABLE}"),
        sa.ForeignKeyConstraint(
            ["contract_id"], [f"{CONTRACTS_TABLE}.id"], name=f"fk_{ADJUSTMENTS_TABLE}_contract"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["ops_staff.id"], name=f"fk_{ADJUSTMENTS_TABLE}_created_by"
        ),
    )
    op.create_index(f"ix_{ADJUSTMENTS_TABLE}_contract", ADJUSTMENTS_TABLE, ["contract_id"])
    op.create_table(
        EXCLUSIONS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{EXCLUSIONS_TABLE}"),
        sa.ForeignKeyConstraint(
            ["contract_id"], [f"{CONTRACTS_TABLE}.id"], name=f"fk_{EXCLUSIONS_TABLE}_contract"
        ),
        sa.UniqueConstraint("contract_id", "day", name=f"uq_{EXCLUSIONS_TABLE}_day"),
    )


def _create_levers_and_forecasts() -> None:
    num = sa.Numeric(precision=20, scale=6)
    op.create_table(
        LEVERS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=True),
        sa.Column("lever_key", sa.String(length=32), nullable=False),
        sa.Column("wave", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("lag_days", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("low", num, nullable=False),
        sa.Column("high", num, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{LEVERS_TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{LEVERS_TABLE}_shop"),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["ops_sim_scenarios.id"], name=f"fk_{LEVERS_TABLE}_scenario"
        ),
        sa.CheckConstraint("high >= low", name=f"ck_{LEVERS_TABLE}_range"),
        sa.CheckConstraint("lag_days >= 0", name=f"ck_{LEVERS_TABLE}_lag"),
    )
    op.create_index(f"ix_{LEVERS_TABLE}_shop", LEVERS_TABLE, ["shop_id", "scenario_id"])
    op.create_table(
        FORECASTS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("scenario_id", sa.Uuid(), nullable=True),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("milestone", sa.SmallInteger(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("expected", num, nullable=True),
        sa.Column("lo90", num, nullable=True),
        sa.Column("hi90", num, nullable=True),
        sa.Column("p_pass", num, nullable=True),
        sa.Column("trend_weight", num, nullable=True),
        sa.Column("inputs_sha256", sa.String(length=64), nullable=False),
        sa.Column("method_version", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{FORECASTS_TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{FORECASTS_TABLE}_shop"),
        sa.ForeignKeyConstraint(
            ["contract_id"], [f"{CONTRACTS_TABLE}.id"], name=f"fk_{FORECASTS_TABLE}_contract"
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["ops_sim_scenarios.id"], name=f"fk_{FORECASTS_TABLE}_scenario"
        ),
        sa.CheckConstraint(
            "p_pass IS NULL OR (p_pass >= 0 AND p_pass <= 1)", name=f"ck_{FORECASTS_TABLE}_p"
        ),
        sa.CheckConstraint("length(inputs_sha256) = 64", name=f"ck_{FORECASTS_TABLE}_sha256"),
    )
    op.create_index(f"ix_{FORECASTS_TABLE}_run", FORECASTS_TABLE, ["shop_id", "run_at"])


def _create_market() -> None:
    money = sa.Numeric(precision=20, scale=4)
    op.create_table(
        LISTINGS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("sort", sa.String(length=16), nullable=False),
        sa.Column("page", sa.SmallInteger(), nullable=False),
        sa.Column("pos", sa.SmallInteger(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("platform_item_id", sa.String(length=32), nullable=False),
        sa.Column("platform_shop_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("price", money, nullable=True),
        sa.Column("discount_pct", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("sold_text", sa.String(length=120), nullable=True),
        sa.Column("sold_monthly", money, nullable=True),
        sa.Column("sold_lifetime", money, nullable=True),
        sa.Column("collector", sa.String(length=64), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{LISTINGS_TABLE}"),
        sa.UniqueConstraint(
            "platform",
            "keyword",
            "sort",
            "page",
            "pos",
            "collected_at",
            name=f"uq_{LISTINGS_TABLE}_card",
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{LISTINGS_TABLE}_platform"),
    )
    op.create_index(
        f"ix_{LISTINGS_TABLE}_item",
        LISTINGS_TABLE,
        ["platform", "platform_item_id", "collected_at"],
    )
    op.create_index(
        f"ix_{LISTINGS_TABLE}_shop",
        LISTINGS_TABLE,
        ["platform", "platform_shop_id", "collected_at"],
    )
    op.create_table(
        KEYWORDS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("sort", sa.String(length=16), nullable=False),
        sa.Column("collected_on", sa.Date(), nullable=False),
        sa.Column("pages", sa.SmallInteger(), nullable=False),
        sa.Column("n_cards", sa.Integer(), nullable=False),
        sa.Column("n_shops", sa.Integer(), nullable=False),
        sa.Column("median_price_page1", money, nullable=True),
        sa.Column("share_discounted", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("sold_monthly_median", money, nullable=True),
        sa.Column("sold_monthly_p75", money, nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{KEYWORDS_TABLE}"),
        sa.UniqueConstraint(
            "platform", "keyword", "sort", "collected_on", name=f"uq_{KEYWORDS_TABLE}_key"
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{KEYWORDS_TABLE}_platform"),
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
    """RLS on, the only policy ``TO juli_ops``, nothing for any other role (107's shape)."""
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
    op.add_column(DAILY_TABLE, sa.Column("mapper_version", sa.SmallInteger(), nullable=True))
    _create_period()
    _create_items()
    _create_flags()
    _create_promotions()
    _create_contracts()
    _create_contract_children()
    _create_levers_and_forecasts()
    _create_market()
    for table, verbs in TENANT_GRANTS.items():
        _secure_tenant(table, verbs)
    for table, verbs in OPS_GRANTS.items():
        _secure_ops(table, verbs)


def downgrade() -> None:
    for table in (*TENANT_GRANTS, *OPS_GRANTS):
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
    # Children before parents.
    for table in (
        KEYWORDS_TABLE,
        LISTINGS_TABLE,
        FORECASTS_TABLE,
        LEVERS_TABLE,
        EXCLUSIONS_TABLE,
        ADJUSTMENTS_TABLE,
        TARGETS_TABLE,
        CONTRACTS_TABLE,
        PROMOTIONS_TABLE,
        FLAGS_TABLE,
        ITEMS_TABLE,
        PERIOD_TABLE,
    ):
        op.drop_table(table)
    op.drop_column(DAILY_TABLE, "mapper_version")
