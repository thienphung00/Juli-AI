"""close public schema to PostgREST client roles by default (#897)

Revision ID: 032_close_public_schema_defaults
Revises: 031_inventory_items_velocity
Create Date: 2026-08-10

ADR-061 decision 1 — thirteen `public` tables (including `action_cards` and
`webhook_raw_events`, which has no `shop_id` column at all) have never had row-level
protection. `public` never received the `ALTER DEFAULT PRIVILEGES` treatment that
021_medallion_schemas gave bronze/silver/ops, so every table landing in `public`
since migration 006 inherited Supabase's permissive bootstrap grants — two more
(027_decision_emission_budget, 028_demo_execution_records) shipped unprotected in
the week before this audit.

This migration extends 021's role-guarded revoke helper (`_revoke_client_access`,
including its ``IF EXISTS (SELECT 1 FROM pg_roles ...)`` role-existence guard) to
`public`: REVOKE existing anon/authenticated privileges AND set
`ALTER DEFAULT PRIVILEGES` so every table/sequence landing in `public` from now on
is born closed, with no per-migration author action required. This also revokes the
dormant `SELECT` grant 024_gold_kpi_envelopes issued to anon/authenticated on the
`public.analytics_kpi_envelopes_compat` view — that view lives in `public`, so it is
covered by "REVOKE ALL ON ALL TABLES IN SCHEMA public" like every other object here.

Does NOT touch `gold` (no USAGE grant is added there — the client-reachable
allowlist stays explicit and narrow, per ADR-061) and does NOT add or repair
per-table RLS (deferred to 3.5-C). The backend's own connection is unaffected: it
authenticates as the Supabase pooler `postgres` role, never as `anon`/`authenticated`.

Downgrade is an availability remedy only (release-evidence-plan-issue-897.json
rollbackAssertion) — it restores the pre-migration Supabase-bootstrap-shaped grants
(GRANT ALL on schema/tables/sequences + matching default privileges) so the schema
still round-trips through `alembic downgrade -1 && alembic upgrade head`, but
re-opens the boundary this migration exists to close; any downgrade must be
followed by a fix-forward re-upgrade, never left standing.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "032_close_public_schema_defaults"
down_revision: str | None = "031_inventory_items_velocity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PUBLIC_SCHEMA = "public"
POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")


def _revoke_client_access(schema: str) -> None:
    """Mirrors 021_medallion_schemas._revoke_client_access verbatim (#603 pattern)."""
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $close_public$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    REVOKE ALL ON SCHEMA {schema} FROM {role};
    REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {role};
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {role};
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schema} FROM {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM {role};
  END IF;
END
$close_public$;
"""  # nosec B608 — schema/role are fixed module constants
        op.execute(sql)


def _restore_bootstrap_grants(schema: str) -> None:
    """Downgrade path — re-open `schema` the way Supabase's own bootstrap SQL

    leaves it (GRANT ALL to anon/authenticated, relying on RLS as the boundary).
    Availability remedy only; see module docstring.
    """
    for role in POSTGREST_CLIENT_ROLES:
        sql = f"""
DO $close_public$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    GRANT USAGE ON SCHEMA {schema} TO {role};
    GRANT ALL ON ALL TABLES IN SCHEMA {schema} TO {role};
    GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema} TO {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON SEQUENCES TO {role};
  END IF;
END
$close_public$;
"""  # nosec B608 — schema/role are fixed module constants
        op.execute(sql)


def upgrade() -> None:
    _revoke_client_access(PUBLIC_SCHEMA)


def downgrade() -> None:
    _restore_bootstrap_grants(PUBLIC_SCHEMA)
