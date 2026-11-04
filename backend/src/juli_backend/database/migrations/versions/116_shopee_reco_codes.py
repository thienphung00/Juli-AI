"""Shopee recommendation cards: card codes and the product queue (P91 D-1, D-5)

Revision ID: 116_shopee_reco_codes
Revises: 115_shopee_recommendations
Create Date: 2026-11-04

Two nullable columns on ``shop_proposals`` and one tenant-direct counter table:

- ``shop_proposals.code`` -- ``JC-<yymm>-<seq4>``, unique per shop (partial unique index, so the
  proposals made by hand before P91 and the TikTok ones keep NULL), assigned when a Shopee
  recommendation card is first persisted.
- ``shop_proposals.product_queue`` -- the card's place among the open cards of its product
  (1 = the Quyết định card), NULL when closed or not about one product; indexed with the item.
- ``shop_proposal_code_counters`` -- one row per shop holding the last sequence number handed
  out (SELECT, INSERT, UPDATE under RLS). A card takes the next number with one
  ``INSERT .. ON CONFLICT DO UPDATE .. RETURNING``, which locks the shop's row until the
  transaction ends, so two writers never get the same number.

EXPAND-ONLY AND REVERSIBLE: nullable columns, one index, one new table. The additive gate
refuses a migration that moves rows, so the backfill of codes for the cards that already exist
is NOT here: ``shopee_recommendations.codes.backfill_codes`` (idempotent, ``created_at`` order,
Ops route ``POST .../recommendations/backfill-codes``) does it. ``downgrade`` drops the three
objects. The deferred write-mode backfill stays the tail (re-parented onto this revision).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "116_shopee_reco_codes"
down_revision: str | None = "115_shopee_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
PROPOSALS = "shop_proposals"
COUNTERS = "shop_proposal_code_counters"
TENANT_TABLES = (COUNTERS,)
CODE_INDEX = "uq_shop_proposals_shop_code"
QUEUE_INDEX = "ix_shop_proposals_shop_item_queue"
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def upgrade() -> None:
    op.add_column(PROPOSALS, sa.Column("code", sa.String(length=24), nullable=True))
    op.add_column(PROPOSALS, sa.Column("product_queue", sa.SmallInteger(), nullable=True))
    op.create_index(
        CODE_INDEX,
        PROPOSALS,
        ["shop_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )
    op.create_index(QUEUE_INDEX, PROPOSALS, ["shop_id", "item_id", "product_queue"])
    op.create_table(
        COUNTERS,
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name=f"pk_{COUNTERS}"),
        sa.CheckConstraint("last_seq >= 0", name=f"ck_{COUNTERS}_seq"),
    )
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
    for table in TENANT_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_table(COUNTERS)
    op.drop_index(QUEUE_INDEX, table_name=PROPOSALS)
    op.drop_index(CODE_INDEX, table_name=PROPOSALS)
    op.drop_column(PROPOSALS, "product_queue")
    op.drop_column(PROPOSALS, "code")
