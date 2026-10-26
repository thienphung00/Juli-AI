"""Per-shop pseudonym keys ``shop_pseudonym_keys`` (NDA work, PR 3).

Revision ID: 104_shop_pseudonym_keys
Revises: 103_data_use_consents
Create Date: 2026-10-26

DECISIONS D76; ADR-116 §4 (grill log D5, D8).

WHAT IT ADDS. One tenant table holding, per shop, the random 32-byte key that
``buyer_id`` is pseudonymised with (``HMAC-SHA256(key, platform buyer id)``, in
bronze and silver alike):

- one row per shop (``uq_shop_pseudonym_keys_shop``); the key is stored sealed
  (``enc:p1:shop_pseudonym_key:...``, Fernet under a key derived for that purpose
  from ``TIKTOK_TOKEN_ENCRYPTION_KEY``), never in clear;
- deleting the row makes the shop's stored ids permanently anonymous (offboarding,
  a later PR -- ADR-116 named AWS Secrets Manager for the keys; the VPS role is
  read-only there, so the keys live here, sealed);
- RLS through ``app_current_shop_id()``. ``juli_app`` may SELECT and INSERT only:
  a key is never rewritten, and DELETE comes with offboarding (the privacy purge in
  094 already deletes every ``shop_id`` table as the owner).

EXPAND-ONLY AND REVERSIBLE. A new table, its policies and its grants; no data
change. Removing stored buyer fields and re-keying stored ids is a DATA change,
so it is the operator command ``python -m juli_backend.services.privacy.payload_cleanup``
(dry run by default), not a migration. ``downgrade`` drops the table. The deferred
write-mode backfill (and the phone cleanup under it) is re-parented onto this
revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "104_shop_pseudonym_keys"
down_revision: str | None = "103_data_use_consents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "shop_pseudonym_keys"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("key_ciphertext", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shop_pseudonym_keys"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_shop_pseudonym_keys_shop"),
        sa.UniqueConstraint("shop_id", name="uq_shop_pseudonym_keys_shop"),
        sa.CheckConstraint(
            "key_ciphertext LIKE 'enc:p1:shop_pseudonym_key:%'",
            name="ck_shop_pseudonym_keys_sealed",
        ),
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
    """)  # nosec B608 - table and role are fixed module constants
    op.drop_table(TABLE)
