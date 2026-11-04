"""Shopee income export: the actual fees and payout per order (P91 D-12)

Revision ID: 117_shopee_order_income
Revises: 116_shopee_reco_codes
Create Date: 2026-11-04

One new tenant-direct table and one nullable column:

- ``shopee_order_income`` -- one row per order from the income export (Tài chính › Doanh thu):
  the fees Shopee ACTUALLY charged (cố định, dịch vụ with its hạ tầng and Voucher Xtra parts,
  xử lý giao dịch, PiShip, NTTD), the shipping the seller bore after Shopee's and the buyer's
  share, return shipping (two kinds), the refund, lost-parcel compensation, the affiliate
  commission, the VAT / PIT Shopee withheld, the vouchers and coins the seller bore, the payout and
  the payout date. Keyed ``(shop_id, platform, order_ref)`` -- ``order_ref`` is the same keyed hash
  as ``shopee_order_lines.order_ref``, so the two join. A table of its own rather than columns
  on the lines: an income row can exist for an order the order export does not hold, and the
  amounts are per ORDER (the engine splits them across the order's lines by value when it
  reads them). ``juli_app`` SELECT, INSERT, UPDATE (a later export of the same month ranks
  the same or higher and replaces the row); RLS by ``app_current_shop_id()``.
- ``shopee_order_lines.variation_name`` -- the order export's "Tên phân loại hàng". Combo
  variations reuse one SKU, so the name is what tells "Combo 3 hộp" from "Combo 10 hộp".

EXPAND-ONLY AND REVERSIBLE: a table and a nullable column; no data is moved or rewritten.
``downgrade`` drops both.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "117_shopee_order_income"
down_revision: str | None = "116_shopee_reco_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "shopee_order_income"
LINES = "shopee_order_lines"
#: Written out, not imported from the models: a migration must not change when the model does.
PLATFORMS = ("tiktok", "shopee")
MONEY_COLUMNS: tuple[str, ...] = (
    "payout",
    "product_price",
    "refund_amount",
    "fee_fixed",
    "fee_service",
    "fee_infra",
    "fee_voucher_xtra",
    "fee_payment",
    "fee_piship",
    "fee_nttd",
    "affiliate_commission",
    "ship_actual_cost",
    "ship_shopee_subsidy",
    "ship_buyer_paid",
    "ship_piship_refund",
    "ship_seller_support",
    "net_shipping_cost",
    "return_ship_refund",
    "return_ship_failed",
    "lost_compensation",
    "vat_withheld",
    "pit_withheld",
    "seller_voucher_borne",
    "seller_coin_borne",
    "trade_in_bonus_seller",
)
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def upgrade() -> None:
    op.add_column(LINES, sa.Column("variation_name", sa.String(length=128), nullable=True))
    money = sa.Numeric(precision=18, scale=2)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("order_ref", sa.String(length=128), nullable=False),
        sa.Column("ordered_on", sa.Date(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        *[sa.Column(name, money, nullable=True) for name in MONEY_COLUMNS],
        sa.Column("transaction_fee_rate", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_rank", sa.SmallInteger(), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload_id", sa.Uuid(), sa.ForeignKey("ingest_raw_payloads.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.UniqueConstraint("shop_id", "platform", "order_ref", name="uq_shopee_order_income_key"),
        sa.CheckConstraint(
            "platform IN (" + ", ".join(f"'{p}'" for p in PLATFORMS) + ")",
            name="ck_shopee_order_income_platform",
        ),
    )
    op.create_index("ix_shopee_order_income_paid", TABLE, ["shop_id", "paid_on"])
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")  # nosec B608
    for verb in ("SELECT", "INSERT", "UPDATE"):
        op.execute(  # nosec B608 - fixed module constants
            f"CREATE POLICY {TABLE}_{verb.lower()}_public ON public.{TABLE} FOR {verb} "
            f"{_CLAUSES[verb]}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{TABLE} TO {APP_ROLE}';
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
    op.drop_table(TABLE)
    op.drop_column(LINES, "variation_name")
