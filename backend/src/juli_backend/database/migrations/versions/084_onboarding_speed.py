"""Quick-scan state and the nightly history marker on ``shop_ingestion_state`` (fast track P17).

Revision ID: 084_onboarding_speed
Revises: 081_order_cost_data
Create Date: 2026-10-10

DECISIONS D26 (cards right after connecting: the "quét nhanh") and D25.12
(history to 180 days in the background); contract
``fasttrack/contracts/p17-onboarding-speed.md``.

WHAT IT ADDS. Five nullable columns on 074's ``shop_ingestion_state``:

- ``quick_scan_status`` (``running`` | ``done`` | ``skipped`` | ``failed``),
  ``quick_scan_started_at``, ``quick_scan_done_at``, ``quick_scan_cards`` --
  the quick scan's progress, read by ``GET /v1/shops/me/onboarding`` and the
  time-to-first-card measurement;
- ``history_extended_on`` -- the local day of the last nightly history
  extension, so a duplicated beat runs it once a night.

Same table, same RLS policies and the same ``juli_app`` grants (074 granted
table-level SELECT / INSERT / UPDATE, which cover new columns). No new table,
no data change.

EXPAND-ONLY AND REVERSIBLE. ``downgrade`` drops the five columns.

RE-CHAIN AT INTEGRATION. Authored onto ``081_order_cost_data`` while sibling
fast-track branches add 082/083; the orchestrator re-points ``down_revision``
onto the last of them. The deferred phone-cleanup step is re-parented onto this
revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "084_onboarding_speed"
down_revision: str | None = "081_order_cost_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "shop_ingestion_state"
QUICK_SCAN_STATUSES = ("running", "done", "skipped", "failed")

COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("quick_scan_status", sa.String(length=20), nullable=True),
    sa.Column("quick_scan_started_at", sa.DateTime(), nullable=True),
    sa.Column("quick_scan_done_at", sa.DateTime(), nullable=True),
    sa.Column("quick_scan_cards", sa.Integer(), nullable=True),
    sa.Column("history_extended_on", sa.Date(), nullable=True),
)
CHECK_NAME = f"ck_{TABLE}_quick_scan_status"


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, column.copy())
    values = ", ".join(repr(v) for v in QUICK_SCAN_STATUSES)
    op.create_check_constraint(
        CHECK_NAME, TABLE, f"quick_scan_status IS NULL OR quick_scan_status IN ({values})"
    )


def downgrade() -> None:
    op.drop_constraint(CHECK_NAME, TABLE, type_="check")
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column.name)
