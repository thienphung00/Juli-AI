"""Stored ADR-108 shop diagnosis reports, one per shop / end date / ranking (fast track P7-A).

Revision ID: 076_shop_diagnosis_reports
Revises: 075_analytics_breakdown
Create Date: 2026-10-08

ACCEPTANCE AC-7.1, DECISIONS D21.

WHAT IT ADDS. ``shop_diagnosis_reports``: the daily per-shop job's output, read
by ``GET /v1/demo/analysis``. ``report`` is the ``report.json`` dict of the
shop diagnosis package (aggregates only -- no buyer-level order rows);
``end_date`` is its ``as_of``; ``ranking`` is the hero ranking mode
(``60d`` default, ``30d``). Unique on (shop_id, end_date, ranking), which is
what makes the job idempotent per shop and day.

Tenant-scoped exactly like 074's ``shop_ingestion_state``: RLS on, one policy
per verb through ``app_current_shop_id()`` (never the raw
``current_setting(...)::uuid`` cast, #1467), and ``juli_app`` granted SELECT /
INSERT / UPDATE -- the verbs the job and the read route use. DELETE stays
ungranted.

EXPAND-ONLY AND REVERSIBLE. One new table; nothing existing is altered.
``downgrade`` drops it.

RE-CHAIN AT INTEGRATION. Authored onto ``075_analytics_breakdown`` while a
sibling fast-track branch (P7-B) may add its own revision on the same parent;
whichever lands second must re-point its ``down_revision`` so the chain stays
linear, and the deferred phone-cleanup step must stay the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "076_shop_diagnosis_reports"
down_revision: str | None = "075_analytics_breakdown"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "shop_diagnosis_reports"


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("ranking", sa.String(length=4), nullable=False, server_default="60d"),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{TABLE}_shop"),
        sa.UniqueConstraint("shop_id", "end_date", "ranking", name=f"uq_{TABLE}_key"),
        sa.CheckConstraint("ranking IN ('60d', '30d')", name=f"ck_{TABLE}_ranking"),
    )
    op.create_index(f"ix_{TABLE}_shop_id", TABLE, ["shop_id"])


def _enable_rls_and_policies() -> None:
    """Tenant-scope the table the way 074 scoped ``shop_ingestion_state``."""
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    for verb, clause in (
        ("SELECT", "USING (shop_id = app_current_shop_id())"),
        (
            "UPDATE",
            "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
        ),
        ("DELETE", "USING (shop_id = app_current_shop_id())"),
        ("INSERT", "WITH CHECK (shop_id = app_current_shop_id())"),
    ):
        op.execute(  # nosec B608 - table, verb and clause are fixed module constants
            f"CREATE POLICY {TABLE}_{verb.lower()}_public ON public.{TABLE} FOR {verb} {clause}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{TABLE} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_table()
    _enable_rls_and_policies()


def downgrade() -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_table(TABLE)
