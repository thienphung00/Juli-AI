"""Enumeration for the configured-merchant credential resolve (#2019, ADR-089).

THE OUTAGE THIS CLOSES.

Since 05:28 UTC 2026-09-16 the `fujiwa-poll-cycle` beat entry failed every fifteen minutes
with

    NotFound('No credentials for merchant 7658073774813611784 with capability
             production_read')

The credential is present, `active` and unexpired. What is absent is the tenant GUC.
`tiktok_credentials_select_public` carries qual `(shop_id = app_current_shop_id())`, the worker
connects as `juli_app` (`rolbypassrls = f`), and `resolve_production_read_credential` queries
before any scope is entered -- it must, because the scope on the line below it is built FROM
`credential.shop_id`, and the credential is what supplies it. `orders` and `inventory_items`
stayed at zero for the whole window.

That circularity is exactly the case ADR-089 decision 3 reserves for an enumeration: "where a
task genuinely cannot know its work list without looking across tenants". The resolve cannot
know its shop without looking across tenants, because the shop is the answer.

WHAT IT IS NOT.

It is not `system_scope`. That flag is "a Python flag and a log line -- no `set_config`, no
`SET ROLE`, no SQL" (051's docstring, above). It suppresses `TenantContextRequiredError` and
nothing else, so it cannot make an RLS-hidden row visible; ADR-089 decision 1 forbids reading it
as a database-layer claim, and `test_system_scope_confers_no_database_access` pins that.

It is not a policy change either. Nothing on `tiktok_credentials` is relaxed by this revision --
no policy is created, altered or dropped. The shop-scoped qual stays exactly as strict as it is,
and the resolve comes to meet it.

HOW IT DIFFERS FROM `enumerate_expiring_credentials` (051), ITS SIBLING ON THIS TABLE.

Same table, same definer mechanics, same pinned `search_path`, same revoke-from-PUBLIC /
grant-to-`juli_app`. Three deliberate differences, each because the caller differs:

  1. **It returns the shop id alone**, where 051 returns `(credential_id, shop_id, expires_at)`.
     051's caller acts on the credential id directly (`refresh_credential(session,
     credential_id)`) and needs the expiry for its window. This caller's whole question is
     "which shop owns it" -- it then re-reads through `TikTokCredentialRepo.get_by_merchant`
     under that shop's scope, which keeps the cross-merchant guard (#1234), the newest-wins
     ordering and the canonical `NotFound` message in the one place they already live. A
     credential id would be a column nobody reads, on a function that bypasses RLS; ADR-089
     decision 4 calls a row type wider than it needs "a defect, not a convenience".

  2. **It answers with at most one row.** 051 is a work list. This is a lookup: `ORDER BY
     created_at DESC LIMIT 1` mirrors `_newest`, so the row the caller then reads under scope is
     the same row an unscoped read used to return. The fix restores the pre-RLS answer; it does
     not choose a new one.

  3. **It applies no status filter.** 051 excludes `needs_reauth` because the warm-keeping beat
     does not retry terminal rows. `get_by_merchant` has never filtered on status, and adding
     one here would turn "credential present but needs re-auth" from a loud vendor failure into
     a silent `NotFound` -- a behaviour change smuggled in under a fix.

Both arguments narrow and cannot widen: each is an equality filter applied on top of the query,
so no argument value returns more than the unfiltered query would. Neither is spelled into the
schema as a literal -- `PRODUCTION_AUTH_ID` and `SANDBOX_AUTH_ID` are application configuration
(`integrations/tiktok`), and pinning them in a migration would make rotating a merchant
authorization a schema change.

The parameters are named `merchant` and `wanted_capability` rather than after their columns, for
the reason 051 prefixes its OUT parameters `out_`: inside a function, an unqualified name that
matches both a parameter and a column is ambiguous, and Postgres either errors or silently
compares a column to itself.

EXPAND-ONLY AND REVERSIBLE (ADR-027). Creates one function and narrows its grants. No table, no
column, no data and no policy is touched, so `downgrade()` is a `DROP FUNCTION` and the grants go
with it -- nothing can be lost by running it.

APPLY THIS BEFORE THE CODE DEPLOY, NOT AFTER. `_enumerate_owning_shop` branches on the DIALECT,
not on whether this function exists, so the resolve raises `asyncpg.UndefinedFunctionError`
against a Postgres that has not run this revision -- measured during #2019 review, not assumed.
There is deliberately no existence probe and no silent fallback: falling back would restore the
scope-less read this revision exists to remove, and would do it invisibly. Because the revision
is expand-only and nothing calls the function until the code lands, applying it early is free.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "061_credential_owner_enum"
down_revision: str | None = "060_processed_events_epoch"
branch_labels: str | None = None
depends_on: str | None = None

ROLE_NAME = "juli_app"

# Named once so the grant loop and the downgrade cannot drift from what upgrade() creates --
# the same reason 051 keeps a `_FUNCTIONS` tuple.
FUNCTION_SIGNATURE = "enumerate_credential_owner_shop(text, text)"


def _create_function() -> None:
    """Create the enumeration.

    The OUT parameter is prefixed `out_` so the body can reference `shop_id` as a real column:
    inside a function returning `shop_id`, an unqualified `shop_id` resolves to the OUT
    parameter and silently compares a column to itself.
    """
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_credential_owner_shop(
        merchant text,
        wanted_capability text
    )
    RETURNS TABLE (
        out_shop_id uuid
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT c.shop_id
          FROM public.tiktok_credentials AS c
         WHERE c.merchant_authorization_id = merchant
           AND c.capability = wanted_capability
         ORDER BY c.created_at DESC
         LIMIT 1
      $fn$;
    """)


def _restrict_execute() -> None:
    """Take EXECUTE from PUBLIC and give it only to the runtime role.

    Postgres grants EXECUTE to PUBLIC by default on a new function. On a SECURITY DEFINER
    function that bypasses RLS, that default hands the bypass to every role in the cluster,
    including read-only and per-developer roles that do not exist yet. This is the most
    important statement in the revision.

    Guarded on the role existing for the reason 043 guards CREATE ROLE: roles are cluster-global
    while migrations are per-database, so a database in the same cluster that has not run 043
    would fail an unguarded GRANT.
    """
    # nosec B608: the signature comes from the module constant above -- never a parameter, never
    # reachable from a request. A function signature cannot be bound as a query parameter.
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
    """Create the enumeration, then narrow who may execute it."""
    _create_function()
    _restrict_execute()


def downgrade() -> None:
    """Drop it. Its grants go with it."""
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION_SIGNATURE};")  # nosec B608
