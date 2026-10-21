"""``enumerate_sandbox_write_credentials()``: find the sandbox credential by capability (fast track P61-G, D71.6).

Until P61-G the sandbox write-validation merchant was a configured id
(``TIKTOK_SANDBOX_MERCHANT_ID``), and 061's ``enumerate_credential_owner_shop(merchant,
capability)`` could find its credential because the caller knew the merchant. The owner
decision of 2026-10-21 removes every configured / hardcoded merchant id: a credential is the
sandbox one because its OWN ``capability`` column is ``sandbox_write``, and its merchant id is
whatever the connect flow stored on the row. The caller no longer knows a merchant to ask
about, so the one cross-tenant question becomes "which credentials carry the sandbox
capability, for which shop and merchant, and do they collide with a production credential".

WHY A ``SECURITY DEFINER`` FUNCTION (ADR-089 decision 3, shaped like 051 / 061 / 074).
``tiktok_credentials`` is RLS'd on ``shop_id`` and the runtime role (``juli_app``) sees one
tenant at a time, but the question spans tenants: the sandbox shop is a different tenant from
the production shop it must never be confused with. The function returns identifiers and one
boolean, never token material; the caller re-reads the credential under the owning shop's
scope through the repo that decrypts it.

``out_collides`` is the 2026-08-18 invariant (``services/tiktok/credential_binding.py``)
restated from credentials alone: a ``sandbox_write`` row collides when ANY credential that is
not ``sandbox_write`` carries the same ``merchant_authorization_id`` or the same non-null
``shop_cipher``. No pinned id, nothing configured. The resolver refuses a colliding sandbox
credential, so a sandbox row whose token resolves to a production shop cannot be used even if
it was written before the on-write check existed.

Rows come back newest first. EXPAND-ONLY AND REVERSIBLE: one new function, its grants go with
``DROP FUNCTION`` on downgrade. APPLY BEFORE THE CODE DEPLOY (the resolver calls it on
PostgreSQL with no existence probe and no silent fallback, like 061).

The deferred phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "099_sandbox_write_enumeration"
down_revision: str | None = "098_processed_events_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "juli_app"
FUNCTION_SIGNATURE = "enumerate_sandbox_write_credentials()"


def upgrade() -> None:
    op.execute("""
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
                    WHERE o.capability IS DISTINCT FROM 'sandbox_write'
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
    """)
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


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION_SIGNATURE};")  # nosec B608
