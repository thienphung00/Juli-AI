"""Shopee recommendations: simulation prior runs and calibration state (ADR-121, P90 step 8)

Revision ID: 115_shopee_recommendations
Revises: 114_card_verification_events
Create Date: 2026-11-04

Cards reuse ``action_cards`` / ``shop_proposals`` (same id) / ``card_events``. Two CLIENT-LANE
tables, tenant-direct (``shop_id``, RLS by ``app_current_shop_id()``), are new because no
existing table holds them:

- ``shopee_sim_prior_runs`` -- an imported ``juli-sim/priors/v1`` run of this shop, with its
  per change_kind gate (SELECT, INSERT, UPDATE: a newer run supersedes the older).
- ``shopee_reco_calibrations`` -- this shop's calibration state per (change_kind, metric) and
  the scored observations it was computed from (SELECT, INSERT, UPDATE).

EXPAND-ONLY AND REVERSIBLE: tables, indexes, policies and grants; no data change. ``downgrade``
drops them. The deferred write-mode backfill stays the tail (re-parented onto this revision).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "115_shopee_recommendations"
down_revision: str | None = "114_card_verification_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
SIM_TABLE = "shopee_sim_prior_runs"
CAL_TABLE = "shopee_reco_calibrations"
_CLAUSES = {
    "SELECT": "USING (shop_id = app_current_shop_id())",
    "INSERT": "WITH CHECK (shop_id = app_current_shop_id())",
    "UPDATE": "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())",
}
TENANT_TABLES = (SIM_TABLE, CAL_TABLE)


def _shop() -> sa.Column:
    return sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        SIM_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("shop_alias", sa.String(length=64), server_default="", nullable=False),
        sa.Column("model_version", sa.String(length=64), server_default="", nullable=False),
        sa.Column("priors_version", sa.String(length=64), server_default="", nullable=False),
        sa.Column("gate", postgresql.JSONB(), nullable=False),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("imported_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SIM_TABLE}"),
        sa.UniqueConstraint("shop_id", "run_id", name="uq_shopee_sim_prior_runs_run"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_shopee_sim_prior_runs_status"
        ),
    )
    op.create_index("ix_shopee_sim_prior_runs_shop_status", SIM_TABLE, ["shop_id", "status"])
    op.create_table(
        CAL_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        _shop(),
        sa.Column("change_kind", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=16), nullable=False),
        sa.Column("n_results", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pooled_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("coverage_n", sa.Integer(), server_default="0", nullable=False),
        sa.Column("coverage_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "range_scale", sa.Numeric(precision=8, scale=4), server_default="1", nullable=False
        ),
        sa.Column("n_bundle_excluded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("observations", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{CAL_TABLE}"),
        sa.UniqueConstraint(
            "shop_id", "change_kind", "metric", name="uq_shopee_reco_calibrations_key"
        ),
    )
    op.create_index("ix_shopee_reco_calibrations_shop", CAL_TABLE, ["shop_id"])
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
    for table in (CAL_TABLE, SIM_TABLE):
        op.drop_table(table)
