"""Migration round-trip checks for #1653 / W8-A / P10-1 (migration
`057_workflow_run_rollup`) -- the six additive, nullable rollup columns on
`workflow_runs`: `input_tokens`, `output_tokens`, `cost_usd`, `duration_ms`,
`tool_call_count`, `rows_affected`.

File-content assertions (revision string, down_revision, revision-id length)
need no database and always run. Everything else is gated by
`requires_postgres` (reused from `tests/integration/test_migrations.py`, the
same gate every other migration-shaped test in this repo already uses) and
skips cleanly wherever `DATABASE_URL` is not a reachable local Postgres.

The round-trip test resets its own dedicated engine back to
`056_series_source_column` (a downgrade local to whatever *disposable*
database `DATABASE_URL` names) before upgrading to head again -- guarded by
`_assert_local_database_url`, the same "never touch a non-local host"
discipline `tests/integration/test_migrations.py` established for issue
#734 and `test_workflow_runs_schema.py` reuses verbatim for `056`/`057`.

This module calls `command.downgrade(cfg, "base")` (via `_reset_to_revision`),
so it is listed in `tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES` and
runs against a database of its own (`_isolated_migration_database`), never
the shared one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from juli_backend.core.config.runtime import sync_database_url
from tests.integration.test_migrations import postgres_at_head, requires_postgres

__all__ = ["postgres_at_head", "requires_postgres"]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION_057_PATH = MIGRATIONS_DIR / "057_workflow_run_rollup.py"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

_ROLLUP_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "duration_ms",
    "tool_call_count",
    "rows_affected",
)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _sync_engine() -> Engine:
    return create_engine(sync_database_url(_database_url()), pool_pre_ping=True)


def _assert_local_database_url(url: str) -> None:
    """Refuse to downgrade against anything but a local, disposable Postgres
    -- issue #734's discipline, reproduced here rather than importing a
    private helper from another test module."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname}); this test only ever downgrades a "
            "throwaway local database."
        )


def _reset_to_revision(cfg: Config, revision: str) -> None:
    _assert_local_database_url(_database_url())
    command.downgrade(cfg, "base")
    command.upgrade(cfg, revision)


def _columns_by_name(engine: Engine, table: str, schema: str | None = None) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns(table, schema=schema)}


# ---------------------------------------------------------------------------
# File-content assertions -- no database needed.
# ---------------------------------------------------------------------------


def test_migration_057_revision_equals_filename_stem():
    assert MIGRATION_057_PATH.exists(), f"missing {MIGRATION_057_PATH}"
    body = MIGRATION_057_PATH.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert rev is not None, "migration 057 has no `revision: str = ...` line"
    assert rev.group(1) == "057_workflow_run_rollup"
    assert rev.group(1) == MIGRATION_057_PATH.stem
    assert len(rev.group(1)) <= 32, (
        f"revision id {rev.group(1)!r} is {len(rev.group(1))} chars -- "
        "alembic_version.version_num is VARCHAR(32)"
    )


def test_migration_057_down_revision_is_056():
    body = MIGRATION_057_PATH.read_text(encoding="utf-8")
    down = re.search(r'^down_revision: str \| None = "([^"]+)"', body, re.M)
    assert down is not None, "migration 057 has no string `down_revision`"
    assert down.group(1) == "056_series_source_column"


# ---------------------------------------------------------------------------
# Postgres-backed schema assertions.
# ---------------------------------------------------------------------------


@requires_postgres
def test_rollup_columns_exist_and_are_nullable_at_head(postgres_at_head: Engine):
    columns = _columns_by_name(postgres_at_head, "workflow_runs")
    for name in _ROLLUP_COLUMNS:
        assert name in columns, f"missing rollup column: {name}"
        assert columns[name]["nullable"] is True, (
            f"{name} must be nullable -- a pre-existing run predates the rollup "
            "and must read NULL, never a fabricated 0 (#1653)"
        )


@requires_postgres
def test_migration_057_upgrade_downgrade_upgrade_round_trips_cleanly():
    """`upgrade head` -> `downgrade 056_series_source_column` -> `upgrade
    head` round-trips the six rollup columns cleanly on a real Postgres, and
    touches nothing else on `workflow_runs`."""
    cfg = _alembic_config()
    engine = _sync_engine()
    try:
        _reset_to_revision(cfg, "057_workflow_run_rollup")
        columns_at_head = _columns_by_name(engine, "workflow_runs")
        for name in _ROLLUP_COLUMNS:
            assert name in columns_at_head, f"missing rollup column at head: {name}"
            assert columns_at_head[name]["nullable"] is True

        non_rollup_columns_at_head = {
            name: info for name, info in columns_at_head.items() if name not in _ROLLUP_COLUMNS
        }

        command.downgrade(cfg, "056_series_source_column")
        columns_after_downgrade = _columns_by_name(engine, "workflow_runs")
        for name in _ROLLUP_COLUMNS:
            assert name not in columns_after_downgrade, (
                f"downgrade() did not drop rollup column: {name}"
            )
        # Nothing else on the table moved: same column set (minus the six),
        # same types, same nullability.
        for name, before_info in non_rollup_columns_at_head.items():
            assert name in columns_after_downgrade, (
                f"downgrade() dropped an unrelated column: {name}"
            )
            after_info = columns_after_downgrade[name]
            assert str(before_info["type"]) == str(after_info["type"]), (
                f"downgrade() changed the type of unrelated column {name}: "
                f"{before_info['type']} -> {after_info['type']}"
            )
            assert before_info["nullable"] == after_info["nullable"], (
                f"downgrade() changed the nullability of unrelated column {name}: "
                f"{before_info['nullable']} -> {after_info['nullable']}"
            )
        assert set(columns_after_downgrade) == set(non_rollup_columns_at_head), (
            "downgrade() left the table with a different column set than "
            "'at head minus the six rollup columns'"
        )

        command.upgrade(cfg, "057_workflow_run_rollup")
        columns_after_reupgrade = _columns_by_name(engine, "workflow_runs")
        for name in _ROLLUP_COLUMNS:
            assert name in columns_after_reupgrade, (
                f"re-upgrade did not restore rollup column: {name}"
            )
            assert columns_after_reupgrade[name]["nullable"] is True
        assert set(columns_after_reupgrade) == set(columns_at_head), (
            "re-upgrading to 057 produced a different column set than the original upgrade did"
        )
    finally:
        engine.dispose()
