"""Shopee affiliate order lines keep their KOL (P91 D-9)

Revision ID: 118_shopee_kol_lines
Revises: 117_shopee_reco_plans
Create Date: 2026-11-04

Five nullable columns on ``shopee_order_lines``, written only by the ``affiliate_order_lines``
lane (SellerConversionReport) when it marks a line:

- ``kol_key`` -- ``'a'`` + 12 hex of SHA-1 of the creator's account (the same ``_short_hash``
  the ``affiliate_partner_period`` segment uses). The platform's raw affiliate id is never
  stored; the report names the creator by public account handle only.
- ``kol_handle`` -- the creator's PUBLIC account handle (a handle, not a buyer; <= 120).
- ``affiliate_channel`` -- ``Kênh`` (Shopee Video / Facebook / TikTok ...).
- ``affiliate_campaign_type`` -- ``Loại chiến dịch`` (open / targeted ...).
- ``affiliate_mcn`` -- true when the line is linked to an MCN (``MCN được liên kết`` is
  non-empty); the MCN's name is not stored.

No buyer data. RLS and grants of ``shopee_order_lines`` (112) are unchanged: the table keeps
its policies and ``juli_app`` SELECT / INSERT / UPDATE. One partial index serves the KOL read
model (shop, KOL, order time) and only covers marked lines.

EXPAND-ONLY AND REVERSIBLE: nullable columns and one index; ``downgrade`` drops them. The
Mẫu KOL sheet needs no table: it is stored as the ``kol_sample`` shop rule (versioned by
``shop_rule_versions``), so this migration holds nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "118_shopee_kol_lines"
down_revision: str | None = "117_shopee_reco_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINES_TABLE = "shopee_order_lines"
KOL_INDEX = "ix_shopee_order_lines_kol"


def upgrade() -> None:
    op.add_column(LINES_TABLE, sa.Column("kol_key", sa.String(length=16), nullable=True))
    op.add_column(LINES_TABLE, sa.Column("kol_handle", sa.String(length=120), nullable=True))
    op.add_column(LINES_TABLE, sa.Column("affiliate_channel", sa.String(length=64), nullable=True))
    op.add_column(
        LINES_TABLE, sa.Column("affiliate_campaign_type", sa.String(length=64), nullable=True)
    )
    op.add_column(LINES_TABLE, sa.Column("affiliate_mcn", sa.Boolean(), nullable=True))
    op.create_index(
        KOL_INDEX,
        LINES_TABLE,
        ["shop_id", "kol_key", "ordered_at"],
        postgresql_where=sa.text("kol_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(KOL_INDEX, table_name=LINES_TABLE)
    for column in (
        "affiliate_mcn",
        "affiliate_campaign_type",
        "affiliate_channel",
        "kol_handle",
        "kol_key",
    ):
        op.drop_column(LINES_TABLE, column)
