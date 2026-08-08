"""Decision emission/surfacing budget: columns + novelty ledger (#716, B-4, ADR-038 §6)

Revision ID: 027_decision_emission_budget
Revises: 026_action_cards_computed_at
Create Date: 2026-08-08

Additive/expand-only, same discipline as 026:

- ``action_cards`` gains three nullable columns — ``dismissed_at``
  (parallels the existing ``approved_at`` / ``executed_at`` terminal
  timestamps), ``surfaced_at``, and ``suppressed_reason``. These are
  additive *columns* alongside the existing seller-lifecycle ``status``
  (active/approved/dismissed/executing) rather than new ``status`` enum
  values — see ``services/action_cards/MODULE.md`` for the full rationale.
  No existing column is dropped, renamed, narrowed, or made NOT NULL.
- A composite index on ``action_cards`` (shop_id, workflow_key) plus the
  three terminal timestamps (``dismissed_at`` / ``approved_at`` /
  ``executed_at``) is provisioned ahead of need for a cooldown lookup query a
  future slice may issue directly against Postgres. It is **not** exercised
  today: ``apply_emission_budget``'s only query is
  ``WHERE shop_id=:s AND status='active'`` (served by the pre-existing
  ``ix_action_cards_shop_status``), and the cooldown itself is computed in
  Python over those already-loaded rows. A second index makes the
  surfaced/suppressed state queryable separately from "all scored rows"
  without a table scan — this one *is* live (``GET`` paths / diagnostics can
  filter on ``surfaced_at`` directly).
- A brand-new table, ``decision_emission_novelty_ledger``, durably tracks
  (Postgres, not Redis) which workflow_keys have already consumed a "new
  this week" novelty slot per shop per ISO week — the server-side novelty
  counter/window state required by ADR-038 §6. Because the table is new,
  its NOT NULL columns constrain no pre-existing row (same precedent as
  024/025's new gold/silver tables) and stay additive.

The currently-deployed release keeps reading/writing ``action_cards``
completely unchanged while this migration is applied: existing rows read
back with the three new columns NULL, and older code paths that never
mention them are unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "027_decision_emission_budget"
down_revision: str | None = "026_action_cards_computed_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_cards",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_cards",
        sa.Column("surfaced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_cards",
        sa.Column("suppressed_reason", sa.String(length=40), nullable=True),
    )

    op.create_index(
        "ix_action_cards_shop_workflow_terminal",
        "action_cards",
        ["shop_id", "workflow_key", "dismissed_at", "approved_at", "executed_at"],
    )
    op.create_index(
        "ix_action_cards_shop_surfaced_at",
        "action_cards",
        ["shop_id", "surfaced_at"],
    )

    op.create_table(
        "decision_emission_novelty_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("first_surfaced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "week_start",
            "workflow_key",
            name="uq_decision_emission_novelty_shop_week_workflow",
        ),
    )
    op.create_index(
        "ix_decision_emission_novelty_shop_week",
        "decision_emission_novelty_ledger",
        ["shop_id", "week_start"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_emission_novelty_shop_week",
        table_name="decision_emission_novelty_ledger",
    )
    op.drop_table("decision_emission_novelty_ledger")

    op.drop_index("ix_action_cards_shop_surfaced_at", table_name="action_cards")
    op.drop_index("ix_action_cards_shop_workflow_terminal", table_name="action_cards")

    op.drop_column("action_cards", "suppressed_reason")
    op.drop_column("action_cards", "surfaced_at")
    op.drop_column("action_cards", "dismissed_at")
