"""Planned listing changes imported from a file (P91 D-13)

Revision ID: 120_planned_changes
Revises: 119_shopee_order_income
Create Date: 2026-11-04

Two tenant-direct tables, SELECT / INSERT / UPDATE under RLS for ``juli_app`` (additive, no data
step, no change to an existing table):

- ``planned_change_imports`` -- one row per applied file of Cài đặt › Đề xuất kế hoạch (who, when,
  why, file hash, per-row outcome), numbered per shop.
- ``planned_change_refs`` -- the ``external_ref`` of each imported row and the card it became,
  with a hash of the row's content, unique per shop, so a re-import creates nothing twice.

The deferred write-mode backfill stays the tail (re-parented onto this revision).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "120_planned_changes"
down_revision: str | None = "119_shopee_order_income"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
IMPORTS = "planned_change_imports"
REFS = "planned_change_refs"
TENANT_TABLES = (IMPORTS, REFS)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _jsonb() -> sa.types.TypeEngine:
    from sqlalchemy.dialects.postgresql import JSONB

    return JSONB()


def upgrade() -> None:
    op.create_table(
        IMPORTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("set_by", sa.String(length=8), nullable=False),
        sa.Column("set_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("set_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("summary", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{IMPORTS}"),
        sa.UniqueConstraint("shop_id", "number", name="uq_planned_change_imports_number"),
        sa.CheckConstraint("number >= 1", name="ck_planned_change_imports_number"),
        sa.CheckConstraint(
            "set_by IN ('seller', 'staff')", name="ck_planned_change_imports_set_by"
        ),
    )
    op.create_table(
        REFS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("external_ref", sa.String(length=64), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey(f"{IMPORTS}.id"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state", _jsonb(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{REFS}"),
        sa.UniqueConstraint("shop_id", "external_ref", name="uq_planned_change_refs_ref"),
    )
    op.create_index("ix_planned_change_refs_card", REFS, ["shop_id", "card_id"])
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
    for table in reversed(TENANT_TABLES):
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_index("ix_planned_change_refs_card", table_name=REFS)
    op.drop_table(REFS)
    op.drop_table(IMPORTS)
