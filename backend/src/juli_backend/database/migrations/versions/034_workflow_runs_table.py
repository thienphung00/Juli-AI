"""add workflow_runs table, promote tool_executions to an idempotency ledger,
add the impact_readings.run_id FK (#1117, ADR-073 decisions 1-4, AGT-W3A)

Revision ID: 034_workflow_runs_table
Revises: 033_impact_readings_table
Create Date: 2026-08-14

Additive-only, same discipline as 033: a brand-new table (``workflow_runs``),
new nullable columns on an existing table (``tool_executions``), and one
forward-reference FK that a prior migration explicitly deferred
(``impact_readings.run_id``). No existing column anywhere is dropped,
renamed, narrowed, or made ``NOT NULL``.

``workflow_runs`` (ADR-073 decision 1): the persisted run record
``WorkflowRunner`` (a later slice) will own. ``state`` is JSONB — the
conversation-window/iteration-count/pending-confirmation/basis-snapshot blob
that stands in for the deferred P-CS chat store. ``status``/``stop_reason``
are check-constrained strings mirroring
``services/agent/runner/status.py``'s ``WorkflowRunStatus``/``StopReason``
vocabulary, the same "string + CHECK, not a native enum" choice migration 033
made for ``impact_readings.kind``/``confidence`` — an additive migration adds
a vocabulary member later, never an ``ALTER TYPE``.

The partial unique index ``uq_workflow_runs_active_shop_product`` (ADR-073
decision 4) is the structural guard against a second Juli-initiated run
racing the same ``(shop_id, product_id)``: it only covers rows whose
``status`` is ``queued``, ``running``, or ``waiting_approval`` — a terminal
row (``completed``/``cancelled``/``timed_out``/``failed``) never blocks a
fresh insert for that product.

``tool_executions`` gains three new nullable columns
(``workflow_run_id``/``tool_call_id``/``operation``) plus a unique
constraint over the three (ADR-073 decision 3 — ``ToolExecution`` promoted
from an audit row to an idempotency ledger). All three are nullable because
pre-agent legacy rows, and the existing Celery-approval write path, have
none of them; every column that existed on ``tool_executions`` before this
migration (``id``, ``shop_id``, ``approval_id``, ``tool_name``,
``payload_json``, ``idempotency_key``, ``status``, ``celery_task_id``,
``outcome_json``, ``error_message``, ``error_category``, ``created_at``,
``updated_at``) is untouched.

``impact_readings.run_id`` gets the ``ForeignKeyConstraint`` migration 033's
docstring explicitly deferred to this slice, now that ``workflow_runs``
exists. No data is backfilled and no other column/constraint on
``impact_readings`` (the ``tool_execution_id`` FK, the
``(tool_execution_id, metric, kind)`` unique constraint, the ``kind``/
``confidence`` check constraints) is touched.

The currently-deployed release keeps reading/writing every existing table
completely unchanged while this migration is applied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "034_workflow_runs_table"
down_revision: str | None = "033_impact_readings_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "cancelled",
    "timed_out",
    "failed",
)

_VALID_STOP_REASONS = (
    "final_response",
    "confirmation_declined",
    "paused_for_confirmation",
    "cancelled_by_seller",
    "confirmation_expired",
    "iteration_cap_exceeded",
    "wall_clock_timeout",
    "tool_error_unrecoverable",
    "llm_error",
    "concurrency_conflict",
    "output_validation_failed",
    "worker_lost",
)

_ACTIVE_STATUSES = ("queued", "running", "waiting_approval")


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiting_approval_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "running_seconds_elapsed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _VALID_STATUSES)})",
            name="ck_workflow_runs_status",
        ),
        sa.CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ("
            f"{', '.join(repr(r) for r in _VALID_STOP_REASONS)})",
            name="ck_workflow_runs_stop_reason",
        ),
    )
    op.create_index(
        "ix_workflow_runs_shop",
        "workflow_runs",
        ["shop_id"],
    )
    op.create_index(
        "uq_workflow_runs_active_shop_product",
        "workflow_runs",
        ["shop_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN (" + ", ".join(repr(s) for s in _ACTIVE_STATUSES) + ")"
        ),
    )

    op.add_column(
        "tool_executions",
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "tool_executions",
        sa.Column("tool_call_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tool_executions",
        sa.Column("operation", sa.String(length=100), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_executions_workflow_run_id",
        "tool_executions",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_tool_executions_run_call_operation",
        "tool_executions",
        ["workflow_run_id", "tool_call_id", "operation"],
    )

    op.create_foreign_key(
        "fk_impact_readings_run_id",
        "impact_readings",
        "workflow_runs",
        ["run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_impact_readings_run_id", "impact_readings", type_="foreignkey")

    op.drop_constraint("uq_tool_executions_run_call_operation", "tool_executions", type_="unique")
    op.drop_constraint("fk_tool_executions_workflow_run_id", "tool_executions", type_="foreignkey")
    op.drop_column("tool_executions", "operation")
    op.drop_column("tool_executions", "tool_call_id")
    op.drop_column("tool_executions", "workflow_run_id")

    op.drop_index("uq_workflow_runs_active_shop_product", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_shop", table_name="workflow_runs")
    op.drop_table("workflow_runs")
