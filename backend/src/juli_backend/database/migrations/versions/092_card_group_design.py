"""Card groups: design (source, reason, CTR guard) for Ops (fast track P36).

Revision ID: 092_card_group_design
Revises: 091_trial_signups
Create Date: 2026-10-16

DECISIONS D45 (simulator research priorities into Ops): D45.1 a D34 group for a
lever Juli does not propose (a new pack option the owner creates on TikTok) is
created in Juli Ops; D45.2 such a group declares its primary metric (AOV) with the
product-card CTR as a guard; D45.3 / D45.4 each group carries an optional one-line
"lý do chọn thử nghiệm" typed in Ops.

WHAT IT ADDS. One nullable JSON column, ``card_groups.design``:
``{source: cards | ops, reason, guard, created_by}``. ``NULL`` = a group drawn from
Optimize Product drafts (every row before this revision). No new table, policy or
grant: ``card_groups`` already has RLS by ``app_current_shop_id()`` and ``juli_app``
SELECT / INSERT / UPDATE (089), which is all the writes need.

EXPAND-ONLY AND REVERSIBLE. ``downgrade`` drops the column. The deferred
phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "092_card_group_design"
down_revision: str | None = "091_trial_signups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "card_groups"
COLUMN = "design"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
