"""Content analysis of seller-uploaded videos and LIVE recordings (fast track P15).

Revision ID: 082_content_analysis
Revises: 081_order_cost_data
Create Date: 2026-10-10

DECISIONS D24.19 / D24.20; contract ``fasttrack/contracts/p15-content-analysis.md``.

WHAT IT ADDS.

``content_analyses`` -- one row per upload: what the seller uploaded it for
(video / LIVE, the Phân tích row, the product, optionally the content run),
the upload's progress, the pipeline's status, and ONLY DERIVED DATA: the
transcript segments, scene cuts, on-screen text, the product-on-screen
timeline, the scoring result, the OpenAI usage and cost. The uploaded file
itself lives on the VPS disk until the analysis ends (then it is deleted) and
never in the database; ``storage_key`` is cleared when it is.

Written by the demo routes (create, upload progress) and the
``analyze_content_upload`` Celery task under the shop's scope: INSERT /
UPDATE. No DELETE grant: rows are kept as the shop's history (they hold no
media). Tenant-scoped like 081: RLS on, one policy per verb through
``app_current_shop_id()``.

EXPAND-ONLY AND REVERSIBLE. One new table; nothing existing is touched.
``downgrade`` drops it. The deferred phone-cleanup step is re-parented onto
this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "082_content_analysis"
down_revision: str | None = "081_order_cost_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "content_analyses"
GRANT_VERBS = "SELECT, INSERT, UPDATE"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("content_ref", sa.String(length=200), nullable=True),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=300), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column(
            "cost_usd", sa.Numeric(precision=10, scale=6), nullable=False, server_default="0"
        ),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("file_deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_content_analyses"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_content_analyses_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_content_analyses_run"
        ),
        sa.CheckConstraint("kind IN ('video', 'live')", name="ck_content_analyses_kind"),
    )
    op.create_index("ix_content_analyses_shop_id", TABLE, ["shop_id"])
    op.create_index(
        "ix_content_analyses_shop_product", TABLE, ["shop_id", "tiktok_product_id", "created_at"]
    )

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
            EXECUTE 'GRANT {GRANT_VERBS} ON public.{TABLE} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


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
