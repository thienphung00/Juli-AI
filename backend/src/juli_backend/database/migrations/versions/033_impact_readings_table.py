"""add impact_readings table for incremental impact measurement (#1040, ADR-077 d.5, I9)

Revision ID: 033_impact_readings_table
Revises: 032_close_public_schema_defaults
Create Date: 2026-08-12

Additive-only: a brand-new table, ``impact_readings``, the source of truth for
every incremental-impact reading the daily impact-reader beat task computes
(ADR-077 d.5). Because the table is new, no existing table (``tool_executions``,
``action_cards``, or otherwise) is altered, and no column is dropped, renamed,
narrowed, or made NOT NULL.

Unique on ``(tool_execution_id, metric, kind)`` — the correctness constraint
that makes the daily reader idempotent, per ADR-077 d.5 and the issue's
acceptance criteria. ``kind`` is check-constrained to ``preliminary`` |
``final``; ``confidence`` is check-constrained to exactly the five documented
values (``cao`` | ``trung_binh`` | ``thap`` | ``suppressed`` | ``confounded``)
so an unknown value is rejected at the database, not silently stored.

Numeric precision deliberately reuses the two scales
``analytics_performance_intervals`` (migration 017) already established rather
than inventing a third: ``pre``/``post``/``expected``/``incremental`` use
``Numeric(18, 2)`` (the same scale as that table's ``gmv`` column);
``impact_pct`` uses ``Numeric(10, 6)`` (the same scale as its ``ctr`` /
``conversion_rate`` columns) because it is always a ratio
(``incremental / expected``) regardless of which underlying metric produced
the reading.

Known deliberate deferred constraint — read before "fixing" this: ADR-077 d.5
names ``run_id`` alongside ``tool_execution_id``, but the ``workflow_runs``
table (W3-A's write path, ADR-073) does not exist yet in this schema; the wave
handoff states P-IM "depends on nothing in the agent stack ... use synthetic T
fixtures until W3-A". So ``run_id`` is carried here as a plain nullable UUID
column with **no foreign key** — ``tool_execution_id`` does get a real FK to
the pre-existing ``tool_executions`` table (migration 015). W3-A should add
``ForeignKeyConstraint(["run_id"], ["workflow_runs.id"])`` in a follow-up
migration once ``workflow_runs`` exists; this migration deliberately does not
attempt a forward-reference to a table that isn't there.

The currently-deployed release keeps reading/writing every existing table
completely unchanged while this migration is applied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "033_impact_readings_table"
down_revision: str | None = "032_close_public_schema_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_KINDS = ("preliminary", "final")
_VALID_CONFIDENCE = ("cao", "trung_binh", "thap", "suppressed", "confounded")


def upgrade() -> None:
    op.create_table(
        "impact_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Deliberately no ForeignKeyConstraint — see module docstring.
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("tool_execution_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("pre", sa.Numeric(18, 2), nullable=True),
        sa.Column("post", sa.Numeric(18, 2), nullable=True),
        sa.Column("expected", sa.Numeric(18, 2), nullable=True),
        sa.Column("incremental", sa.Numeric(18, 2), nullable=True),
        sa.Column("impact_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column(
            "control_set_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tool_execution_id"], ["tool_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tool_execution_id",
            "metric",
            "kind",
            name="uq_impact_readings_execution_metric_kind",
        ),
        sa.CheckConstraint(
            f"kind IN ({', '.join(repr(k) for k in _VALID_KINDS)})",
            name="ck_impact_readings_kind",
        ),
        sa.CheckConstraint(
            f"confidence IN ({', '.join(repr(c) for c in _VALID_CONFIDENCE)})",
            name="ck_impact_readings_confidence",
        ),
    )
    op.create_index(
        "ix_impact_readings_run_id",
        "impact_readings",
        ["run_id"],
    )
    op.create_index(
        "ix_impact_readings_tool_execution",
        "impact_readings",
        ["tool_execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_impact_readings_tool_execution", table_name="impact_readings")
    op.drop_index("ix_impact_readings_run_id", table_name="impact_readings")
    op.drop_table("impact_readings")
