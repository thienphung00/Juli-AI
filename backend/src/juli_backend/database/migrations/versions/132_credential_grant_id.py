"""One TikTok grant's credentials refresh as one unit (P101 W2a).

Revision ID: 132_credential_grant_id
Revises: 131_connector_reader_blocks
Create Date: 2026-11-16

THE RISK. Since P101 W2a one OAuth grant writes a credential row per authorised shop, each a copy
of the same access + refresh token. TikTok Shop rotates the refresh token on every refresh, so the
first shop to refresh leaves every sibling holding a dead refresh token -- their next refresh
fails and they go ``needs_reauth`` although the seller did nothing.

WHAT IT ADDS.

- ``tiktok_credentials.grant_id`` (nullable uuid) + an index: the lineage of one grant. Every row a
  single OAuth provision writes carries the same id; a later re-grant stamps a new one, so rows the
  new grant no longer covers drop out of the lineage. NULL for every row written before this
  revision (single-shop grants: no siblings).
- ``enumerate_grant_sibling_credentials(uuid)``: the refresh's sibling list. Siblings live in OTHER
  shops, which ``tiktok_credentials``' shop-keyed policy hides from the refreshing shop's scope, so
  the read cannot run inside a scope (ADR-089 decision 3, the 061 / 102 circularity). Narrowed so
  it can only ever answer about the CALLER's own credential: the source row must belong to
  ``app_current_shop_id()``. Siblings must share its ``grant_id``, merchant and capability, and
  their shop must have the same owner -- another account or merchant is never returned. Returns
  ``(credential id, shop id)`` only, never token material. The refresh then writes each sibling
  under that sibling's own shop scope, so no policy is relaxed.

SECURITY DEFINER with a pinned ``search_path``, EXECUTE revoked from PUBLIC and granted to
``juli_app`` only (061 / 099 / 102 shape). Literal SQL, so the additive-only gate reads it.

EXPAND-ONLY AND REVERSIBLE (ADR-027). A nullable column, an index and one function; no data is
moved. ``downgrade`` drops them. APPLY BEFORE THE CODE: on PostgreSQL the refresh calls the
function directly, with no existence probe and no silent fallback (061).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "132_credential_grant_id"
down_revision: str | None = "131_connector_reader_blocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tiktok_credentials", sa.Column("grant_id", sa.Uuid(), nullable=True))
    op.create_index("ix_tiktok_credentials_grant_id", "tiktok_credentials", ["grant_id"])
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_grant_sibling_credentials(source_credential uuid)
    RETURNS TABLE (
        out_credential_id uuid,
        out_shop_id uuid
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT o.id, o.shop_id
          FROM public.tiktok_credentials AS c
          JOIN public.shops AS cs ON cs.id = c.shop_id
          JOIN public.tiktok_credentials AS o
            ON o.grant_id = c.grant_id
           AND o.id <> c.id
           AND o.shop_id <> c.shop_id
           AND o.merchant_authorization_id = c.merchant_authorization_id
           AND o.capability IS NOT DISTINCT FROM c.capability
          JOIN public.shops AS os ON os.id = o.shop_id AND os.user_id = cs.user_id
         WHERE c.id = source_credential
           AND c.shop_id = app_current_shop_id()
           AND c.grant_id IS NOT NULL
           AND c.merchant_authorization_id IS NOT NULL
         ORDER BY o.created_at, o.id
      $fn$;
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.enumerate_grant_sibling_credentials(uuid) FROM PUBLIC;"
    )
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'juli_app') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION '
                'public.enumerate_grant_sibling_credentials(uuid) TO juli_app';
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.enumerate_grant_sibling_credentials(uuid);")
    op.drop_index("ix_tiktok_credentials_grant_id", table_name="tiktok_credentials")
    op.drop_column("tiktok_credentials", "grant_id")
