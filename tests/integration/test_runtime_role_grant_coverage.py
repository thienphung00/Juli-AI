"""The runtime role's grants must cover what the runtime path actually does (#1453).

`juli_app` is granted table by table, migration by migration. That is the right shape —
ADR-086 decision 8 wants a DML-only, least-privilege map, and a blanket
`GRANT ... ON ALL TABLES` would hand the runtime role verbs it never uses. But a hand-written
map goes stale exactly the way the isolation list in
`tests/unit/test_destructive_migration_isolation.py` did, and for the same reason: a later
migration adds a table and forgets its grants.

That is not hypothetical here. It has now happened twice on the W7 wave:

  - Migration 045 enabled RLS but missed two tenant-scoped tables; #1329's proof caught it,
    and 046 fixed it.
  - Migration 044 created `production_write_authorizations` and granted `juli_app` nothing;
    this was found by reading production privileges by hand on 2026-09-01, AFTER the wave had
    merged, deployed, and passed every CI gate. 048 fixes it.

Both were caught by someone looking, not by a test. This file is the test.

WHY IT ASSERTS COVERAGE RATHER THAN AN EXACT SET.

Asserting an exact privilege set per table would restate the migrations in a second place, and
the copy would be what breaks. What actually has to hold is weaker and more useful: every
tenant-scoped table the runtime reads must be SELECT-able by the runtime role. A missing grant
is a runtime `permission denied`; an extra grant is a separate, narrower concern that
`test_juli_app_role_downgrade_cross_database.py` and ADR-086's review already cover.

WHY IT IS NOT SKIPPED WHEN `juli_app` IS ABSENT.

An earlier draft skipped when the role did not exist. That is the attested-versus-executed
failure this repository keeps hitting: the role is created by migration 043, so on a database
at head it is always present, and "the role is missing" means the migration chain did not run
— which should fail loudly rather than quietly skip the only test that reads these grants.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

ROLE_NAME = "juli_app"

# Tables the runtime writes as well as reads, with the verb it needs beyond SELECT.
# Kept deliberately short: each entry is a claim about a code path, and an entry
# nobody can point at a caller for is an entry that should not be here.
_RUNTIME_WRITE_VERBS: dict[str, str] = {
    # ProductionWriteAuthorizationsRepo.consume(): SELECT ... FOR UPDATE, then
    # sets consumed_at and consumed_by_run_id (#1453).
    "public.production_write_authorizations": "UPDATE",
}

# Tables classified tenant-scoped that the runtime legitimately never reads.
# Each needs a reason, because "it is not read" is exactly what someone would
# claim about a table whose grant they forgot — which is #1453 itself. An entry
# here is a claim that the migration's grant is deliberate, and 043/054's
# GRANT_MAP is where that claim is checked.
_NOT_READ_BY_RUNTIME: dict[str, str] = {
    # All tables in public/bronze/silver/ops/gold that carry explicit grants
    # are either read by runtime or deliberately read-protected (e.g. webhook_raw_events).
    # Bronze raw payloads were removed here in #1548: they are append-only
    # (043 INSERT), read by the medallion path (054 SELECT).
}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


requires_postgres = pytest.mark.skipif(
    not _database_url().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)


@pytest.fixture(scope="module")
def runtime_grants_engine() -> Iterator[Engine]:
    """A plain read-only engine on the shared database.

    Deliberately NOT `postgres_at_head` imported from `test_migrations.py`. That
    fixture downgrades to base, so importing it would make this module
    destructive-by-inheritance — the exact pattern
    `test_destructive_migration_isolation.py` now detects, and it would force
    this module onto a private database for no reason. Every query here is a
    catalog read; the shared database is already guaranteed at head by the
    session fixture in `tests/conftest.py`.
    """
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(_database_url()))
    try:
        yield engine
    finally:
        engine.dispose()


def _tenant_scoped_tables() -> list[str]:
    """Schema-qualified names.

    `has_table_privilege` resolves a bare name through `search_path`, so a
    `gold.` or `bronze.` table passed unqualified raises `UndefinedTable` rather
    than returning False — an error that reads like a broken test instead of a
    missing grant. The classification map is keyed by (schema, table); keep both.
    """
    return sorted(
        f"{schema}.{table}"
        for (schema, table), classification in TABLE_CLASSIFICATION_MAP.items()
        if classification in {"tenant_direct", "tenant_via_parent"}
        and f"{schema}.{table}" not in _NOT_READ_BY_RUNTIME
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_the_runtime_role_can_read_every_tenant_scoped_table(runtime_grants_engine) -> None:
    """A missing SELECT is a runtime `permission denied`, not a test failure.

    This is the assertion that would have caught #1453 before the cutover rather
    than during it.
    """
    with runtime_grants_engine.connect() as conn:
        role_exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE_NAME}
        ).scalar()
        assert role_exists, (
            f"{ROLE_NAME} does not exist. Migration 043 creates it, so on a database at head "
            "it is always present — its absence means the chain did not run, which must fail "
            "loudly rather than skip the only test that reads these grants."
        )

        missing = []
        for table in _tenant_scoped_tables():
            has_select = conn.execute(
                text("SELECT has_table_privilege(:r, :t, 'SELECT')"),
                {"r": ROLE_NAME, "t": table},
            ).scalar()
            if not has_select:
                missing.append(table)

    assert not missing, (
        f"{ROLE_NAME} cannot SELECT these tenant-scoped tables, so the runtime path hits "
        f"`permission denied` the moment it reaches one: {missing}. A migration that creates a "
        "tenant-scoped table must grant the runtime role its verbs in the same migration — "
        "043's grant map cannot cover a table that did not exist when it ran (#1453)."
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_the_runtime_role_holds_the_write_verbs_its_repos_use(runtime_grants_engine) -> None:
    """SELECT alone is not enough where the runtime mutates a row.

    `production_write_authorizations` is the case in point: `consume()` takes
    `SELECT ... FOR UPDATE` and writes `consumed_at`, so a SELECT-only grant
    would pass the test above and still fail #1339 observation 3.
    """
    with runtime_grants_engine.connect() as conn:
        missing = []
        for table, verb in _RUNTIME_WRITE_VERBS.items():
            has_verb = conn.execute(
                text("SELECT has_table_privilege(:r, :t, :v)"),
                {"r": ROLE_NAME, "t": table, "v": verb},
            ).scalar()
            if not has_verb:
                missing.append(f"{table}:{verb}")

    assert not missing, (
        f"{ROLE_NAME} is missing write verbs its repositories use: {missing}. "
        "Each entry here names a real caller — see _RUNTIME_WRITE_VERBS."
    )


@requires_postgres
@pytest.mark.migration_heavy
def test_the_runtime_role_is_not_granted_verbs_it_never_uses(runtime_grants_engine) -> None:
    """Least privilege, asserted in the direction that actually erodes.

    Grants accumulate: the easy fix for any `permission denied` is a wider GRANT,
    and nothing pushes back. `production_write_authorizations` is issued and
    revoked by an operator CLI that takes `--db-url`, so the runtime role must
    never hold INSERT or DELETE on it.
    """
    with runtime_grants_engine.connect() as conn:
        over_granted = []
        for verb in ("INSERT", "DELETE"):
            has_verb = conn.execute(
                text("SELECT has_table_privilege(:r, :t, :v)"),
                {"r": ROLE_NAME, "t": "public.production_write_authorizations", "v": verb},
            ).scalar()
            if has_verb:
                over_granted.append(verb)

    assert not over_granted, (
        f"{ROLE_NAME} holds {over_granted} on production_write_authorizations. Authorizations "
        "are issued and revoked by an operator through "
        "services/operations/production_write_authorizations_cli.py, which takes --db-url and "
        "is run with an admin URL. The runtime role consumes an authorization; it never "
        "creates or deletes one (ADR-086 decision 8)."
    )
