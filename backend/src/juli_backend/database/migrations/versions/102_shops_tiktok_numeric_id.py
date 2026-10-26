"""TikTok's numeric shop id on ``shops``, and the webhook shop resolve (fast track P68, E11).

Revision ID: 102_shops_tiktok_numeric_id
Revises: 100_sandbox_collision_xshop
Create Date: 2026-10-26

THE BUG. TikTok order webhooks for a connected shop went to the DLQ as
``unknown shop tiktok_shop_id=7495274531001436791``. ``shops.tiktok_shop_id`` holds the
identifier the connect flow received (the OAuth ``open_id``), while a webhook names the shop by
TikTok's **numeric** shop id -- the ``id`` that Get Authorized Shops returns beside ``cipher``.
Nothing stored that number, so no webhook could ever match.

WHAT IT ADDS.

- ``shops.tiktok_numeric_shop_id`` (nullable varchar) + a unique partial index over the non-NULL
  values: one Juli shop per TikTok shop. Filled on connect / reconnect from the verified
  authorized shop, and lazily by the poll for shops connected before this revision.
- ``resolve_tiktok_shop_key(text)``: the webhook's shop resolve. A webhook carries no tenant
  context and its shop is the answer the lookup produces, so the read cannot run inside a scope
  (ADR-089 decision 3, the same circularity as 061). Returns the shop id alone, at most one row,
  matching either identifier (``tiktok_shop_id`` first).
- ``record_tiktok_numeric_shop_id(uuid, text)``: the write. ``shops``' UPDATE policy is keyed on
  the USER, and both writers (the OAuth callback's credential step, the poll) hold a SHOP scope,
  so a plain UPDATE would match zero rows. The function writes only the row named by
  ``app_current_shop_id()`` -- a caller can fill its own shop and nothing else -- and returns
  whether a row changed.

Both functions are ``SECURITY DEFINER`` with a pinned ``search_path``, EXECUTE revoked from
PUBLIC and granted to ``juli_app`` only (061 / 099 shape).

EXPAND-ONLY AND REVERSIBLE (ADR-027). A nullable column, an index and two functions; no data is
moved. ``downgrade`` drops them. The deferred write-mode backfill (and the phone cleanup under
it) is re-parented onto this revision so it stays the tail.

APPLY BEFORE THE CODE (``deploy.sh`` migrates first): on PostgreSQL the repository calls the
functions directly, with no existence probe and no silent fallback (061).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "102_shops_tiktok_numeric_id"
down_revision: str | None = "100_sandbox_collision_xshop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
TABLE = "shops"
COLUMN = "tiktok_numeric_shop_id"
INDEX = "uq_shops_tiktok_numeric_shop_id"
RESOLVE_SIGNATURE = "resolve_tiktok_shop_key(text)"
RECORD_SIGNATURE = "record_tiktok_numeric_shop_id(uuid, text)"
FUNCTION_SIGNATURES = (RESOLVE_SIGNATURE, RECORD_SIGNATURE)


def _restrict_execute(signature: str) -> None:
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.{signature} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=64), nullable=True))
    op.create_index(
        INDEX,
        TABLE,
        [COLUMN],
        unique=True,
        postgresql_where=sa.text(f"{COLUMN} IS NOT NULL"),
    )
    # Literal SQL (no helper call): the additive-only deploy gate must read it statically.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.resolve_tiktok_shop_key(shop_key text)
    RETURNS TABLE (
        out_shop_id uuid
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT s.id
          FROM public.shops AS s
         WHERE s.tiktok_shop_id = shop_key
            OR s.tiktok_numeric_shop_id = shop_key
         ORDER BY (s.tiktok_shop_id = shop_key) DESC, s.created_at
         LIMIT 1
      $fn$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.record_tiktok_numeric_shop_id(
        target_shop uuid,
        numeric_id text
    )
    RETURNS boolean
      LANGUAGE sql
      VOLATILE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        WITH changed AS (
            UPDATE public.shops AS s
               SET tiktok_numeric_shop_id = numeric_id
             WHERE s.id = target_shop
               AND s.id = app_current_shop_id()
               AND numeric_id IS NOT NULL
               AND s.tiktok_numeric_shop_id IS DISTINCT FROM numeric_id
            RETURNING s.id
        )
        SELECT EXISTS (SELECT 1 FROM changed)
      $fn$;
    """)
    for signature in FUNCTION_SIGNATURES:
        _restrict_execute(signature)


def downgrade() -> None:
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature};")  # nosec B608
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_column(TABLE, COLUMN)
