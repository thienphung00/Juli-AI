"""Groups of a plan: options that run together, with one period (P97 D85.14 / P94)

Revision ID: 125_reco_plan_groups
Revises: 123_shopee_metrics_tables
Create Date: 2026-11-09

INTEGRATION NOTE: written on 123 because T3's ``124_shopee_fill_jobs`` is built in parallel; when
both merge, re-parent this revision onto ``124_shopee_fill_jobs`` and move ``deferred/101`` and the
head-pin tests onto 125 (this file is the tail).

Two tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``; SELECT, INSERT, UPDATE for
``juli_app``; no DELETE: a removed member keeps its row, a dropped group is ``cancelled``):

- ``shop_reco_plan_groups`` -- "Nhóm A", "Nhóm B" ... of a plan: letter, run order, start date
  (null = right after the previous group), days (3..90), the ``<card code>-G<letter>`` code frozen
  on confirm, status ``draft`` / ``approved`` / ``cancelled``.
- ``shop_reco_plan_group_members`` -- a version of a planned card in a group; the same card may sit in
  several groups with different versions.

EXPAND-ONLY AND REVERSIBLE: new tables, indexes, policies and grants; no row is moved. Existing plans
have no group and behave as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "125_reco_plan_groups"
down_revision: str | None = "123_shopee_metrics_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
GROUPS = "shop_reco_plan_groups"
MEMBERS = "shop_reco_plan_group_members"
TENANT_TABLES = (GROUPS, MEMBERS)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _shop() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        GROUPS,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("shop_reco_plans.id"), nullable=False),
        sa.Column("letter", sa.String(length=2), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("days", sa.SmallInteger(), nullable=False, server_default="7"),
        sa.Column("code", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="draft"),
        sa.Column(
            "created_by",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{GROUPS}"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'cancelled')", name="ck_shop_reco_plan_groups_status"
        ),
        sa.CheckConstraint("days BETWEEN 3 AND 90", name="ck_shop_reco_plan_groups_days"),
    )
    op.create_index(
        "uq_shop_reco_plan_groups_letter",
        GROUPS,
        ["plan_id", "letter"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )
    op.create_index("ix_shop_reco_plan_groups_shop_plan", GROUPS, ["shop_id", "plan_id"])
    op.create_table(
        MEMBERS,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey(f"{GROUPS}.id"), nullable=False),
        sa.Column(
            "plan_card_id", sa.Uuid(), sa.ForeignKey("shop_reco_plan_cards.id"), nullable=False
        ),
        sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{MEMBERS}"),
        sa.CheckConstraint(
            "version BETWEEN 1 AND 4", name="ck_shop_reco_plan_group_members_version"
        ),
    )
    op.create_index(
        "uq_shop_reco_plan_group_members_open",
        MEMBERS,
        ["group_id", "plan_card_id", "version"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index("ix_shop_reco_plan_group_members_shop_group", MEMBERS, ["shop_id", "group_id"])
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
    op.drop_index("ix_shop_reco_plan_group_members_shop_group", table_name=MEMBERS)
    op.drop_index("uq_shop_reco_plan_group_members_open", table_name=MEMBERS)
    op.drop_table(MEMBERS)
    op.drop_index("ix_shop_reco_plan_groups_shop_plan", table_name=GROUPS)
    op.drop_index("uq_shop_reco_plan_groups_letter", table_name=GROUPS)
    op.drop_table(GROUPS)
