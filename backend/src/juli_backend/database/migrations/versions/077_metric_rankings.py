"""Stored ADR-109 d.5 metric rankings, one per shop / end date / stream / metric (fast track P8-A).

Revision ID: 077_metric_rankings
Revises: 076_shop_diagnosis_reports
Create Date: 2026-10-08

ACCEPTANCE AC-8.1, ADR-109 decision 5.

WHAT IT ADDS. ``shop_metric_rankings``: for each traffic stream × clickable
metric of the Phân tích screen, the rows (products, LIVE sessions, videos)
ranked by the GMV/day their change in that metric moved, plus the closing rows
that make the table add up to the stream's factor GMV. Written by the daily
shop diagnosis job from the snapshot it already fetched; read by
``GET /v1/demo/analysis/rankings``. ``ranking`` is the JSON payload of
``shop_diagnosis.rankings`` (aggregates and titles only). Unique on
(shop_id, end_date, stream, metric); ``stream`` / ``metric`` are checked
against ADR-109 d.4's values.

Shape: one row per table rather than one row per ranked line -- a table is
always read whole (one click, one table), is at most ~25 lines, and its lines
only make sense together (the closing rows reconcile to the stream factor), so
normalising the lines would buy joins and nothing else.

Tenant-scoped exactly like 076's ``shop_diagnosis_reports``: RLS on, one
policy per verb through ``app_current_shop_id()``, ``juli_app`` granted SELECT /
INSERT / UPDATE only.

EXPAND-ONLY AND REVERSIBLE. One new table; ``downgrade`` drops it.

RE-CHAIN AT INTEGRATION. Authored onto ``076_shop_diagnosis_reports`` while
sibling fast-track tasks (P8-C) add their own revision on the same parent;
whichever lands second re-points its ``down_revision``, and the deferred
phone-cleanup step stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "077_metric_rankings"
down_revision: str | None = "076_shop_diagnosis_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "shop_metric_rankings"
STREAMS = ("product_card", "shop_tab", "seller_live", "seller_video")
METRICS = ("impressions", "ctr", "ctor", "add_to_cart_rate", "orders_per_cart", "aov")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("ranking", sa.JSON(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name=f"fk_{TABLE}_shop"),
        sa.UniqueConstraint("shop_id", "end_date", "stream", "metric", name=f"uq_{TABLE}_key"),
        sa.CheckConstraint(_in("stream", STREAMS), name=f"ck_{TABLE}_stream"),
        sa.CheckConstraint(_in("metric", METRICS), name=f"ck_{TABLE}_metric"),
    )
    op.create_index(f"ix_{TABLE}_shop_id", TABLE, ["shop_id"])


def _enable_rls_and_policies() -> None:
    """Tenant-scope the table the way 076 scoped ``shop_diagnosis_reports``."""
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
