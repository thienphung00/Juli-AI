"""Per-shop data-use consent ``data_use_consents`` (NDA work, PR 2).

Revision ID: 103_data_use_consents
Revises: 102_shops_tiktok_numeric_id
Create Date: 2026-10-26

DECISIONS D76; ADR-116 §2.

WHAT IT ADDS. One tenant table recording what a shop allowed Juli to do with its
non-public data, one row per grant:

- ``scope`` ∈ ``service`` (analysis and the shop's own client layer, from the
  contract / terms), ``llm_processing`` (sending its data to OpenAI, from the
  approved sub-processor list), ``pooled_training`` (its data in shared models,
  a separate opt-in). ``method`` ∈ ``contract_paper``, ``in_app_click``,
  ``email`` -- the channel is evidence, not a different kind of consent.
- At most one open grant per (``shop_id``, ``scope``): a partial unique index
  ``WHERE revoked_at IS NULL``. A withdrawal sets ``revoked_at``; a new grant is
  a new row, so the history is the table.
- RLS through ``app_current_shop_id()``. ``juli_app`` may SELECT and INSERT, and
  UPDATE the ``revoked_at`` column only, and only on a row that is still open
  (the UPDATE policy's USING) -- a revoked grant cannot be reopened or
  re-dated. No DELETE grant: the rows go with the shop (privacy purge, 094).

EXPAND-ONLY AND REVERSIBLE. A new table, its policies and its grants; no data
change. ``downgrade`` drops it. The deferred write-mode backfill (and the phone
cleanup under it) is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "103_data_use_consents"
down_revision: str | None = "102_shops_tiktok_numeric_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "data_use_consents"

#: Written out rather than imported from the model: a migration must not change
#: when the model does. ``tests/unit/test_data_use_consents.py`` pins the two equal.
SCOPES = ("service", "llm_processing", "pooled_training")
METHODS = ("contract_paper", "in_app_click", "email")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("terms_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.String(length=512), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("granted_by", sa.String(length=255), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_data_use_consents"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_data_use_consents_shop"),
        sa.CheckConstraint(f"scope IN ({_in(SCOPES)})", name="ck_data_use_consents_scope"),
        sa.CheckConstraint(f"method IN ({_in(METHODS)})", name="ck_data_use_consents_method"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="ck_data_use_consents_revoked_after_granted",
        ),
        sa.CheckConstraint(
            "evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_data_use_consents_evidence_sha256",
        ),
    )
    op.create_index(
        "uq_data_use_consents_open",
        TABLE,
        ["shop_id", "scope"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_data_use_consents_shop_scope_granted", TABLE, ["shop_id", "scope", "granted_at"]
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
    op.execute(
        f"CREATE POLICY {TABLE}_revoke_public ON public.{TABLE} "
        "FOR UPDATE USING (shop_id = app_current_shop_id() AND revoked_at IS NULL) "
        "WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}';
            EXECUTE 'GRANT UPDATE (revoked_at) ON public.{TABLE} TO {APP_ROLE}';
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
    """)  # nosec B608 - table and role are fixed module constants
    op.drop_table(TABLE)
