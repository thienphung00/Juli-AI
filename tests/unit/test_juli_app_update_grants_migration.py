"""Migration round-trip and contract checks for `058_juli_app_update_grants` (#1897).

Modelled on `test_workflow_run_rollup_migration.py` (the newest round-trip in
the tree) with one deliberate difference: 058 grants privileges and touches no
schema and no data, so the round trip goes

    head -> downgrade 057 -> upgrade head

rather than resetting to base. Nothing here drops a table, so this module is
NOT in `tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES` and does not need a
database of its own. The subject of the assertions is the grant surface, which
is exactly what `downgrade` and `upgrade` move.

File-content assertions need no database and always run. The rest is gated by
`requires_postgres` and skips cleanly where `DATABASE_URL` is not Postgres.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from juli_backend.core.config.runtime import sync_database_url
from tests.support.postgres import RUNTIME_ROLE, database_url, requires_postgres

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_058_PATH = MIGRATIONS_DIR / "058_juli_app_update_grants.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

#: The six tables 058 grants UPDATE on, and nothing else.
GRANTED_TABLES = (
    "alert_configs",
    "campaigns",
    "demo_execution_records",
    "graph_edges",
    "run_confirmations",
    "shops",
)

#: 043's grants, which downgrade must leave alone.
_PRESERVED = ("SELECT", "INSERT")


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(database_url()))
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(database_url()), pool_pre_ping=True)


def _assert_local_database_url() -> None:
    """Refuse to move an alembic revision on anything but a local, disposable
    Postgres -- issue #734's discipline, reproduced rather than imported."""
    hostname = urlparse(database_url()).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing an Alembic downgrade against a non-local DATABASE_URL host "
            f"({hostname}); this test only ever moves a throwaway local database."
        )


def _privileges(engine: Engine, table: str) -> set[str]:
    sql = text(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = :role AND table_schema = 'public' AND table_name = :table"
    )
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(sql, {"role": RUNTIME_ROLE, "table": table})}


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_058_revision_equals_filename_stem():
    assert MIGRATION_058_PATH.exists(), f"missing {MIGRATION_058_PATH}"
    body = MIGRATION_058_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 058 has no `revision: str = ...` line"
    assert rev.group(1) == "058_juli_app_update_grants"
    assert rev.group(1) == MIGRATION_058_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32)"
    )


def test_migration_058_down_revision_is_057():
    body = MIGRATION_058_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 058 has no string `down_revision`"
    assert down.group(1) == "057_workflow_run_rollup"


def test_migration_058_grants_update_only_and_never_delete():
    """Least privilege, checked in the source rather than assumed.

    The audit found no `delete(Model)` and no `session.delete` on any mapped
    table, so a DELETE appearing in this map would be unjustified by any call
    site -- exactly the "grant blindly" failure the issue warns against.
    """
    body = MIGRATION_058_PATH.read_text(encoding="utf-8")
    grant_map = body.split("GRANT_MAP: GrantMap = {")[1].split("\n}")[0]

    assert "DELETE" not in grant_map.upper()
    assert "TRUNCATE" not in grant_map.upper()
    for table in GRANTED_TABLES:
        assert f'"{table}": ("UPDATE",)' in grant_map, f"{table} is not granted UPDATE"


def test_migration_058_is_guarded_on_the_role_and_the_table():
    """A cluster whose database has not run 043 has no `juli_app`; an unguarded
    GRANT would fail there. 048 guards on `pg_roles`, 043/054/055 on `pg_tables`;
    058 needs both."""
    body = MIGRATION_058_PATH.read_text(encoding="utf-8")
    assert "pg_roles" in body
    assert "pg_tables" in body
    assert body.count("IF EXISTS") >= 1


def test_migration_058_still_leaves_a_single_alembic_head():
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()

    assert len(heads) == 1, f"058 branched the revision chain: heads={heads}"
    assert heads[0] == "058_juli_app_update_grants"


def test_migration_058_satisfies_the_additive_gate():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_058_PATH])

    assert result.accepted, result.report()


# ---------------------------------------------------------------------------
# Postgres-backed round trip.
# ---------------------------------------------------------------------------


@requires_postgres
def test_migration_058_upgrade_downgrade_upgrade_round_trips_cleanly():
    """`head` -> `downgrade 057` -> `upgrade head` restores exactly the six
    UPDATE grants, and takes nothing else away on the way down."""
    _assert_local_database_url()
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        command.upgrade(cfg, "058_juli_app_update_grants")
        at_head = {table: _privileges(engine, table) for table in GRANTED_TABLES}
        for table, held in at_head.items():
            assert "UPDATE" in held, f"{table} has no UPDATE at head: {sorted(held)}"

        command.downgrade(cfg, "057_workflow_run_rollup")
        after_downgrade = {table: _privileges(engine, table) for table in GRANTED_TABLES}
        for table, held in after_downgrade.items():
            assert "UPDATE" not in held, f"downgrade left UPDATE on {table}"
            for privilege in _PRESERVED:
                assert privilege in held, (
                    f"downgrade revoked more than it should on {table}: "
                    f"{privilege} is gone, leaving {sorted(held)}"
                )

        command.upgrade(cfg, "058_juli_app_update_grants")
        after_reupgrade = {table: _privileges(engine, table) for table in GRANTED_TABLES}

        assert after_reupgrade == at_head, (
            "re-upgrading to 058 produced a different privilege set than the "
            f"original upgrade did: {after_reupgrade} != {at_head}"
        )
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()


@requires_postgres
def test_migration_058_upgrade_is_idempotent_over_grants_already_held():
    """Re-running the GRANT on a table that already holds UPDATE must be a no-op.

    `command.upgrade` twice proves nothing -- alembic simply skips the second.
    So the version table is STAMPED back to 057 while the privileges stay in
    place, and 058 is then run against a database that already satisfies it.
    That is the real shape of a re-applied migration, and the property 043, 054
    and 055 each claim for their own guarded GRANT.
    """
    _assert_local_database_url()
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        command.upgrade(cfg, "head")
        before = {table: _privileges(engine, table) for table in GRANTED_TABLES}

        command.stamp(cfg, "057_workflow_run_rollup")
        command.upgrade(cfg, "058_juli_app_update_grants")
        after = {table: _privileges(engine, table) for table in GRANTED_TABLES}

        assert after == before, f"re-applying 058 changed the grant surface: {after} != {before}"
        assert all("UPDATE" in held for held in after.values())
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
