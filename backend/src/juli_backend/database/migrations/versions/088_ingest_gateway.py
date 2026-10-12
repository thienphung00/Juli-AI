"""Shopee shops, the ingest gateway and Juli Connector pairing (fast track P24).

Revision ID: 088_ingest_gateway
Revises: 087_history_and_baselines
Create Date: 2026-10-12

DECISIONS D31.3 (one ingest gateway, normalized form, source + confidence) and
D31.4 (Juli Connector extension, pairing instead of a password).

WHAT IT ADDS.

- ``shops.platform`` (``tiktok`` | ``shopee``, default ``tiktok`` so every
  existing row is unchanged) and ``shops.shopee_shop_id`` (nullable, unique).
  Two columns on ``shops`` rather than a link table: a Shopee shop is a Juli
  shop like any other (owner, tenancy, RLS, Ops), it just has no TikTok
  credential, and every existing reader keeps working untouched.
- ``app_current_pairing_code_hash()``: the GUC helper for the pairing redeem
  (NULL when unset or empty, like ``app_current_shop_id()``).
- Five tenant tables, each like 087's: RLS on, one policy per granted verb
  through ``app_current_shop_id()``; ``juli_app`` gets only the verbs the
  code needs.

  - ``ingest_pairing_codes``: SELECT, INSERT, UPDATE. Its SELECT policy also
    admits the single row whose ``code_hash = app_current_pairing_code_hash()``
    (the redeemer does not know the shop yet; a wrong code selects nothing).
  - ``ingest_tokens``: SELECT, INSERT, UPDATE (rotation, revocation, last use).
  - ``ingest_raw_payloads``: append-only, SELECT, INSERT; unique per
    ``(shop_id, content_hash)``.
  - ``platform_daily_metrics``: SELECT, INSERT, UPDATE (upserted).
  - ``ingest_dataset_status``: SELECT, INSERT, UPDATE.

EXPAND-ONLY AND REVERSIBLE. New columns (with a default), a function, tables,
policies and grants; no data change. ``downgrade`` drops them. The deferred
phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "088_ingest_gateway"
down_revision: str | None = "087_history_and_baselines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
CODES_TABLE = "ingest_pairing_codes"
TOKENS_TABLE = "ingest_tokens"
RAW_TABLE = "ingest_raw_payloads"
METRICS_TABLE = "platform_daily_metrics"
STATUS_TABLE = "ingest_dataset_status"
PAIRING_HELPER = "app_current_pairing_code_hash"
PAIRING_GUC = "app.pairing_code_hash"

APPEND_ONLY_VERBS = "SELECT, INSERT"
UPSERT_VERBS = "SELECT, INSERT, UPDATE"

#: table -> granted verbs. Every table here is tenant-direct.
GRANTS: dict[str, str] = {
    CODES_TABLE: UPSERT_VERBS,
    TOKENS_TABLE: UPSERT_VERBS,
    RAW_TABLE: APPEND_ONLY_VERBS,
    METRICS_TABLE: UPSERT_VERBS,
    STATUS_TABLE: UPSERT_VERBS,
}

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}

#: The pairing-code SELECT: the shop's own codes, or the one code being redeemed.
_PAIRING_SELECT = f"USING (shop_id = app_current_shop_id() OR code_hash = {PAIRING_HELPER}())"


def _shops_columns() -> None:
    op.add_column(
        "shops",
        sa.Column("platform", sa.String(length=16), server_default="tiktok", nullable=False),
    )
    op.add_column("shops", sa.Column("shopee_shop_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_shops_shopee_shop_id", "shops", ["shopee_shop_id"])
    op.create_check_constraint("ck_shops_platform", "shops", "platform IN ('tiktok', 'shopee')")


def _pairing_helper() -> None:
    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.{PAIRING_HELPER}() RETURNS text
      LANGUAGE sql
      STABLE
      SET search_path = pg_catalog, public
      AS $func$ SELECT nullif(current_setting('{PAIRING_GUC}', true), '') $func$;
    """)  # nosec B608 - fixed module constants


def _create_codes() -> None:
    op.create_table(
        CODES_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("token_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_pairing_codes"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ingest_pairing_codes_shop"),
        sa.UniqueConstraint("code_hash", name="uq_ingest_pairing_codes_hash"),
    )
    op.create_index("ix_ingest_pairing_codes_shop", CODES_TABLE, ["shop_id", "created_at"])


def _create_tokens() -> None:
    op.create_table(
        TOKENS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("platform_shop_id", sa.String(length=64), nullable=True),
        sa.Column("client_label", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_tokens"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ingest_tokens_shop"),
        sa.UniqueConstraint("token_hash", name="uq_ingest_tokens_hash"),
        sa.CheckConstraint("platform IN ('tiktok', 'shopee')", name="ck_ingest_tokens_platform"),
    )
    op.create_index("ix_ingest_tokens_shop", TOKENS_TABLE, ["shop_id", "created_at"])


def _create_raw() -> None:
    op.create_table(
        RAW_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_raw_payloads"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ingest_raw_payloads_shop"),
        sa.UniqueConstraint("shop_id", "content_hash", name="uq_ingest_raw_payloads_hash"),
    )
    op.create_index(
        "ix_ingest_raw_payloads_dataset",
        RAW_TABLE,
        ["shop_id", "platform", "dataset", "received_at"],
    )


def _create_metrics() -> None:
    op.create_table(
        METRICS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("item_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("stream", sa.String(length=24), nullable=False),
        sa.Column("platform_source", sa.String(length=64), nullable=True),
        sa.Column("segment", sa.String(length=16), server_default="all", nullable=False),
        sa.Column("order_type", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("impressions", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("clicks", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("ctr", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("orders", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("gmv", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("buyers", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("visitors", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("add_to_cart", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("units", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("page_views", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("bounce_rate", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_platform_daily_metrics"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_platform_daily_metrics_shop"),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"], [f"{RAW_TABLE}.id"], name="fk_platform_daily_metrics_raw"
        ),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "dataset",
            "day",
            "item_id",
            "stream",
            "segment",
            "order_type",
            name="uq_platform_daily_metrics_key",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'estimated')", name="ck_platform_daily_metrics_confidence"
        ),
    )
    op.create_index("ix_platform_daily_metrics_day", METRICS_TABLE, ["shop_id", "platform", "day"])
    op.create_index(
        "ix_platform_daily_metrics_item",
        METRICS_TABLE,
        ["shop_id", "platform", "item_id", "day"],
    )


def _create_status() -> None:
    op.create_table(
        STATUS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("dataset", sa.String(length=48), nullable=False),
        sa.Column("last_ingest_at", sa.DateTime(), nullable=True),
        sa.Column("last_captured_at", sa.DateTime(), nullable=True),
        sa.Column("last_period_start", sa.Date(), nullable=True),
        sa.Column("last_period_end", sa.Date(), nullable=True),
        sa.Column("last_row_count", sa.Integer(), nullable=True),
        sa.Column("last_source", sa.String(length=16), nullable=True),
        sa.Column("last_source_version", sa.String(length=64), nullable=True),
        sa.Column("last_raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column("drift_state", sa.String(length=8), server_default="ok", nullable=False),
        sa.Column("drift_detail", postgresql.JSONB(), nullable=True),
        sa.Column("drift_source_version", sa.String(length=64), nullable=True),
        sa.Column("drift_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_dataset_status"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_ingest_dataset_status_shop"),
        sa.UniqueConstraint("shop_id", "platform", "dataset", name="uq_ingest_dataset_status_key"),
        sa.CheckConstraint("drift_state IN ('ok', 'drift')", name="ck_ingest_dataset_status_drift"),
    )


def _secure(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    for verb in (v.strip() for v in verbs.split(",")):
        clause = _CLAUSES[verb]
        if table == CODES_TABLE and verb == "SELECT":
            clause = _PAIRING_SELECT
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {clause}"
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
    _shops_columns()
    _pairing_helper()
    _create_codes()
    _create_tokens()
    _create_raw()
    _create_metrics()
    _create_status()
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
    op.drop_table(STATUS_TABLE)
    op.drop_index("ix_platform_daily_metrics_item", table_name=METRICS_TABLE)
    op.drop_index("ix_platform_daily_metrics_day", table_name=METRICS_TABLE)
    op.drop_table(METRICS_TABLE)
    op.drop_index("ix_ingest_raw_payloads_dataset", table_name=RAW_TABLE)
    op.drop_table(RAW_TABLE)
    op.drop_index("ix_ingest_tokens_shop", table_name=TOKENS_TABLE)
    op.drop_table(TOKENS_TABLE)
    op.drop_index("ix_ingest_pairing_codes_shop", table_name=CODES_TABLE)
    op.drop_table(CODES_TABLE)
    op.execute(f"DROP FUNCTION IF EXISTS public.{PAIRING_HELPER}()")
    op.drop_constraint("ck_shops_platform", "shops", type_="check")
    op.drop_constraint("uq_shops_shopee_shop_id", "shops", type_="unique")
    op.drop_column("shops", "shopee_shop_id")
    op.drop_column("shops", "platform")
