"""The Connector on more than one computer: fill-job lease and per-token state (batch-1118e R7)

Revision ID: 135_connector_multi_computer
Revises: 133_fleet_draws_real_shops
Create Date: 2026-11-18

One shop can run the Connector on several computers (one ingest token each). Nothing coordinated
them: every poll got every open fill job, and the last writer won the shop's heartbeat, version
and reader blocks.

- ``shopee_fill_jobs.claimed_by_token_id`` / ``lease_until`` -- nullable: the token a poll handed
  the job to, until when (UTC naive). Another live token's poll skips a leased job.
- ``shopee_connector_token_state`` -- tenant-direct, one row per ingest token: what that computer
  last said (heartbeat, version, Seller Centre tab, reader blocks). ``shopee_connector_state``
  stays as the shop's aggregate. RLS and ``juli_app`` grants as 128.
- ``ingest_tokens.install_id`` -- nullable: the Connector's per-install random id sent at pairing,
  indexed with (shop_id, platform).

EXPAND-ONLY AND REVERSIBLE: nullable columns, one new table, one index; no row is moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "135_connector_multi_computer"
down_revision: str | None = "133_fleet_draws_real_shops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TOKEN_STATE = "shopee_connector_token_state"
INSTALL_INDEX = "ix_ingest_tokens_install"


def upgrade() -> None:
    op.add_column("shopee_fill_jobs", sa.Column("claimed_by_token_id", sa.Uuid(), nullable=True))
    op.add_column("shopee_fill_jobs", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("ingest_tokens", sa.Column("install_id", sa.String(length=64), nullable=True))
    op.create_index(INSTALL_INDEX, "ingest_tokens", ["shop_id", "platform", "install_id"])
    op.create_table(
        TOKEN_STATE,
        sa.Column("token_id", sa.Uuid(), sa.ForeignKey("ingest_tokens.id"), nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("connector_version", sa.String(length=32), nullable=True),
        sa.Column("seller_centre_open", sa.Boolean(), nullable=True),
        sa.Column(
            "reader_blocks",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("reader_blocks_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("token_id", name=f"pk_{TOKEN_STATE}"),
    )
    op.create_index(f"ix_{TOKEN_STATE}_shop", TOKEN_STATE, ["shop_id"])
    op.execute(f"ALTER TABLE public.{TOKEN_STATE} ENABLE ROW LEVEL SECURITY")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TOKEN_STATE}_select_public ON public.{TOKEN_STATE} FOR SELECT "
        "USING (shop_id = app_current_shop_id())"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TOKEN_STATE}_insert_public ON public.{TOKEN_STATE} FOR INSERT "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(  # nosec B608 - fixed module constants
        f"CREATE POLICY {TOKEN_STATE}_update_public ON public.{TOKEN_STATE} FOR UPDATE "
        "USING (shop_id = app_current_shop_id()) WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.{TOKEN_STATE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def downgrade() -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TOKEN_STATE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants
    op.drop_index(f"ix_{TOKEN_STATE}_shop", table_name=TOKEN_STATE)
    op.drop_table(TOKEN_STATE)
    op.drop_index(INSTALL_INDEX, table_name="ingest_tokens")
    op.drop_column("ingest_tokens", "install_id")
    op.drop_column("shopee_fill_jobs", "lease_until")
    op.drop_column("shopee_fill_jobs", "claimed_by_token_id")
