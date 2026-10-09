"""Seller reasons for reject / decline / revert, and inventory_items.seller_sku (fast track P10-A).

Revision ID: 079_decision_reasons
Revises: 078_rules_and_write_values
Create Date: 2026-10-09

ACCEPTANCE AC-10.1, ADR-109 amendment 1 (decisions 1 and 7), contract
``fasttrack/contracts/p10-quyet-dinh.md`` §1-§2.

WHAT IT ADDS.

- ``decision_reasons``: one row per seller "Từ chối" (card), "Không thực hiện"
  (consent step) or "Hoàn tác" (finished run) -- the one required reason code,
  the optional note (≤ 300 chars), who and when, and the (product, lever) the
  7-day cooldown is keyed on with the rate the card was proposed on. Written by
  the three routes (INSERT only); read by the card generator's cooldown check.
- ``inventory_items.seller_sku``: the seller's own SKU code, shown on the card
  ("SM-012 +2"). Nullable; filled by the next inventory sync.

Tenant-scoped like 078: RLS on ``decision_reasons``, one policy per verb through
``app_current_shop_id()``, ``juli_app`` granted SELECT, INSERT only.
``inventory_items`` already has its policies; a new column needs none.

EXPAND-ONLY AND REVERSIBLE. One new table, one nullable column. ``downgrade``
drops both.

RE-CHAIN AT INTEGRATION. Authored onto ``078_rules_and_write_values`` while P10-B
may add its own 080 on the same parent; whichever lands second re-points its
``down_revision`` so the chain stays linear, and the deferred phone-cleanup step
stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "079_decision_reasons"
down_revision: str | None = "078_rules_and_write_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "decision_reasons"
VERBS = "SELECT, INSERT"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("action_card_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("lever_code", sa.String(length=32), nullable=True),
        sa.Column("basis_stage_rate", sa.String(length=8), nullable=True),
        sa.Column("basis_rate", sa.Float(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_decision_reasons"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_decision_reasons_shop"),
        sa.ForeignKeyConstraint(
            ["action_card_id"], ["action_cards.id"], name="fk_decision_reasons_card"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_decision_reasons_run"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_decision_reasons_product"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], name="fk_decision_reasons_user"
        ),
        sa.CheckConstraint(
            "action IN ('reject', 'decline', 'revert')", name="ck_decision_reasons_action"
        ),
    )
    op.create_index("ix_decision_reasons_shop_id", TABLE, ["shop_id"])
    op.create_index(
        "ix_decision_reasons_cooldown",
        TABLE,
        ["shop_id", "product_id", "lever_code", "decided_at"],
    )
    op.add_column("inventory_items", sa.Column("seller_sku", sa.String(length=100), nullable=True))

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
            EXECUTE 'GRANT {VERBS} ON public.{TABLE} TO {ROLE_NAME}';
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
    op.drop_column("inventory_items", "seller_sku")
    op.drop_table(TABLE)
