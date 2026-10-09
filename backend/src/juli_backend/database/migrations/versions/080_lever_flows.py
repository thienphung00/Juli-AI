"""Lever flows: cover-image photos, Seller Center promotions, measurement (fast track P10-B).

Revision ID: 080_lever_flows
Revises: 078_rules_and_write_values
Create Date: 2026-10-09

ACCEPTANCE AC-10.2, contract ``fasttrack/contracts/p10-quyet-dinh.md`` §4-§6,
ADR-109 Amendment 1 decisions 3 and 6.

WHAT IT ADDS.

- ``run_lever_flows``: one row per run of a card whose lever is not a plain
  listing write -- ``photo`` (cover image: the run waits for the seller's photo)
  or ``promotion`` (the four Seller Center levers: the run waits for the seller
  to apply the promotion, then verifies it on TikTok, read-only). Holds the
  promotion proposal checked against the seller's rules, the seller's "Tôi đã
  áp dụng" time, the verification attempts and the promotion found, and the
  date the measurement clock starts. Written by approve (INSERT), the worker and
  the flow routes (UPDATE).
- ``run_lever_photos``: the cover image before Juli's change and the seller's
  photo (bytes, size, check results), served by our API under an unguessable
  per-photo token so the consent step can show both without any TikTok URL or
  credential leaving the backend. The staged TikTok image URI is kept on the
  seller's photo so the write after consent can attach it.
- ``lever_calibrations``: per shop and lever, the realised / expected GMV ratio
  (D16 / D22), starting at 0.5, updated by each conclusive day-14 result.
- ``run_measurement_finals``: the day-14 verdict of a run, written once; it is
  what makes the calibration update happen exactly once per run.

Tenant-scoped like 078: RLS on, one policy per verb through
``app_current_shop_id()``, ``juli_app`` granted only the verbs its call sites
use (no DELETE anywhere).

EXPAND-ONLY AND REVERSIBLE. Four new tables; nothing existing is touched.
``downgrade`` drops them.

RE-CHAIN AT INTEGRATION. Authored onto ``078_rules_and_write_values`` while
P10-A adds its own 079 on the same parent; the orchestrator re-points
``down_revision`` so the chain stays linear, and the deferred phone-cleanup
step stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "080_lever_flows"
down_revision: str | None = "078_rules_and_write_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

#: table -> the verbs juli_app needs (matched to the call sites; see docstring).
GRANTS: dict[str, str] = {
    "run_lever_flows": "SELECT, INSERT, UPDATE",
    "run_lever_photos": "SELECT, INSERT, UPDATE",
    "lever_calibrations": "SELECT, INSERT, UPDATE",
    "run_measurement_finals": "SELECT, INSERT",
}


def _create_tables() -> None:
    op.create_table(
        "run_lever_flows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("verify_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("found", sa.JSON(), nullable=True),
        sa.Column("measurement_start", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_lever_flows"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_lever_flows_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_lever_flows_run"
        ),
        sa.UniqueConstraint("workflow_run_id", name="uq_run_lever_flows_run"),
        sa.CheckConstraint("kind IN ('photo', 'promotion')", name="ck_run_lever_flows_kind"),
    )
    op.create_index("ix_run_lever_flows_shop_id", "run_lever_flows", ["shop_id"])

    op.create_table(
        "run_lever_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("tiktok_uri", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_lever_photos"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_lever_photos_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_lever_photos_run"
        ),
        sa.UniqueConstraint("workflow_run_id", "role", name="uq_run_lever_photos_run_role"),
        sa.UniqueConstraint("public_token", name="uq_run_lever_photos_token"),
        sa.CheckConstraint("role IN ('before', 'after')", name="ck_run_lever_photos_role"),
    )
    op.create_index("ix_run_lever_photos_shop_id", "run_lever_photos", ["shop_id"])

    op.create_table(
        "lever_calibrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("coefficient", sa.Numeric(6, 4), nullable=False),
        sa.Column("readings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_lever_calibrations"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_lever_calibrations_shop"),
        sa.UniqueConstraint("shop_id", "lever", name="uq_lever_calibrations_lever"),
    )
    op.create_index("ix_lever_calibrations_shop_id", "lever_calibrations", ["shop_id"])

    op.create_table(
        "run_measurement_finals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=True),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("gmv_actual_per_day", sa.Numeric(18, 2), nullable=True),
        sa.Column("pct_of_expected", sa.Integer(), nullable=True),
        sa.Column("calibration_from", sa.Numeric(6, 4), nullable=True),
        sa.Column("calibration_to", sa.Numeric(6, 4), nullable=True),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_measurement_finals"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_measurement_finals_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_measurement_finals_run"
        ),
        sa.UniqueConstraint("workflow_run_id", name="uq_run_measurement_finals_run"),
        sa.CheckConstraint(
            "label IN ('dat', 'gan_dat', 'khong_dat', 'chua_ket_luan')",
            name="ck_run_measurement_finals_label",
        ),
    )
    op.create_index("ix_run_measurement_finals_shop_id", "run_measurement_finals", ["shop_id"])


def _enable_rls_and_policies(table: str, verbs: str) -> None:
    """Tenant-scope ``table`` the way 078 scoped ``run_write_values``."""
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
    op.drop_table("run_measurement_finals")
    op.drop_table("lever_calibrations")
    op.drop_table("run_lever_photos")
    op.drop_table("run_lever_flows")
