"""add workflow_run_events table (#1125, ADR-074 decisions 1-2, AGT-W3B)

Revision ID: 035_workflow_run_events_table
Revises: 034_workflow_runs_table
Create Date: 2026-08-14

Additive-only, same discipline as 033/034: one brand-new table, no existing
column anywhere dropped, renamed, narrowed, or made ``NOT NULL``.

``workflow_run_events`` (ADR-074 decision 1): the Postgres-authoritative
event log. Anything a client ever sees on the SSE stream (a later slice)
must exist as a row here first -- Redis is best-effort delivery on top,
never the source of truth. Mirrors the Pydantic envelope in
``services/agent/events/envelope.py`` field-for-field: ``workflow_run_id``,
``sequence_number``, ``event_type``, ``timestamp``, ``payload`` (JSONB),
``v``, plus the ORM-only surrogate primary key ``id``.

The unique index ``uq_workflow_run_events_run_sequence`` on
``(workflow_run_id, sequence_number)`` is the mechanism, not decoration
(ADR-074 decision 1): sequence numbers are minted by the ``WorkflowRunner``
(a later slice) from its run-state blob, and exactly one writer exists per
run, so a crash-replayed emit racing the same sequence number hits this
constraint and becomes a no-op instead of a duplicate row.

``workflow_run_id`` carries a real ``ForeignKeyConstraint`` to
``workflow_runs.id`` (migration 034, #1117 / AGT-W3A) -- this migration's
``down_revision`` chains directly onto 034 for exactly that reason; applying
this migration's ``upgrade()`` against a database that lacks
``workflow_runs`` fails at the database level (the ``CREATE TABLE ...
REFERENCES workflow_runs(id)`` has nothing to reference).

The currently-deployed release keeps reading/writing every existing table
completely unchanged while this migration is applied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "035_workflow_run_events_table"
down_revision: str | None = "034_workflow_runs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("v", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_workflow_run_events_run_sequence",
        "workflow_run_events",
        ["workflow_run_id", "sequence_number"],
        unique=True,
    )
    op.create_index(
        "ix_workflow_run_events_run_id",
        "workflow_run_events",
        ["workflow_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_run_events_run_id", table_name="workflow_run_events")
    op.drop_index("uq_workflow_run_events_run_sequence", table_name="workflow_run_events")
    op.drop_table("workflow_run_events")
