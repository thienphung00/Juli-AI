"""The card journey log ``card_events`` (fast track P60-1a).

Revision ID: 095_card_events
Revises: 094_user_privacy_and_consent
Create Date: 2026-10-20

DECISIONS D70.9; ADR-107 "Amendment 2026-10-20" §1-§3 and §5.

WHAT IT ADDS. One tenant table, append-only like 078's ``run_write_values`` and
087's ``external_changes``: RLS on, a SELECT policy and an INSERT policy through
``app_current_shop_id()``, and ``juli_app`` granted SELECT, INSERT only -- no
UPDATE / DELETE grant and no policy for them, so a correction is a new event.

- ``card_events``: one row per stage of a recommendation. ``event_type`` and
  ``actor`` / ``source`` are CHECK-constrained to the amendment's vocabulary;
  ``card_id`` (-> ``action_cards``) is NULL only for a card-less
  ``seller_change`` and for ``shadow``; a ``dismissed`` row carries one of the
  six dismiss ``reason_code`` values; a live ``proposed`` row names its
  ``model_version`` (``readiness_level`` and ``feature_snapshot_id``, ->
  ``gold.ml_feature_snapshots``, stay nullable until those exist: DEBT P60-1a).
- Idempotency: unique (``shop_id``, ``dedup_key``) for every writer and the
  backfill; a partial unique (``card_id``, ``event_type``) for the event types
  that happen once per card.
- Indexes (``shop_id``, ``workflow_key``, ``occurred_at``), (``card_id``,
  ``occurred_at``), (``shop_id``, ``subject_id``, ``occurred_at``).

EXPAND-ONLY AND REVERSIBLE. A new table, its policies and its grant; no data
change. ``downgrade`` drops it. The deferred phone-cleanup step is re-parented
onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "095_card_events"
down_revision: str | None = "094_user_privacy_and_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "card_events"

#: Written out rather than imported from the model: a migration must not change
#: when the model does. ``tests/unit/test_card_events.py`` pins the two equal.
EVENT_TYPES = (
    "proposed",
    "shown",
    "accepted",
    "edited",
    "dismissed",
    "expired",
    "seller_done",
    "executed",
    "not_executed",
    "reverted",
    "impact_preliminary",
    "impact_final",
    "seller_change",
    "shadow",
    "superseded",
)
SINGLE_PER_CARD = ("proposed", "shown", "dismissed", "expired", "seller_done", "superseded")
CARDLESS = ("seller_change", "shadow")
ACTORS = ("seller", "juli", "tiktok", "system")
SOURCES = ("live", "backfill")
DISMISS_REASONS = (
    "not_needed",
    "wrong_analysis",
    "not_understood",
    "already_done",
    "later",
    "unspecified",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("readiness_level", sa.SmallInteger(), nullable=True),
        sa.Column("feature_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_card_events"),
        sa.ForeignKeyConstraint(["card_id"], ["action_cards.id"], name="fk_card_events_card"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_card_events_shop"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], name="fk_card_events_run"
        ),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["gold.ml_feature_snapshots.id"],
            name="fk_card_events_feature_snapshot",
        ),
        sa.UniqueConstraint("shop_id", "dedup_key", name="uq_card_events_dedup"),
        sa.CheckConstraint(f"event_type IN ({_in(EVENT_TYPES)})", name="ck_card_events_event_type"),
        sa.CheckConstraint(f"actor IN ({_in(ACTORS)})", name="ck_card_events_actor"),
        sa.CheckConstraint(f"source IN ({_in(SOURCES)})", name="ck_card_events_source"),
        sa.CheckConstraint(
            f"card_id IS NOT NULL OR event_type IN ({_in(CARDLESS)})",
            name="ck_card_events_card_id",
        ),
        sa.CheckConstraint(
            f"reason_code IS NULL OR reason_code IN ({_in(DISMISS_REASONS)})",
            name="ck_card_events_reason_code",
        ),
        sa.CheckConstraint(
            "event_type <> 'dismissed' OR reason_code IS NOT NULL",
            name="ck_card_events_dismissed_reason",
        ),
        sa.CheckConstraint(
            "event_type <> 'proposed' OR source <> 'live' OR model_version IS NOT NULL",
            name="ck_card_events_proposed_frozen",
        ),
    )
    op.create_index(
        "uq_card_events_card_single",
        TABLE,
        ["card_id", "event_type"],
        unique=True,
        postgresql_where=sa.text(f"event_type IN ({_in(SINGLE_PER_CARD)})"),
    )
    op.create_index(
        "ix_card_events_shop_workflow_time", TABLE, ["shop_id", "workflow_key", "occurred_at"]
    )
    op.create_index("ix_card_events_card_time", TABLE, ["card_id", "occurred_at"])
    op.create_index(
        "ix_card_events_shop_subject_time", TABLE, ["shop_id", "subject_id", "occurred_at"]
    )

    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {TABLE}_select_public ON public.{TABLE} "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_insert_public ON public.{TABLE} "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - table and role are fixed module constants


def downgrade() -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_index("ix_card_events_shop_subject_time", table_name=TABLE)
    op.drop_index("ix_card_events_card_time", table_name=TABLE)
    op.drop_index("ix_card_events_shop_workflow_time", table_name=TABLE)
    op.drop_index("uq_card_events_card_single", table_name=TABLE)
    op.drop_table(TABLE)
