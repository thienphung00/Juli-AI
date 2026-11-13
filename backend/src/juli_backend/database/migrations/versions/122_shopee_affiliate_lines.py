"""Shopee affiliate order lines, stored on their own (P96, owner 2026-11-06)

Revision ID: 122_shopee_affiliate_lines
Revises: 121_shop_members
Create Date: 2026-11-06

Phân tích › KOL must fill from the Juli Connector's affiliate conversion report alone. Until now an
``affiliate_order_lines`` row only MARKED the matching ``shopee_order_lines`` row of the order export,
so an affiliate order the export does not hold yet (ORY's export ended 04/11) was dropped.

CREATED, CLIENT LANE, tenant-direct (RLS by ``app_current_shop_id()``), UPSERT (``juli_app``
SELECT, INSERT, UPDATE -- a later conversion report moves a line's status, refund and commission):

- ``shopee_affiliate_lines`` -- one row per affiliate order line: the keyed ``order_ref`` (the same
  hash as ``shopee_order_lines``, so the two join), ``line_no`` (place among the report's lines of one
  order, item and model), ``item_id`` / ``model_id``, price, qty, order value, refund, the seller's
  commission, the fraud check (``valid``), the order status and times, and the KOL columns of 118
  (hashed key + PUBLIC handle, channel, campaign type, MCN flag). No buyer data.

It carries ``shop_id`` (uuid), so the account purge (094) finds it by column. The Postgres proof
(RLS, grants, up / down) is ``tests/integration/test_shopee_affiliate_lines_db.py``.

EXPAND-ONLY AND REVERSIBLE. One table, two indexes, policies and grants; no data change.
``downgrade`` drops the table (the stored lines are lost; the order-export lines keep their marks).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "122_shopee_affiliate_lines"
down_revision: str | None = "121_shop_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "shopee_affiliate_lines"

#: Written out, not imported from the models: a migration must not change when the model does.
PLATFORMS = ("tiktok", "shopee")

UPSERT_VERBS = "SELECT, INSERT, UPDATE"
_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}
#: Tenant table -> its ``juli_app`` verbs.
TENANT_VERBS: dict[str, str] = {TABLE: UPSERT_VERBS}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _create_lines() -> None:
    money = sa.Numeric(precision=18, scale=2)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("order_ref", sa.String(length=128), nullable=False),
        sa.Column("line_no", sa.SmallInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=32), server_default="", nullable=False),
        sa.Column("price", money, nullable=True),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("order_value", money, nullable=True),
        sa.Column("refund_amount", money, nullable=True),
        sa.Column("commission", money, nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=True),
        sa.Column("order_status", sa.String(length=64), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("conversion_at", sa.DateTime(), nullable=True),
        sa.Column("kol_key", sa.String(length=16), nullable=True),
        sa.Column("kol_handle", sa.String(length=120), nullable=True),
        sa.Column("affiliate_channel", sa.String(length=64), nullable=True),
        sa.Column("affiliate_campaign_type", sa.String(length=64), nullable=True),
        sa.Column("affiliate_mcn", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.UniqueConstraint(
            "shop_id",
            "platform",
            "order_ref",
            "line_no",
            "item_id",
            "model_id",
            name=f"uq_{TABLE}_line",
        ),
        sa.CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name=f"ck_{TABLE}_platform"),
    )
    op.create_index(f"ix_{TABLE}_time", TABLE, ["shop_id", "platform", "ordered_at"])
    op.create_index(
        f"ix_{TABLE}_kol",
        TABLE,
        ["shop_id", "kol_key", "ordered_at"],
        postgresql_where=sa.text("kol_key IS NOT NULL"),
    )


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
    _create_lines()
    for table, verbs in TENANT_VERBS.items():
        _secure_tenant(table, verbs)


def downgrade() -> None:
    for table in reversed(tuple(TENANT_VERBS)):
        _revoke(table)
        op.drop_index(f"ix_{table}_kol", table_name=table)
        op.drop_index(f"ix_{table}_time", table_name=table)
        op.drop_table(table)
