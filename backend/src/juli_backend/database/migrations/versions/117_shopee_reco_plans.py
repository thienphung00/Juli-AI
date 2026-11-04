"""Shopee recommendations: the draft plan, plan codes and change sets (P91 D-6, D-7, D-8)

Revision ID: 117_shopee_reco_plans
Revises: 116_shopee_reco_codes
Create Date: 2026-11-04

Four tenant-direct tables (``shop_id``, RLS by ``app_current_shop_id()``; SELECT, INSERT, UPDATE
for ``juli_app``) and one widened CHECK:

- ``shop_reco_plans`` -- a shop's plan: ``draft`` (one per shop: partial unique index) ->
  ``confirmed`` (``KH-<yymm>-<seq3>``, unique per shop) -> ``executed``; the plan-level
  measurement window default, per-product overrides, acknowledged breaches, the aggregate frozen
  on confirm.
- ``shop_reco_plan_cards`` -- a card in a plan with its chosen version and what-if inputs; a
  removed card keeps its row (``removed_at``), so no DELETE grant is needed.
- ``shop_reco_plan_counters`` -- the last plan sequence number per shop; a plan takes the next
  number with one ``UPDATE .. RETURNING`` (the card-code counter's technique).
- ``shop_reco_change_sets`` -- the unit of measurement: cards of one product (or of the shop)
  executed the same day, the window chosen (3..90 days), the joint prediction, the result.
- ``shop_proposals.status`` may be ``planned`` (a card in a draft plan): the CHECK is dropped and
  recreated with the extra value.

EXPAND-ONLY AND REVERSIBLE: new tables, indexes, policies, grants and a wider CHECK; no row is
moved or rewritten (the additive gate refuses a data step). ``downgrade`` drops the tables and puts
the narrower CHECK back as ``NOT VALID`` (a ``planned`` card left behind is not rewritten here: a
person re-opens those cards first). The deferred write-mode tail stays the tail (re-parented onto
this revision).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "117_shopee_reco_plans"
down_revision: str | None = "116_shopee_reco_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
PROPOSALS = "shop_proposals"
PLANS = "shop_reco_plans"
PLAN_CARDS = "shop_reco_plan_cards"
COUNTERS = "shop_reco_plan_counters"
SETS = "shop_reco_change_sets"
TENANT_TABLES = (PLANS, PLAN_CARDS, COUNTERS, SETS)
STATUS_CHECK = "ck_shop_proposals_status"
_STATUSES_116 = (
    "draft",
    "sent",
    "approved",
    "rejected",
    "changes_requested",
    "executed",
    "measured",
    "withdrawn",
    "superseded",
)
STATUSES = (*_STATUSES_116, "planned")
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _shop() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def _jsonb(name: str, *, nullable: bool = True, default: str | None = None) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(),
        nullable=nullable,
        server_default=None if default is None else sa.text(f"'{default}'::jsonb"),
    )


def upgrade() -> None:
    op.drop_constraint(STATUS_CHECK, PROPOSALS, type_="check")
    op.create_check_constraint(STATUS_CHECK, PROPOSALS, f"status IN ({_in(STATUSES)})")

    op.create_table(
        PLANS,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("code", sa.String(length=24), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("window_days", sa.SmallInteger(), nullable=True),
        _jsonb("product_windows", nullable=False, default="{}"),
        sa.Column("planned_date", sa.Date(), nullable=True),
        _jsonb("created_by", nullable=False, default="{}"),
        _jsonb("confirmed_by"),
        _jsonb("acknowledged_breaches"),
        _jsonb("cut_measurements"),
        _jsonb("aggregate"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PLANS}"),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'executed', 'cancelled')", name=f"ck_{PLANS}_status"
        ),
        sa.CheckConstraint(
            "window_days IS NULL OR window_days BETWEEN 3 AND 90", name=f"ck_{PLANS}_window"
        ),
    )
    op.create_index(
        "uq_shop_reco_plans_one_draft",
        PLANS,
        ["shop_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "uq_shop_reco_plans_shop_code",
        PLANS,
        ["shop_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )
    op.create_index("ix_shop_reco_plans_shop_status", PLANS, ["shop_id", "status"])

    op.create_table(
        PLAN_CARDS,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey(f"{PLANS}.id"), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey(f"{PROPOSALS}.id"), nullable=False),
        sa.Column("chosen_version", sa.SmallInteger(), server_default="1", nullable=False),
        _jsonb("inputs", nullable=False, default="{}"),
        sa.Column("prior_status", sa.String(length=24), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False),
        _jsonb("added_by", nullable=False, default="{}"),
        _jsonb("acknowledged_breaches"),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PLAN_CARDS}"),
        sa.CheckConstraint("chosen_version BETWEEN 1 AND 4", name=f"ck_{PLAN_CARDS}_version"),
    )
    op.create_index(
        "uq_shop_reco_plan_cards_open",
        PLAN_CARDS,
        ["plan_id", "proposal_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index("ix_shop_reco_plan_cards_shop_proposal", PLAN_CARDS, ["shop_id", "proposal_id"])

    op.create_table(
        COUNTERS,
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name=f"pk_{COUNTERS}"),
        sa.CheckConstraint("last_seq >= 0", name=f"ck_{COUNTERS}_seq"),
    )

    op.create_table(
        SETS,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey(f"{PLANS}.id"), nullable=True),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("product_id", sa.String(length=64), nullable=True),
        sa.Column("executed_on", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        _jsonb("card_ids", nullable=False, default="[]"),
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("window_source", sa.String(length=8), server_default="auto", nullable=False),
        sa.Column("status", sa.String(length=12), server_default="measuring", nullable=False),
        sa.Column("with_shop_wide", sa.Boolean(), server_default=sa.false(), nullable=False),
        _jsonb("predicted", nullable=False, default="{}"),
        _jsonb("result"),
        sa.Column("cut_at", sa.DateTime(), nullable=True),
        sa.Column("cut_days", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SETS}"),
        sa.CheckConstraint("scope IN ('product', 'shop')", name=f"ck_{SETS}_scope"),
        sa.CheckConstraint("status IN ('measuring', 'done', 'cut')", name=f"ck_{SETS}_status"),
        sa.CheckConstraint("window_source IN ('auto', 'plan', 'custom')", name=f"ck_{SETS}_source"),
        sa.CheckConstraint("window_days BETWEEN 3 AND 90", name=f"ck_{SETS}_window"),
        sa.CheckConstraint(
            "(scope = 'product') = (product_id IS NOT NULL)", name=f"ck_{SETS}_scope_id"
        ),
    )
    op.create_index(
        "uq_shop_reco_change_sets_product_day",
        SETS,
        ["shop_id", "product_id", "executed_on"],
        unique=True,
        postgresql_where=sa.text("scope = 'product'"),
    )
    op.create_index(
        "uq_shop_reco_change_sets_shop_day",
        SETS,
        ["shop_id", "executed_on"],
        unique=True,
        postgresql_where=sa.text("scope = 'shop'"),
    )
    op.create_index("ix_shop_reco_change_sets_shop_status", SETS, ["shop_id", "status"])

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
    for table in reversed(TENANT_TABLES):
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'REVOKE ALL ON public.{table} FROM {APP_ROLE}';
            END IF;
        END
        $$;
        """)  # nosec B608 - fixed module constants
    op.drop_table(SETS)
    op.drop_table(COUNTERS)
    op.drop_table(PLAN_CARDS)
    op.drop_table(PLANS)
    op.drop_constraint(STATUS_CHECK, PROPOSALS, type_="check")
    # NOT VALID: a card still `planned` is not rewritten by a migration; new rows obey the old list
    op.execute(
        f"ALTER TABLE {PROPOSALS} ADD CONSTRAINT {STATUS_CHECK} "
        f"CHECK (status IN ({_in(_STATUSES_116)})) NOT VALID"  # nosec B608 - fixed constants
    )
