"""``enumerate_sandbox_write_credentials()``: a collision is a credential of ANOTHER shop (P61-G2, D71.6a).

Migration 099 set ``out_collides`` when ANY non-sandbox credential shared the sandbox row's
merchant id or shop cipher. Production (owner, 2026-10-21) showed the real sandbox shop holds
TWO rows for the SAME shop: ``sandbox_write`` (merchant A) and ``seller_connect`` (an OAuth
open_id, merchant B), with the same ``shop_cipher``. 099 therefore refused the sandbox
credential and every agent run (which still writes to the sandbox until P61-F) would have
failed for all shops.

The 2026-08-18 invariant is about a sandbox row reaching ANOTHER shop (the production shop).
Rows of the sandbox shop itself sharing its cipher are the same shop, not a collision. So the
predicate gains ``o.shop_id <> c.shop_id``. Signature, ``SECURITY DEFINER``, ``search_path`` and
grants are exactly 099's (``CREATE OR REPLACE`` keeps the grants; they are re-asserted anyway).
Downgrade restores 099's body.

The deferred phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "100_sandbox_collision_xshop"
down_revision: str | None = "099_sandbox_write_enumeration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
FUNCTION_SIGNATURE = "enumerate_sandbox_write_credentials()"


def _body(cross_shop: bool) -> str:
    where = (
        "WHERE o.shop_id <> c.shop_id\n                      AND o.capability"
        if cross_shop
        else "WHERE o.capability"
    )
    return f"""
    CREATE OR REPLACE FUNCTION public.enumerate_sandbox_write_credentials()
    RETURNS TABLE (
        out_shop_id uuid,
        out_merchant text,
        out_collides boolean
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT c.shop_id,
               c.merchant_authorization_id,
               EXISTS (
                   SELECT 1
                     FROM public.tiktok_credentials AS o
                    {where} IS DISTINCT FROM 'sandbox_write'
                      AND (
                          (c.merchant_authorization_id IS NOT NULL
                           AND o.merchant_authorization_id = c.merchant_authorization_id)
                          OR (c.shop_cipher IS NOT NULL AND o.shop_cipher = c.shop_cipher)
                      )
               )
          FROM public.tiktok_credentials AS c
         WHERE c.capability = 'sandbox_write'
         ORDER BY c.created_at DESC
      $fn$;
    """  # nosec B608 -- constant-only f-string (two fixed predicates)


def _grants() -> None:
    op.execute(f"REVOKE ALL ON FUNCTION public.{FUNCTION_SIGNATURE} FROM PUBLIC;")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.{FUNCTION_SIGNATURE} TO {ROLE_NAME}';
        END IF;
    END
    $$;
    """)  # nosec B608


def upgrade() -> None:
    op.execute(_body(cross_shop=True))  # nosec B608
    _grants()


def downgrade() -> None:
    op.execute(_body(cross_shop=False))  # nosec B608
    _grants()
