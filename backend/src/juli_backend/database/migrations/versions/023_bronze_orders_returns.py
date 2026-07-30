"""bronze append tables for orders/returns raw payloads (#605)

Revision ID: 023_bronze_orders_returns
Revises: 021_medallion_schemas
Create Date: 2026-07-30

Parallel tip: down_revision points at 021_medallion_schemas while #604 lands
022_ops_backfill_partitions. Meta rebases to 022 when opening the sequential PR.

webhook_raw_events fate (Architect lock — option 2 from A0 PRD):
- ``public.webhook_raw_events`` remains a **read-only audit shim** for HTTP
  delivery audit (redacted headers/body on every webhook exit path).
- **Forward write path** for orders/returns domain raw payloads is
  ``bronze.order_raw_payloads`` and ``bronze.return_raw_payloads`` only.
- **No indefinite double-write:** new bronze ingest writers must not also append
  domain payloads to ``public.webhook_raw_events``. Existing webhook audit
  recorder may continue for HTTP audit until A1 cutover retires it; silver
  promotion reads bronze only (wired in A1 / #607).
- A1 webhook enqueue and targeted-fetch orchestration are out of scope here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023_bronze_orders_returns"
down_revision: str | None = "022_ops_backfill_partitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
BRONZE_TABLES: tuple[str, ...] = (
    "bronze.order_raw_payloads",
    "bronze.return_raw_payloads",
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
        "order_raw_payloads",
        *_payload_columns(),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="bronze",
    )
    op.create_index(
        "ix_bronze_order_raw_payloads_shop_received",
        "order_raw_payloads",
        ["shop_id", "received_at"],
        schema="bronze",
    )

    op.create_table(
        "return_raw_payloads",
        *_payload_columns(),
        sa.Column("tiktok_return_id", sa.String(length=100), nullable=True),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="bronze",
    )
    op.create_index(
        "ix_bronze_return_raw_payloads_shop_received",
        "return_raw_payloads",
        ["shop_id", "received_at"],
        schema="bronze",
    )

    for table in BRONZE_TABLES:
        _revoke_client_table(table)


def downgrade() -> None:
    op.drop_index(
        "ix_bronze_return_raw_payloads_shop_received",
        table_name="return_raw_payloads",
        schema="bronze",
    )
    op.drop_table("return_raw_payloads", schema="bronze")
    op.drop_index(
        "ix_bronze_order_raw_payloads_shop_received",
        table_name="order_raw_payloads",
        schema="bronze",
    )
    op.drop_table("order_raw_payloads", schema="bronze")
