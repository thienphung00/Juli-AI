"""Card content specs: title candidates, banner set, shop style profile (P100 E.7)

Revision ID: 127_card_content_specs
Revises: 126_shopee_source_funnel
Create Date: 2026-11-12

One tenant-direct table ``card_content_specs`` (``shop_id``, RLS by ``app_current_shop_id()``;
SELECT and INSERT for ``juli_app``; no UPDATE, no DELETE: append-only, the newest row wins).
``spec_type`` is ``title`` | ``banner`` (one card and product) or ``style_profile`` (the shop:
``proposal_id`` and ``item_id`` NULL). Shapes: ``fasttrack/contracts/p100-s2-demo.md``,
"E.7 card specs" (accepted by Session 1, 2026-11-12).

EXPAND-ONLY AND REVERSIBLE: a new table, its indexes, policies and grants; no row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "127_card_content_specs"
down_revision: str | None = "126_shopee_source_funnel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "card_content_specs"
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
}


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("spec_type", sa.String(length=16), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("shop_proposals.id"), nullable=True),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("inputs_hash", sa.String(length=64), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("llm_call_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.CheckConstraint(
            "spec_type IN ('title', 'banner', 'style_profile')", name="ck_card_content_specs_type"
        ),
        sa.CheckConstraint(
            "source IN ('llm', 'seller', 'seeded')", name="ck_card_content_specs_source"
        ),
        sa.CheckConstraint("length(inputs_hash) = 64", name="ck_card_content_specs_hash"),
        sa.CheckConstraint(
            "spec_type <> 'style_profile' OR (proposal_id IS NULL AND item_id IS NULL)",
            name="ck_card_content_specs_profile_shop",
        ),
    )
    op.create_index(
        "ix_card_content_specs_item", TABLE, ["shop_id", "spec_type", "item_id", "created_at"]
    )
    op.create_index(
        "ix_card_content_specs_card", TABLE, ["shop_id", "spec_type", "proposal_id", "created_at"]
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")  # nosec B608
    for verb in ("SELECT", "INSERT"):
        op.execute(  # nosec B608 - fixed module constants
            f"CREATE POLICY {TABLE}_{verb.lower()}_public ON public.{TABLE} FOR {verb} {_CLAUSES[verb]}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}';
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
    op.drop_index("ix_card_content_specs_card", table_name=TABLE)
    op.drop_index("ix_card_content_specs_item", table_name=TABLE)
    op.drop_table(TABLE)
