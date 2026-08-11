#!/usr/bin/env python3
"""Idempotently create the Supabase PostgREST client roles in CI Postgres and seed
Supabase's project-bootstrap grant (#897, #929).

021_medallion_schemas and 032_close_public_schema_defaults both gate their
REVOKE/ALTER DEFAULT PRIVILEGES statements behind
``IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '<role>')`` so the migrations
stay reversible on plain Postgres, where ``anon``/``authenticated`` never exist.
That guard means the medallion revokes have been silently skipped on every CI run
to date (ADR-061 decision 2). Creating the roles here, before ``alembic upgrade
head`` runs, gives them their first real test coverage and lets
``check_public_schema_privileges.py`` assert against a live privilege state.

**Issue #929**: role creation alone is not enough to prove migration 029's
``ALTER DEFAULT PRIVILEGES ... REVOKE ALL`` clause does anything. Vanilla
``postgres:16`` never auto-grants table privileges to non-owner roles, so a
brand-new ``public`` table is already unreachable to ``anon``/``authenticated``
on a fresh cluster — there is nothing for that clause to counteract. The grant
it exists to reverse is **Supabase's project-bootstrap grant**
(``GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated`` +
matching ``ALTER DEFAULT PRIVILEGES``), applied automatically when a hosted
Supabase project is created — something ``postgres:16`` in CI has never had.
``seed_supabase_bootstrap_grants`` below reproduces that grant so the CI
substrate is representative of the real hosted project. Do **not** delete this
as "redundant setup" — without it, migration 029's default-privileges clause
(the entire thesis of ADR-061 decision 1: future tables are born closed) is
trusted rather than tested. See issue #929 for the live before/after proof.

Usage:
    DATABASE_URL=postgresql://... python agent-runtime/scripts/ci/ensure_postgrest_client_roles.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from sqlalchemy import create_engine, text  # noqa: E402

from juli_backend.core.config.runtime import sync_database_url  # noqa: E402

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")
BOOTSTRAP_SEED_SCHEMA = "public"

_CREATE_ROLE_SQL = """
DO $ensure_role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    CREATE ROLE {role} NOLOGIN;
  END IF;
END
$ensure_role$;
"""  # nosec B608 — role is a fixed module constant, never interpolated user input

# Mirrors 032_close_public_schema_defaults._restore_bootstrap_grants byte-for-byte
# (that function documents itself as reproducing "the way Supabase's own bootstrap
# SQL leaves it") — this is the same shape, run BEFORE any migration, to simulate
# Supabase's project-bootstrap grant rather than a migration's downgrade remedy.
_SEED_BOOTSTRAP_GRANT_SQL = """
DO $seed_bootstrap$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    GRANT USAGE ON SCHEMA {schema} TO {role};
    GRANT ALL ON ALL TABLES IN SCHEMA {schema} TO {role};
    GRANT ALL ON ALL SEQUENCES IN SCHEMA {schema} TO {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO {role};
    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON SEQUENCES TO {role};
  END IF;
END
$seed_bootstrap$;
"""  # nosec B608 — schema/role are fixed module constants


def ensure_roles(database_url: str) -> list[str]:
    """Create any missing PostgREST client role; return the roles that were created."""
    engine = create_engine(sync_database_url(database_url))
    created: list[str] = []
    try:
        with engine.begin() as conn:
            for role in POSTGREST_CLIENT_ROLES:
                existed = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                    {"role": role},
                ).first()
                conn.execute(text(_CREATE_ROLE_SQL.format(role=role)))
                if existed is None:
                    created.append(role)
    finally:
        engine.dispose()
    return created


def seed_supabase_bootstrap_grants(database_url: str, schema: str = BOOTSTRAP_SEED_SCHEMA) -> None:
    """Simulate Supabase's project-bootstrap grant on `schema` (#929).

    Must run BEFORE any Alembic migration executes, against the same role the
    migrations themselves connect as: ``ALTER DEFAULT PRIVILEGES`` only affects
    objects later created by the role that issued it, so seeding under a
    different role than the one running ``alembic upgrade`` would silently do
    nothing. Idempotent and safe to call every CI run — it only touches
    anon/authenticated privileges, never the backend's own pooler role.
    """
    engine = create_engine(sync_database_url(database_url))
    try:
        with engine.begin() as conn:
            for role in POSTGREST_CLIENT_ROLES:
                conn.execute(text(_SEED_BOOTSTRAP_GRANT_SQL.format(schema=schema, role=role)))
    finally:
        engine.dispose()


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("ensure_postgrest_client_roles: DATABASE_URL is not set", file=sys.stderr)
        return 1

    created = ensure_roles(database_url)
    if created:
        print(f"ensure_postgrest_client_roles: created {', '.join(created)}")
    else:
        print("ensure_postgrest_client_roles: anon/authenticated already present")

    seed_supabase_bootstrap_grants(database_url)
    print(
        "ensure_postgrest_client_roles: seeded Supabase-equivalent bootstrap grants "
        f"on schema '{BOOTSTRAP_SEED_SCHEMA}' (simulates Supabase project bootstrap, #929)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
