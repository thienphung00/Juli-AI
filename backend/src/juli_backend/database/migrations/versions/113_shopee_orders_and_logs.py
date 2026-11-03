"""Shopee order export columns, shop health and the ad change log (P90 step 2)

Revision ID: 113_shopee_orders_and_logs
Revises: 112_shopee_profit_and_history
Create Date: 2026-11-03

P90 step 2 (G-03, G-04, G-17): the order export (Đơn hàng › Xuất) becomes ``shopee_order_lines``
rows; two reserved datasets get their tables.

ALTERED, ``shopee_order_lines`` (tenant-direct; policies and grants from 112 are unchanged):

- ``buyer_shipping_fee`` and ``bank_promo`` (the phí xử lý giao dịch base, metrics §10) --
  order-level amounts, split across the order's lines by line value; NULL = not in the source.
- ``ad_attributed`` -- nullable: no export marks an order as ad-attributed (G-04), so NULL
  means "unknown", never False.
- ``seller_subsidy`` / ``shopee_subsidy`` -- who funded the line's promotion (a Shopee subsidy
  is not a seller cost); ``returned_qty``; ``completed_at`` and ``paid_at``.
- ``sku`` / ``variation_sku`` -- the export names a product by SKU only; the gateway fills
  ``item_id`` from the catalogue when it knows the SKU.

CREATED, CLIENT LANE, tenant-direct (RLS by ``app_current_shop_id()``), APPEND-ONLY
(``juli_app`` SELECT, INSERT only: a reading or a log line is never edited):

- ``shop_health_daily`` -- Seller Centre account-health metrics, one row per metric per
  capture (the Connector's ``shop_health_daily`` dataset); ``metric_id`` is ``''`` on the day's
  overview row.
- ``ads_change_log`` -- the ad campaigns' change history (``ops_log_*``).

Both carry ``shop_id`` (uuid), so the account purge (094) finds them by column; the integration
test pins that.

EXPAND-ONLY AND REVERSIBLE. Nullable or defaulted columns, two tables, indexes, policies and
grants; no data change. ``downgrade`` drops the tables and the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "113_shopee_orders_and_logs"
down_revision: str | None = "112_shopee_profit_and_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
LINES_TABLE = "shopee_order_lines"
HEALTH_TABLE = "shop_health_daily"
LOG_TABLE = "ads_change_log"

#: Written out, not imported from the models: a migration must not change when the model does.
PLATFORMS = ("tiktok", "shopee")
ACTOR_KINDS = ("system", "user")

APPEND_ONLY_VERBS = "SELECT, INSERT"
_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
}
#: Tenant table -> its ``juli_app`` verbs.
TENANT_VERBS: dict[str, str] = {HEALTH_TABLE: APPEND_ONLY_VERBS, LOG_TABLE: APPEND_ONLY_VERBS}

#: Columns added to ``shopee_order_lines`` (downgrade drops them in reverse).
LINE_COLUMNS: tuple[str, ...] = (
    "buyer_shipping_fee",
    "bank_promo",
    "ad_attributed",
    "seller_subsidy",
    "shopee_subsidy",
    "returned_qty",
    "completed_at",
    "paid_at",
    "sku",
    "variation_sku",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _shop_column() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False)


def _add_line_columns() -> None:
    money = sa.Numeric(precision=18, scale=2)
    op.add_column(LINES_TABLE, sa.Column("buyer_shipping_fee", money, nullable=True))
    op.add_column(LINES_TABLE, sa.Column("bank_promo", money, nullable=True))
    op.add_column(LINES_TABLE, sa.Column("ad_attributed", sa.Boolean(), nullable=True))
    op.add_column(
        LINES_TABLE, sa.Column("seller_subsidy", money, server_default="0", nullable=False)
    )
    op.add_column(
        LINES_TABLE, sa.Column("shopee_subsidy", money, server_default="0", nullable=False)
    )
    op.add_column(
        LINES_TABLE, sa.Column("returned_qty", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(LINES_TABLE, sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.add_column(LINES_TABLE, sa.Column("paid_at", sa.DateTime(), nullable=True))
    op.add_column(LINES_TABLE, sa.Column("sku", sa.String(length=128), nullable=True))
    op.add_column(LINES_TABLE, sa.Column("variation_sku", sa.String(length=128), nullable=True))


def _create_health() -> None:
    op.create_table(
        HEALTH_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metric_id", sa.String(length=32), server_default="", nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("display_value", sa.String(length=64), nullable=True),
        sa.Column("value", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("target_display", sa.String(length=64), nullable=True),
        sa.Column("target", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("compare_result", sa.String(length=64), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("metric_tag", sa.String(length=64), nullable=True),
        sa.Column("failed_metric_count", sa.Integer(), nullable=True),
        sa.Column("penalty_point", sa.Integer(), nullable=True),
        sa.Column("performance_rating", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{HEALTH_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "platform", "day", "metric_id", "captured_at", name=f"uq_{HEALTH_TABLE}_key"
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{HEALTH_TABLE}_platform"),
    )
    op.create_index(f"ix_{HEALTH_TABLE}_day", HEALTH_TABLE, ["shop_id", "platform", "day"])


def _create_log() -> None:
    op.create_table(
        LOG_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop_column(),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("campaign_id", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("actor_kind", sa.String(length=8), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("surface", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("budget_from", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("budget_to", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("products_from", sa.Integer(), nullable=True),
        sa.Column("products_to", sa.Integer(), nullable=True),
        sa.Column("ordinal", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{LOG_TABLE}"),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "campaign_id",
            "item_id",
            "occurred_at",
            "event_type",
            "ordinal",
            name=f"uq_{LOG_TABLE}_key",
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{LOG_TABLE}_platform"),
        sa.CheckConstraint(
            f"actor_kind IN ({_in(ACTOR_KINDS)})", name=f"ck_{LOG_TABLE}_actor_kind"
        ),
    )
    op.create_index(f"ix_{LOG_TABLE}_time", LOG_TABLE, ["shop_id", "platform", "occurred_at"])


def _secure_tenant(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant (112's shape)."""
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


def _revoke(table: str) -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def upgrade() -> None:
    _add_line_columns()
    _create_health()
    _create_log()
    for table, verbs in TENANT_VERBS.items():
        _secure_tenant(table, verbs)


def downgrade() -> None:
    for table in reversed(tuple(TENANT_VERBS)):
        _revoke(table)
        op.drop_table(table)
    for column in reversed(LINE_COLUMNS):
        op.drop_column(LINES_TABLE, column)
