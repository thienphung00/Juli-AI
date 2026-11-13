"""Juli Connector heartbeat and the one command Juli can give it (P100 Thực hiện)

Revision ID: 128_connector_state
Revises: 127_card_content_specs
Create Date: 2026-11-13

Two tenant-direct tables (RLS by ``app_current_shop_id()``; SELECT / INSERT / UPDATE for
``juli_app``): ``shopee_connector_state`` (one row per shop: whether a Seller Centre tab was open at
the Connector's last poll, when, and its version) and ``shopee_connector_commands`` ("Đối chiếu
ngay": ``pending`` -> ``sent`` -> ``acked``; at most one open command per shop and type).

EXPAND-ONLY AND REVERSIBLE: new tables, indexes, policies and grants; no row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "128_connector_state"
down_revision: str | None = "127_card_content_specs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
STATE = "shopee_connector_state"
COMMANDS = "shopee_connector_commands"
TENANT_TABLES = (STATE, COMMANDS)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def upgrade() -> None:
    op.create_table(
        STATE,
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("seller_centre_open", sa.Boolean(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("connector_version", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name=f"pk_{STATE}"),
    )
    op.create_table(
        COMMANDS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{COMMANDS}"),
        sa.CheckConstraint("type IN ('reconcile')", name="ck_shopee_connector_commands_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'acked')", name="ck_shopee_connector_commands_status"
        ),
    )
    op.create_index(
        "uq_shopee_connector_commands_open",
        COMMANDS,
        ["shop_id", "type"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'sent')"),
    )
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
    for table in TENANT_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_index("uq_shopee_connector_commands_open", table_name=COMMANDS)
    op.drop_table(COMMANDS)
    op.drop_table(STATE)
