"""add refresh-tracking columns to tiktok_credentials (#1230, ADR-081 decision 7)

Revision ID: 038_credential_refresh_cols
Revises: 037_required_steps_completed
Create Date: 2026-08-20

Additive-only, persistence-only slice (AGT-W4A-DP): five new columns on
``tiktok_credentials``, no data migration, no index, no rename, no existing
read path touched.

``status`` (``varchar(20) NOT NULL DEFAULT 'active'``) is a plain
check-free varchar checked in application code -- the same "string, not a
native enum" choice ``workflow_runs.status`` made in migration 034, so a
future vocabulary member (today: ``active`` | ``needs_reauth``) is an
additive change, never an ``ALTER TYPE``. ``refresh_count``
(``integer NOT NULL DEFAULT 0``) backfills existing rows to ``0`` in place.
``last_refreshed_at``, ``last_refresh_error`` and ``refresh_token_expires_at``
are all nullable with no default: a pre-migration-shaped row reads back
``NULL`` for each, never a synthesized value. ``refresh_token_expires_at`` is
populated only if a future refresh call receives ``refresh_token_expire_in``
from the vendor -- a field never observed in a response, a fixture, or
``docs/integrations/tiktok_api/authentication.md`` -- so nothing may assume
this column is ever non-null.

Rejected (ADR-081 decision 7): an index on the scan predicate (~100 rows --
the planner will seq-scan and be right; revisit past a few thousand rows),
and renaming ``token_expires_at`` to ``access_token_expires_at`` (the
asymmetry with ``refresh_token_expires_at`` is real but the rename touches
resolvers, repos, orchestrators and smoke scripts -- neither minimal nor safe
to deploy as part of this slice).

This migration ships schema only. Nothing in this slice reads or writes
these columns except the three new ``TikTokCredentialRepo`` methods it also
adds (``mark_refreshed``, ``mark_needs_reauth``, ``list_expiring_within``);
the beat, lazy and reactive refresh layers land in later slices (#1231,
#1232). Reversible by ``DROP COLUMN``, deployed through
``infra/scripts/safe-alembic-upgrade.sh``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038_credential_refresh_cols"
down_revision: str | None = "037_required_steps_completed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tiktok_credentials",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column("last_refresh_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column(
            "refresh_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "tiktok_credentials",
        sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tiktok_credentials", "refresh_token_expires_at")
    op.drop_column("tiktok_credentials", "refresh_count")
    op.drop_column("tiktok_credentials", "last_refresh_error")
    op.drop_column("tiktok_credentials", "last_refreshed_at")
    op.drop_column("tiktok_credentials", "status")
