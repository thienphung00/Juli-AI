"""Per-shop production write enable and the run's write mode (fast track P61-B).

Revision ID: 097_production_write_shops
Revises: 095_card_events
Create Date: 2026-10-20

DECISIONS D71.2; ADR-085 decisions 6 and 7.

WHAT IT ADDS.

- ``production_write_shops``: one row per shop the owner has turned production
  writes on for. It sits **beside** the global ``PRODUCTION_WRITE_ENABLED`` flag
  and every other ADR-085 gate (kill switch, RLS boot check, red-team
  attestation, the per-mutation ``production_write_authorizations`` row); it
  replaces none of them. A row, not an env list and not a ``shops`` column:
  ``juli_app`` holds table-wide UPDATE on ``shops`` (058), so a column there
  would be an enable the runtime role could set on itself. Here ``juli_app``
  gets SELECT only -- the row is written by the owner on an admin connection,
  exactly like an authorization row (048). Tenant-direct: RLS on, one SELECT
  policy through ``app_current_shop_id()``.
- ``workflow_runs.write_mode`` (``live`` | ``simulated``, nullable): where the
  run's writes went. ``simulated`` = the sandbox merchant, not the seller's own
  shop. The run surface says so instead of "Đã áp dụng", and measurement skips
  it. NULL = a run constructed before this column existed (no backfill: the
  value is a fact recorded at construction, not inferable afterwards).

EXPAND-ONLY AND REVERSIBLE. A new table with its policy and grant, a nullable
column with a CHECK; no data change. ``downgrade`` drops both. The deferred
phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "097_production_write_shops"
down_revision: str | None = "095_card_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "production_write_shops"
RUNS_TABLE = "workflow_runs"
WRITE_MODE_COLUMN = "write_mode"
#: Written out rather than imported from the model: a migration must not change
#: when the model does. ``tests/unit/test_p61b_production_write.py`` pins them equal.
WRITE_MODES = ("live", "simulated")
WRITE_MODE_CHECK = "ck_workflow_runs_write_mode"


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("enabled_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("shop_id", name="pk_production_write_shops"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_production_write_shops_shop"),
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {TABLE}_select_public ON public.{TABLE} "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT ON public.{TABLE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - table and role are fixed module constants

    op.add_column(RUNS_TABLE, sa.Column(WRITE_MODE_COLUMN, sa.String(length=16), nullable=True))
    op.create_check_constraint(
        WRITE_MODE_CHECK,
        RUNS_TABLE,
        f"{WRITE_MODE_COLUMN} IS NULL OR {WRITE_MODE_COLUMN} IN ({_in(WRITE_MODES)})",
    )


def downgrade() -> None:
    op.drop_constraint(WRITE_MODE_CHECK, RUNS_TABLE, type_="check")
    op.drop_column(RUNS_TABLE, WRITE_MODE_COLUMN)
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608
    op.drop_table(TABLE)
