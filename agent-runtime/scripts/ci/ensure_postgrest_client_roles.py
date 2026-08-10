#!/usr/bin/env python3
"""Idempotently create the Supabase PostgREST client roles in CI Postgres (#897).

021_medallion_schemas and 029_close_public_schema_defaults both gate their
REVOKE/ALTER DEFAULT PRIVILEGES statements behind
``IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '<role>')`` so the migrations
stay reversible on plain Postgres, where ``anon``/``authenticated`` never exist.
That guard means the medallion revokes have been silently skipped on every CI run
to date (ADR-061 decision 2). Creating the roles here, before ``alembic upgrade
head`` runs, gives them their first real test coverage and lets
``check_public_schema_privileges.py`` assert against a live privilege state.

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

_CREATE_ROLE_SQL = """
DO $ensure_role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
    CREATE ROLE {role} NOLOGIN;
  END IF;
END
$ensure_role$;
"""  # nosec B608 — role is a fixed module constant, never interpolated user input


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
