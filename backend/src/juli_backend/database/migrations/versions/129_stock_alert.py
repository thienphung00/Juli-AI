"""Stock alert: per-variation stock history, the "Theo dõi" switch, unsubscribes, send log (Part S)

Revision ID: 129_stock_alert
Revises: 128_connector_state
Create Date: 2026-11-14

Four tenant-direct tables (RLS by ``app_current_shop_id()``):

- ``shopee_stock_history`` -- one row per variation per Connector read (``item_snapshot``):
  ``sellable`` / ``available`` stock and the listing status. ``juli_app``: SELECT, INSERT.
- ``shopee_sku_tracking`` -- the per-variation "Theo dõi" switch, who set it (``default`` or a
  user id) and when. ``juli_app``: SELECT, INSERT, UPDATE.
- ``shopee_stock_alert_unsubscribes`` -- members who stopped this shop's stock e-mail.
  ``juli_app``: SELECT, INSERT.
- ``shopee_stock_alert_sends`` -- one row per shop per local day (unique), the send's idempotency
  key. ``juli_app``: SELECT, INSERT.

The shop settings (``stock_alert_status`` off | preview | on, ``stock_alert_days``) are
``shop_rules`` rows; no schema change there.

EXPAND-ONLY AND REVERSIBLE: new tables, indexes, policies and grants; no row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "129_stock_alert"
down_revision: str | None = "128_connector_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
HISTORY = "shopee_stock_history"
TRACKING = "shopee_sku_tracking"
UNSUBSCRIBES = "shopee_stock_alert_unsubscribes"
SENDS = "shopee_stock_alert_sends"
#: table -> the verbs ``juli_app`` gets (and a policy each)
VERBS = {
    HISTORY: ("SELECT", "INSERT"),
    TRACKING: ("SELECT", "INSERT", "UPDATE"),
    UNSUBSCRIBES: ("SELECT", "INSERT"),
    SENDS: ("SELECT", "INSERT"),
}
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def upgrade() -> None:
    op.create_table(
        HISTORY,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.Column("sellable", sa.Integer(), nullable=True),
        sa.Column("available", sa.Integer(), nullable=True),
        sa.Column("listing_status", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{HISTORY}"),
        sa.UniqueConstraint(
            "shop_id", "item_id", "model_id", "read_at", name="uq_shopee_stock_history_read"
        ),
    )
    op.create_index(
        "ix_shopee_stock_history_sku", HISTORY, ["shop_id", "item_id", "model_id", "read_at"]
    )
    op.create_table(
        TRACKING,
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("tracked", sa.Boolean(), nullable=False),
        sa.Column("set_by", sa.String(length=36), nullable=False),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", "item_id", "model_id", name=f"pk_{TRACKING}"),
    )
    op.create_table(
        UNSUBSCRIBES,
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", "user_id", name=f"pk_{UNSUBSCRIBES}"),
    )
    op.create_table(
        SENDS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column(
            "rows",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preview", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SENDS}"),
        sa.UniqueConstraint("shop_id", "local_date", name="uq_shopee_stock_alert_sends_day"),
        sa.CheckConstraint(
            "kind IN ('alert', 'empty', 'no_read')", name="ck_shopee_stock_alert_sends_kind"
        ),
    )
    for table, verbs in VERBS.items():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # nosec B608
        for verb in verbs:
            op.execute(  # nosec B608 - fixed module constants
                f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {_CLAUSES[verb]}"
            )
        grant = ", ".join(verbs)
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'GRANT {grant} ON public.{table} TO {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants


def downgrade() -> None:
    for table in VERBS:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_table(SENDS)
    op.drop_table(UNSUBSCRIBES)
    op.drop_table(TRACKING)
    op.drop_index("ix_shopee_stock_history_sku", table_name=HISTORY)
    op.drop_table(HISTORY)
