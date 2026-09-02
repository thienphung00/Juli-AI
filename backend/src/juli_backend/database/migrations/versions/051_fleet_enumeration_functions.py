"""Enumeration functions for the three fleet-scoped beat tasks (#1487, ADR-089).

The fleet-scope exemption these replace is a Python flag and a log line — no `set_config`, no
`SET ROLE`, no SQL. Its correctness rested on the runtime connecting as the table owner, which
Postgres exempts from row policies, and W7 removes that exemption.

(The exemption is named in ADR-089 and in `database/tenant_context.py`. It is deliberately not
spelled here: `test_system_scope_call_sites_enumerated` finds call sites by scanning for the
name, so prose about it in any file under `backend/src` is counted as a call site. That guard
would be better written against the AST, the way `test_destructive_migration_isolation.py`
parses for `downgrade(..., "base")` rather than grepping — filed as follow-up rather than
changed here, because two slices are concurrently editing its expected set.) After the #1339 cutover, `credential_refresh_beat`,
`impact_reader` and `reaper` each read **zero rows** from every policied table and complete
having done nothing. #1467 turned that from a raise into a clean `0`, which makes the failure
quieter rather than better.

ADR-089's answer is per-tenant context for every data access, with the **only** cross-tenant read
being enumeration — returning identifiers and scheduling metadata, never tenant data. These are
those three enumerations. Nothing calls them yet; the three task-rewiring slices do.

WHY `SECURITY DEFINER` IS SAFE HERE, AND WHERE IT WOULD NOT BE.

A `SECURITY DEFINER` function executes as its owner. These are created by the migration, so they
are owned by the migration role — the table owner — which is exempt from RLS. That is the point:
the function sees across tenants so its caller does not have to.

It is a privilege boundary, and three properties keep it narrow:

  1. **Identifiers and scheduling metadata only.** No tokens, no payloads, no analytics values,
     no PII. `list_expiring_within` hydrates *decrypted* tokens; the enumeration deliberately
     does not, so the loop re-fetches per shop under real tenant context and decrypts there.
  2. **No dynamic SQL and a pinned `search_path`.** A definer function whose `search_path` a
     caller can influence is capturable by a schema earlier on that path.
  3. **`EXECUTE` revoked from `PUBLIC`, granted only to `juli_app`.** Postgres grants `EXECUTE`
     to `PUBLIC` by default on a new function. On a definer function that bypasses RLS, that
     default would hand the bypass to every role in the cluster — including any future read-only
     or per-developer role. It is the single most important part of this migration.

Arguments narrow and cannot widen: each is a filter applied on top of a fixed `WHERE`, so no
argument value returns more than the unfiltered query would.

WHY ONE MIGRATION RATHER THAN THREE.

Three slices each adding a migration means three `down_revision`s computed against a moving
head — the branched-head outage the W7 locks warn about. One migration here, and the three
task-rewiring slices carry no migration at all, so they can land in any order.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "051_fleet_enumeration_fns"
down_revision: str | None = "050_rls_guc_helpers"
branch_labels: str | None = None
depends_on: str | None = None

ROLE_NAME = "juli_app"

# Listed once so the grant loop and the downgrade cannot drift from what
# upgrade() creates.
_FUNCTIONS: tuple[str, ...] = (
    "enumerate_expiring_credentials(timestamp without time zone)",
    "enumerate_measurable_executions(text[])",
    "enumerate_active_workflow_runs()",
)


def _create_functions() -> None:
    """Create the three enumerations.

    OUT parameters are prefixed `out_` so the body can reference real columns
    unambiguously: inside a function returning `shop_id`, an unqualified
    `shop_id` resolves to the OUT parameter and silently compares a column to
    itself.
    """
    # credential_refresh_beat: mirrors TikTokCredentialRepo.list_expiring_within
    # — expiry inside the window, never a terminal `needs_reauth` row, which the
    # warm-keeping beat does not retry. Returns NO token material.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_expiring_credentials(
        cutoff timestamp without time zone
    )
    RETURNS TABLE (
        out_credential_id uuid,
        out_shop_id uuid,
        out_expires_at timestamp without time zone
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT c.id, c.shop_id, c.token_expires_at
          FROM public.tiktok_credentials AS c
         WHERE c.token_expires_at <= cutoff
           AND c.status <> 'needs_reauth'
         ORDER BY c.token_expires_at ASC
      $fn$;
    """)

    # impact_reader: mirrors load_measurable_executions, minus the full ORM row.
    # The pipeline needs payload_json and tool_name, but only AFTER it has an
    # execution to work on — those are fetched per-execution under tenant
    # context, so they stay out of the cross-tenant read.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_measurable_executions(
        measurable_tool_names text[]
    )
    RETURNS TABLE (
        out_execution_id uuid,
        out_shop_id uuid,
        out_updated_at timestamp without time zone
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT e.id, e.shop_id, e.updated_at
          FROM public.tool_executions AS e
         WHERE e.status = 'succeeded'
           AND e.tool_name = ANY(measurable_tool_names)
      $fn$;
    """)

    # reaper: mirrors _reap_stale_running_and_queued's scan. The staleness
    # comparison stays in Python, where the injectable `now` and the
    # TerminationPolicy live and where the existing tests drive it — moving the
    # threshold into SQL would duplicate a policy value those tests inject.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.enumerate_active_workflow_runs()
    RETURNS TABLE (
        out_run_id uuid,
        out_shop_id uuid,
        out_status varchar,
        out_created_at timestamp without time zone,
        out_running_seconds_elapsed integer
    )
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT r.id, r.shop_id, r.status, r.created_at, r.running_seconds_elapsed
          FROM public.workflow_runs AS r
         WHERE r.status IN ('queued', 'running')
      $fn$;
    """)


def _restrict_execute() -> None:
    """Take EXECUTE from PUBLIC and give it only to the runtime role.

    Guarded on the role existing for the same reason 043 guards CREATE ROLE:
    roles are cluster-global while migrations are per-database, so a database in
    the same cluster that has not run 043 would fail an unguarded GRANT.
    """
    for signature in _FUNCTIONS:
        # nosec B608: signature comes from the _FUNCTIONS constant above — never
        # a parameter, never reachable from a request. A function signature
        # cannot be bound as a query parameter.
        revoke = f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;"  # nosec B608
        op.execute(revoke)
        grant = f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
                EXECUTE 'GRANT EXECUTE ON FUNCTION public.{signature} TO {ROLE_NAME}';
            END IF;
        END
        $$;
        """  # nosec B608
        op.execute(grant)


def upgrade() -> None:
    """Create the enumerations, then narrow who may execute them."""
    _create_functions()
    _restrict_execute()


def downgrade() -> None:
    """Drop all three. Their grants go with them."""
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature};")  # nosec B608
