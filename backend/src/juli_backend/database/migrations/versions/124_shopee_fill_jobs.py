"""The fill queue: jobs the Connector opens and fills after an approval (P97 D85.6)

Revision ID: 124_shopee_fill_jobs
Revises: 123_shopee_metrics_tables
Create Date: 2026-11-09

One tenant-direct table ``shopee_fill_jobs`` (RLS by ``app_current_shop_id()``; SELECT / INSERT /
UPDATE for ``juli_app``, additive, no data step, rows are finished by status and never deleted).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "124_shopee_fill_jobs"
down_revision: str | None = "123_shopee_metrics_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "shopee_fill_jobs"
TENANT_TABLES = (TABLE,)
STATUSES = ("queued", "opened", "filled", "saved", "captured", "failed", "cancelled")
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _jsonb() -> sa.types.TypeEngine:
    from sqlalchemy.dialects.postgresql import JSONB

    return JSONB()


def upgrade() -> None:
    statuses = ", ".join(f"'{s}'" for s in STATUSES)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("shop_proposals.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("group_code", sa.String(length=16), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("target", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("target_key", sa.String(length=80), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="queued"),
        sa.Column("captured_ref", sa.String(length=64), nullable=True),
        sa.Column("error", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "proposal_id", "version", "target_key", name="uq_shopee_fill_jobs_target"
        ),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_shopee_fill_jobs_status"),
    )
    op.create_index("ix_shopee_fill_jobs_shop_status", TABLE, ["shop_id", "status", "created_at"])
    op.create_index("ix_shopee_fill_jobs_proposal", TABLE, ["shop_id", "proposal_id"])
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
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants
    op.drop_index("ix_shopee_fill_jobs_proposal", table_name=TABLE)
    op.drop_index("ix_shopee_fill_jobs_shop_status", table_name=TABLE)
    op.drop_table(TABLE)
