"""Add series_source column to impact_readings (issue #1766, ADR-099 decision 2).

Implements ADR-099 decision 2: synthetic provenance must be a column, not a
convention. A writer that forgets to declare provenance should FAIL, not
silently record 'measured'. This migration enforces that with a NOT NULL
column and NO DEFAULT at any point in the sequence.

Expand-contract sequence:
1. Add nullable series_source column (NO default)
2. Backfill the two existing rows as 'measured' (real Fujiwa data, not synthetic)
3. Alter column to set NOT NULL

Why no default: A default would make the safe-looking value the one you get by
omission, which is backwards for a field whose entire job is preventing a
synthetic reading from being mistaken for a measurement.

Why 'measured' for backfill: The two existing rows were computed from real
Fujiwa data (ADR-077 d.5). They were insufficient for the control set, hence
confidence: suppressed and fallback_reason: insufficient_candidates, but real
data is not synthetic data.

RLS note: impact_readings is tenant-scoped via tool_executions (parent-scoped
via migration 045's VIA_PARENT policy shape). A new column does not change the
policy set — the existing policies control reads, writes, and deletes. This
column only adds a WHERE constraint on reads that report impact.

The column is queried by every aggregate that reports impact — internal
dashboards, W8's outcome chain (#1655), any future case study — and a claim
about what Juli achieved must be able to exclude synthetic readings with a
WHERE clause, not a JSON path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "056_series_source_column"
down_revision: str | None = "055_juli_app_sync_state_update"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_SERIES_SOURCES = ("measured", "synthetic")


def upgrade() -> None:
    """Add series_source column with expand-contract: nullable → backfill → NOT NULL."""
    # Step 1: Add nullable column (NO default)
    op.add_column(
        "impact_readings",
        sa.Column(
            "series_source",
            sa.String(length=20),
            nullable=True,  # Nullable for backfill phase
            server_default=None,  # Explicit: no default
        ),
    )

    # Step 2: Backfill the two existing rows as 'measured'
    # The two existing rows were computed from real Fujiwa data (ADR-077 d.5).
    # They are insufficient data (confidence: suppressed) but real, not synthetic.
    op.execute(
        """
UPDATE public.impact_readings
SET series_source = 'measured'
WHERE series_source IS NULL;
"""
    )

    # Step 3: Add NOT NULL constraint
    op.alter_column(
        "impact_readings",
        "series_source",
        existing_type=sa.String(length=20),
        nullable=False,
        existing_nullable=True,
    )

    # Step 4: Add check constraint to enforce enum values
    op.create_check_constraint(
        "ck_impact_readings_series_source",
        "impact_readings",
        f"series_source IN ({', '.join(repr(s) for s in _VALID_SERIES_SOURCES)})",
    )


def downgrade() -> None:
    """Reverse: drop constraint and column."""
    op.drop_constraint(
        "ck_impact_readings_series_source",
        "impact_readings",
        type_="check",
    )
    op.drop_column("impact_readings", "series_source")
