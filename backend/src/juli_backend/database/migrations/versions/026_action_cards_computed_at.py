"""action_cards freshness metadata: computed_at column (#715, B-3, ADR-038)

Revision ID: 026_action_cards_computed_at
Revises: 025_silver_orders_returns
Create Date: 2026-08-08

Additive/expand-only: adds a nullable ``computed_at`` timestamp column to
``action_cards`` so a persisted Decision candidate carries the scoring run's
freshness timestamp as a real, queryable column — not only inside the
existing ``metadata_json`` blob. This aligns Action Card freshness with the
Analytics envelope freshness semantics already in place (ADR-038):
``gold.kpi_envelopes.computed_at`` (``GoldKpiEnvelope``) and
``analytics_kpi_envelopes.computed_at`` (``AnalyticsKpiEnvelope``) are both
``DateTime(timezone=True)`` columns holding the same "when did this compute
run finish" semantics; ``action_cards.computed_at`` follows the same shape.

Expand-contract discipline: the column is nullable with no server default,
so the currently-deployed release keeps reading/writing ``action_cards``
completely unchanged while this migration is applied — existing rows read
back with ``computed_at IS NULL`` and older code paths that never mention
the column are unaffected. No column is dropped, renamed, or narrowed, and
no existing column gains a NOT NULL constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "026_action_cards_computed_at"
down_revision: str | None = "025_silver_orders_returns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_cards",
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("action_cards", "computed_at")
