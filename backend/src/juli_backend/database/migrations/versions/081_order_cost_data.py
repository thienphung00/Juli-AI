"""Per-order cost data: price detail, finance transactions, fetch state (fast track P14-C).

Revision ID: 081_order_cost_data
Revises: 080_lever_flows
Create Date: 2026-10-10

DECISIONS D24.13 (cost data, read-only) and D24.12 (promotion ROI needs the
seller-funded cost); contract ``fasttrack/contracts/p14-rules-and-cost.md``.

WHAT IT ADDS.

- ``order_price_details``: ``GET /order/202407/orders/{id}/price_detail`` per
  (shop, order, SKU) plus an order-level row (``tiktok_sku_id = ''``): list and
  sale price, seller-funded vs platform-funded deductions, net price.
- ``order_finance_transactions``: ``GET /finance/202501/orders/{id}/
  statement_transactions`` per (shop, order, SKU, statement) plus an order-level
  row: revenue, fees, shipping, settlement, and the full fee / shipping
  breakdown as JSON.
- ``order_cost_fetches``: per (shop, order), when each read was made, so a poll
  cycle fetches only orders that are new or changed.

Amounts and ids only -- no buyer data, no product or SKU names.

Written by the poll cycle (``services/order_costs/sync.py``, run by ``run_shop_cycle``) under
the shop's sticky scope: INSERT and DELETE on the two data tables (an order's
rows are replaced as a set when it is read again), INSERT / UPDATE on the fetch
state. Tenant-scoped
like 080: RLS on, one policy per verb through ``app_current_shop_id()``.

The seller rule fields of P14-F need no schema: they are new ``rule_key``
values in 078's ``shop_rules`` key/value store.

EXPAND-ONLY AND REVERSIBLE. Three new tables; nothing existing is touched.
``downgrade`` drops them. The deferred phone-cleanup step is re-parented onto
this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "081_order_cost_data"
down_revision: str | None = "080_lever_flows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

#: table -> the verbs juli_app needs (matched to the call sites; see docstring).
#: The two data tables are replaced as a set (delete + insert), never updated,
#: so they hold no UPDATE (least privilege; ``test_no_public_table_holds_update_
#: beyond_its_call_site``). ``order_cost_fetches`` is updated in place.
GRANTS: dict[str, str] = {
    "order_price_details": "SELECT, INSERT, DELETE",
    "order_finance_transactions": "SELECT, INSERT, DELETE",
    "order_cost_fetches": "SELECT, INSERT, UPDATE",
}

PRICE_AMOUNT_FIELDS: tuple[str, ...] = (
    "sku_list_price",
    "sku_sale_price",
    "subtotal",
    "subtotal_deduction_seller",
    "subtotal_deduction_platform",
    "subtotal_tax_amount",
    "voucher_deduction_seller",
    "voucher_deduction_platform",
    "shipping_list_price",
    "shipping_sale_price",
    "shipping_fee_deduction_seller",
    "shipping_fee_deduction_platform",
    "shipping_fee_deduction_platform_voucher",
    "tax_amount",
    "net_price_amount",
    "payment",
    "total",
)

FINANCE_AMOUNT_FIELDS: tuple[str, ...] = (
    "revenue_amount",
    "settlement_amount",
    "fee_tax_amount",
    "shipping_cost_amount",
    "subtotal_before_discount_amount",
    "seller_discount_amount",
    "refund_subtotal_before_discount_amount",
    "seller_discount_refund_amount",
    "platform_commission_amount",
    "transaction_fee_amount",
    "affiliate_commission_amount",
    "voucher_xtra_service_fee_amount",
    "flash_sales_service_fee_amount",
    "campaign_resource_fee",
    "sfp_service_fee_amount",
    "vn_fix_infrastructure_fee",
)


def _amounts(fields: tuple[str, ...]) -> list[sa.Column]:
    return [sa.Column(name, sa.Numeric(18, 2), nullable=True) for name in fields]


def _create_tables() -> None:
    op.create_table(
        "order_price_details",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=False),
        sa.Column("tiktok_sku_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=True),
        sa.Column("line_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=10), nullable=True),
        *_amounts(PRICE_AMOUNT_FIELDS),
        sa.Column("seller_funded_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("platform_funded_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_price_details"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_order_price_details_shop"),
        sa.UniqueConstraint(
            "shop_id", "tiktok_order_id", "tiktok_sku_id", name="uq_order_price_details_sku"
        ),
    )
    op.create_index("ix_order_price_details_shop_id", "order_price_details", ["shop_id"])

    op.create_table(
        "order_finance_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=False),
        sa.Column("tiktok_sku_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("statement_id", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        *_amounts(FINANCE_AMOUNT_FIELDS),
        sa.Column("fee_breakdown", sa.JSON(), nullable=True),
        sa.Column("shipping_breakdown", sa.JSON(), nullable=True),
        sa.Column("order_create_time", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_finance_transactions"),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name="fk_order_finance_transactions_shop"
        ),
        sa.UniqueConstraint(
            "shop_id",
            "tiktok_order_id",
            "tiktok_sku_id",
            "statement_id",
            name="uq_order_finance_tx_sku_statement",
        ),
    )
    op.create_index(
        "ix_order_finance_transactions_shop_id", "order_finance_transactions", ["shop_id"]
    )

    op.create_table(
        "order_cost_fetches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("tiktok_order_id", sa.String(length=100), nullable=False),
        sa.Column("price_order_update_time", sa.DateTime(), nullable=True),
        sa.Column("price_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("price_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finance_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("finance_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("finance_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_cost_fetches"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_order_cost_fetches_shop"),
        sa.UniqueConstraint("shop_id", "tiktok_order_id", name="uq_order_cost_fetches_order"),
    )
    op.create_index("ix_order_cost_fetches_shop_id", "order_cost_fetches", ["shop_id"])


def _enable_rls_and_policies(table: str, verbs: str) -> None:
    """Tenant-scope ``table`` the way 080 scoped ``run_lever_flows``."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
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
            f"CREATE POLICY {table}_{verb.lower()}_public ON public.{table} FOR {verb} {clause}"
        )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT {verbs} ON public.{table} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    _create_tables()
    for table, verbs in GRANTS.items():
        _enable_rls_and_policies(table, verbs)


def downgrade() -> None:
    for table in GRANTS:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {ROLE_NAME}';
            END IF;
        END
        $$;
        """)  # nosec B608
    op.drop_table("order_cost_fetches")
    op.drop_table("order_finance_transactions")
    op.drop_table("order_price_details")
