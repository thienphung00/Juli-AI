"""bronze append tables for ctor (A-34) / live_hours (A-28) raw payloads (#880)

Revision ID: 029_bronze_ctor_live_hours
Revises: 028_demo_execution_records
Create Date: 2026-08-10

Additive-only, same shape as 023_bronze_orders_returns (ADR-046 Bronze MVP scope):

- ``bronze.ctor_performance_raw_payloads`` — A-34 Get Shop Product Performance
  List rows (product-grain), forward write path for the ``ctor`` Demo Main KPI
  (CTOR = click -> order rate).
- ``bronze.live_hours_raw_payloads`` — A-28 Get Shop LIVE Performance List rows
  (per-session grain plus the derived shop-grain daily rollup), forward write
  path for the ``live_hours`` Demo Main KPI.

Both tables are brand-new, so no NOT NULL column constrains a pre-existing row
(same precedent as 023/024/025/026/027/028). No drops, no destructive alters —
only ``create_table`` / ``create_index`` and client-role grant revocation,
identical in shape to 023's ``_revoke_client_table`` helper.

Forward write path only: these tables are appended to exclusively by
``juli_backend.services.etl.bronze_append`` (mirrors 023's orders/returns
writer boundary) — never by ``public.webhook_raw_events`` (still the
read-only audit shim) and never by a second, parallel writer.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "029_bronze_ctor_live_hours"
down_revision: str | None = "028_demo_execution_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
BRONZE_TABLES: tuple[str, ...] = (
    "bronze.ctor_performance_raw_payloads",
    "bronze.live_hours_raw_payloads",
)


def _revoke_client_table(table: str) -> None:
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $bronze$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    REVOKE ALL ON TABLE {table} FROM {role};
  END IF;
END
$bronze$;
"""  # nosec B608 — table/role are fixed module constants
        op.execute(sql)


def _payload_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ingest_source", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "ctor_performance_raw_payloads",
        *_payload_columns(),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="bronze",
    )
    op.create_index(
        "ix_bronze_ctor_performance_raw_payloads_shop_received",
        "ctor_performance_raw_payloads",
        ["shop_id", "received_at"],
        schema="bronze",
    )

    op.create_table(
        "live_hours_raw_payloads",
        *_payload_columns(),
        sa.Column("tiktok_live_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="bronze",
    )
    op.create_index(
        "ix_bronze_live_hours_raw_payloads_shop_received",
        "live_hours_raw_payloads",
        ["shop_id", "received_at"],
        schema="bronze",
    )

    for table in BRONZE_TABLES:
        _revoke_client_table(table)


def downgrade() -> None:
    op.drop_index(
        "ix_bronze_live_hours_raw_payloads_shop_received",
        table_name="live_hours_raw_payloads",
        schema="bronze",
    )
    op.drop_table("live_hours_raw_payloads", schema="bronze")
    op.drop_index(
        "ix_bronze_ctor_performance_raw_payloads_shop_received",
        table_name="ctor_performance_raw_payloads",
        schema="bronze",
    )
    op.drop_table("ctor_performance_raw_payloads", schema="bronze")
