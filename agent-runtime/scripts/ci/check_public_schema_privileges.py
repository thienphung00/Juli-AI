#!/usr/bin/env python3
"""Fail the build if any table outside the `gold` allowlist is reachable by the
PostgREST client roles (#897 exit gate, ADR-061 decision 1).

This is a **live privilege query** against ``pg_catalog`` / role-privilege
functions — not a text search of migration files, so it catches drift regardless
of which migration (or manual `GRANT`) introduced it.

"Reachable" = the role has ``USAGE`` on the containing schema **and** at least one
of SELECT/INSERT/UPDATE/DELETE on the table/view/matview. Both conditions are
required: a dangling table-level grant without schema ``USAGE`` — e.g. the `SELECT`
024_gold_kpi_envelopes issued to anon/authenticated on ``gold.kpi_envelopes`` — is
correctly treated as *not* reachable, matching ADR-061's finding that no `USAGE`
grant on `gold` was ever issued and so no client-direct read path exists today.

The gold allowlist is intentionally the single serving surface ADR-046 designates
for client exposure (`gold.kpi_envelopes`) — nothing else, including
`gold.ml_feature_snapshots` (ML gold, explicitly revoked in 021_medallion_schemas).

Usage:
    DATABASE_URL=postgresql://... python agent-runtime/scripts/ci/check_public_schema_privileges.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from juli_backend.core.config.runtime import sync_database_url  # noqa: E402

POSTGREST_CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated")

# The gold serving surface is the single client-reachable allowlist entry
# (ADR-046 §5 "Serving gold"; ADR-061 decision 1, doNotInfer: "the allowlist stays
# explicit and narrow"). Nothing else — public, bronze, silver, ops, or any other
# gold table — may be reachable by anon/authenticated.
GOLD_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({("gold", "kpi_envelopes")})

_REACHABLE_TABLES_SQL = text(
    """
    SELECT n.nspname AS schema_name, c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'v', 'm', 'p', 'f')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND has_schema_privilege(:role, n.nspname, 'USAGE')
      AND (
        has_table_privilege(:role, c.oid, 'SELECT')
        OR has_table_privilege(:role, c.oid, 'INSERT')
        OR has_table_privilege(:role, c.oid, 'UPDATE')
        OR has_table_privilege(:role, c.oid, 'DELETE')
      )
    ORDER BY 1, 2
    """
)


def _existing_roles(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
            {"roles": list(POSTGREST_CLIENT_ROLES)},
        ).all()
    return {row[0] for row in rows}


def find_reachable_tables(engine: Engine, role: str) -> list[tuple[str, str]]:
    """All (schema, table) pairs `role` can actually reach — schema USAGE + a CRUD grant."""
    with engine.connect() as conn:
        rows = conn.execute(_REACHABLE_TABLES_SQL, {"role": role}).all()
    return [(row[0], row[1]) for row in rows]


def find_privilege_violations(database_url: str) -> dict[str, list[tuple[str, str]]]:
    """Return {role: [(schema, table), ...]} for every reachable object outside the allowlist.

    A role absent from the target database is silently skipped — matching the
    role-existence guard used throughout the medallion/public-schema migrations —
    rather than treated as a violation.
    """
    engine = create_engine(sync_database_url(database_url), pool_pre_ping=True)
    violations: dict[str, list[tuple[str, str]]] = {}
    try:
        existing_roles = _existing_roles(engine)
        for role in POSTGREST_CLIENT_ROLES:
            if role not in existing_roles:
                continue
            offending = [
                (schema, table)
                for schema, table in find_reachable_tables(engine, role)
                if (schema, table) not in GOLD_ALLOWLIST
            ]
            if offending:
                violations[role] = offending
    finally:
        engine.dispose()
    return violations


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print(
            "check_public_schema_privileges: DATABASE_URL is not set", file=sys.stderr
        )
        return 1

    violations = find_privilege_violations(database_url)
    if violations:
        print(
            "check_public_schema_privileges: FAIL — tables reachable by PostgREST "
            "client roles outside the gold allowlist:",
            file=sys.stderr,
        )
        for role, tables in violations.items():
            for schema, table in tables:
                print(f"  role={role} table={schema}.{table}", file=sys.stderr)
        return 1

    print(
        "check_public_schema_privileges: PASS — no table outside the gold "
        "allowlist is reachable by anon/authenticated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
