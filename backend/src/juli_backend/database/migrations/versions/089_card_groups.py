"""Card groups with a randomised delayed control (fast track P30).

Revision ID: 089_card_groups
Revises: 088_ingest_gateway
Create Date: 2026-10-13

DECISIONS D34 (optimise in groups, each with a randomised delayed control) and
D39.3 (D34 in the card system).

WHAT IT ADDS. Two tenant tables, each like 087's / 088's: RLS on, one policy per
granted verb through ``app_current_shop_id()``; ``juli_app`` gets only the verbs
the code needs (SELECT, INSERT, UPDATE -- nothing is deleted).

- ``card_groups``: one wave of Optimize Product cards sharing a target metric ×
  lever × KPI channel in a shop: launch day, control release day (launch + 14),
  the random seed of the draw, status (``open`` / ``measured``) and the day-14
  verdict (JSON). UPDATE: the verdict is written once at day 14.
- ``card_group_members``: one product per group with its arm (``treated`` /
  ``control``), the card it was drawn with and a control's release time.
  UPDATE: ``released_at``.

EXPAND-ONLY AND REVERSIBLE. New tables, policies and grants only; no data
change. ``downgrade`` drops them. The deferred phone-cleanup step is
re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "089_card_groups"
down_revision: str | None = "088_ingest_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
GROUPS_TABLE = "card_groups"
MEMBERS_TABLE = "card_group_members"

UPSERT_VERBS = "SELECT, INSERT, UPDATE"

#: table -> granted verbs. Every table here is tenant-direct.
GRANTS: dict[str, str] = {
    GROUPS_TABLE: UPSERT_VERBS,
    MEMBERS_TABLE: UPSERT_VERBS,
}

_CLAUSES: dict[str, str] = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _create_groups() -> None:
    op.create_table(
        GROUPS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("group_key", sa.String(length=96), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("lever", sa.String(length=48), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("launched_on", sa.Date(), nullable=False),
        sa.Column("release_on", sa.Date(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.JSON(), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_card_groups"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_card_groups_shop"),
        sa.CheckConstraint("status IN ('open', 'measured')", name="ck_card_groups_status"),
    )
    op.create_index(
        "ix_card_groups_shop_key", GROUPS_TABLE, ["shop_id", "group_key", "launched_on"]
    )


def _create_members() -> None:
    op.create_table(
        MEMBERS_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=False),
        sa.Column("action_card_id", sa.Uuid(), nullable=True),
        sa.Column("arm", sa.String(length=16), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_card_group_members"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_card_group_members_shop"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["card_groups.id"], name="fk_card_group_members_group"
        ),
        sa.ForeignKeyConstraint(
            ["action_card_id"], ["action_cards.id"], name="fk_card_group_members_card"
        ),
        sa.UniqueConstraint("group_id", "tiktok_product_id", name="uq_card_group_members_product"),
        sa.CheckConstraint("arm IN ('treated', 'control')", name="ck_card_group_members_arm"),
    )
    op.create_index(
        "ix_card_group_members_shop_product", MEMBERS_TABLE, ["shop_id", "tiktok_product_id"]
    )


def _secure(table: str, verbs: str) -> None:
    """RLS on, one policy per granted verb, and the ``juli_app`` grant."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    for verb in (v.strip() for v in verbs.split(",")):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} "
            f"FOR {verb} {_CLAUSES[verb]}"
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
    _create_groups()
    _create_members()
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
    op.drop_index("ix_card_group_members_shop_product", table_name=MEMBERS_TABLE)
    op.drop_table(MEMBERS_TABLE)
    op.drop_index("ix_card_groups_shop_key", table_name=GROUPS_TABLE)
    op.drop_table(GROUPS_TABLE)
