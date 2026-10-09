"""Run write values, seller rules, revert questions, and the revert link (fast track P8-C).

Revision ID: 078_rules_and_write_values
Revises: 077_metric_rankings
Create Date: 2026-10-08

ACCEPTANCE AC-8.3, ADR-109 decisions 9-12.

WHAT IT ADDS.

- ``run_write_values``: per run, per tool call, per field, the value read
  immediately before an agent WRITE and the value after it. Read by the
  "Hoàn tác" run and by ``GET /v1/demo/runs/{id}/changes``. Written by the
  worker (INSERT only; rows are never edited).
- ``shop_rules``: the seller-set rule store of ADR-109 d.12, one row per
  (shop, rule, scope) with ``set_by`` ('team' | 'seller'), ``set_by_user_id``
  and ``set_at``. The rules API inserts, updates and deletes rows.
- ``run_revert_questions``: the day-7 guardrail's "Hoàn tác?" question, one per
  run. The impact reader inserts it; the revert / dismiss routes update its
  status.
- ``workflow_runs.reverts_run_id``: nullable self-reference set on a revert run.

Tenant-scoped like 076's ``shop_diagnosis_reports``: RLS on, one policy per verb
through ``app_current_shop_id()``, and ``juli_app`` granted only the verbs its
call sites use (SELECT/INSERT on ``run_write_values``; SELECT/INSERT/UPDATE/
DELETE on ``shop_rules``; SELECT/INSERT/UPDATE on ``run_revert_questions``).

EXPAND-ONLY AND REVERSIBLE. Three new tables and one nullable column; nothing
existing is rewritten. ``downgrade`` drops them.

RE-CHAIN AT INTEGRATION. Authored onto ``076_shop_diagnosis_reports`` while P8-A
adds its own 077 on the same parent; whichever lands second re-points its
``down_revision`` so the chain stays linear, and the deferred phone-cleanup step
stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "078_rules_and_write_values"
down_revision: str | None = "077_metric_rankings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"

#: table -> the verbs juli_app needs (matched to the call sites; see docstring).
GRANTS: dict[str, str] = {
    "run_write_values": "SELECT, INSERT",
    "shop_rules": "SELECT, INSERT, UPDATE, DELETE",
    "run_revert_questions": "SELECT, INSERT, UPDATE",
}


def _create_tables() -> None:
    op.create_table(
        "run_write_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tiktok_product_id", sa.String(length=100), nullable=False),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("before_value", sa.JSON(), nullable=True),
        sa.Column("after_value", sa.JSON(), nullable=True),
        sa.Column("after_source", sa.String(length=16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_write_values"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_write_values_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_write_values_run"
        ),
        sa.UniqueConstraint(
            "workflow_run_id", "tool_call_id", "field", name="uq_run_write_values_call_field"
        ),
        sa.CheckConstraint(
            "after_source IN ('read_back', 'intended')", name="ck_run_write_values_after_source"
        ),
    )
    op.create_index("ix_run_write_values_shop_id", "run_write_values", ["shop_id"])
    op.create_index("ix_run_write_values_run", "run_write_values", ["workflow_run_id"])

    op.create_table(
        "shop_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=40), nullable=False),
        sa.Column("scope_ref", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("set_by", sa.String(length=10), nullable=False),
        sa.Column("set_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("set_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shop_rules"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_shop_rules_shop"),
        sa.ForeignKeyConstraint(["set_by_user_id"], ["users.id"], name="fk_shop_rules_user"),
        sa.UniqueConstraint("shop_id", "rule_key", "scope_ref", name="uq_shop_rules_key"),
        sa.CheckConstraint("set_by IN ('team', 'seller')", name="ck_shop_rules_set_by"),
    )
    op.create_index("ix_shop_rules_shop_id", "shop_rules", ["shop_id"])

    op.create_table(
        "run_revert_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("breaches", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
        sa.Column("revert_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_run_revert_questions"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_run_revert_questions_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_run_revert_questions_run"
        ),
        sa.ForeignKeyConstraint(
            ["revert_run_id"], ["workflow_runs.id"], name="fk_run_revert_questions_revert"
        ),
        sa.UniqueConstraint("workflow_run_id", name="uq_run_revert_questions_run"),
        sa.CheckConstraint(
            "status IN ('open', 'reverted', 'dismissed')", name="ck_run_revert_questions_status"
        ),
    )
    op.create_index("ix_run_revert_questions_shop_id", "run_revert_questions", ["shop_id"])

    op.add_column("workflow_runs", sa.Column("reverts_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_workflow_runs_reverts_run", "workflow_runs", "workflow_runs", ["reverts_run_id"], ["id"]
    )
    op.create_index("ix_workflow_runs_reverts_run_id", "workflow_runs", ["reverts_run_id"])


def _enable_rls_and_policies(table: str, verbs: str) -> None:
    """Tenant-scope ``table`` the way 076 scoped ``shop_diagnosis_reports``."""
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
    op.drop_index("ix_workflow_runs_reverts_run_id", table_name="workflow_runs")
    op.drop_constraint("fk_workflow_runs_reverts_run", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "reverts_run_id")
    op.drop_table("run_revert_questions")
    op.drop_table("shop_rules")
    op.drop_table("run_write_values")
