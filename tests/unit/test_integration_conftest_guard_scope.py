"""The destructive-database guard is scoped to the destructive tests.

Issue #734 added a non-local-host check so `alembic downgrade base` can
never run against a remote database. It was installed as
`tests/integration/conftest.py::pytest_configure`, which fires once for the
whole session on nothing more than `DATABASE_URL` being set — so selecting
any *single* non-destructive test in that directory tripped it too.

That mattered because the guard's error message names exactly one way
forward: `ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1`. The only database with real
TikTok credentials in it is remote, so running a live smoke against it
appeared to require setting a flag that authorises dropping every table in
that same database. The guard was pushing operators toward the disaster it
exists to prevent.

These tests pin the rescope in both directions: still fatal when a
destructive test is selected, inert when one is not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST_PATH = REPO_ROOT / "tests" / "integration" / "conftest.py"

REMOTE_URL = "postgresql://user:pw@aws-1-us-west-2.pooler.supabase.com:5432/postgres"
LOCAL_URL = "postgresql://user@localhost:5432/postgres"


def _load_integration_conftest():
    """Import the integration conftest as a plain module.

    Loaded by path rather than imported as `tests.integration.conftest` so
    this unit test never drags pytest's own conftest-collection machinery
    (or the integration directory's fixtures) into the unit tier.
    """
    spec = importlib.util.spec_from_file_location("_integration_conftest", CONFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _item(filename: str):
    """The only attribute the hook reads off a collected item."""
    return SimpleNamespace(path=SimpleNamespace(name=filename))


@pytest.fixture
def conftest_module():
    return _load_integration_conftest()


class TestTheGuardStillFiresWhereItMatters:
    def test_destructive_module_selected_against_a_remote_host_raises(
        self, conftest_module, monkeypatch
    ):
        monkeypatch.setenv("DATABASE_URL", REMOTE_URL)
        with pytest.raises(RuntimeError, match="refuse non-local hosts"):
            conftest_module.pytest_collection_modifyitems(
                session=None,
                config=None,
                items=[
                    _item("test_agent_live_smoke_sandbox_write.py"),
                    _item("test_migrations.py"),
                ],
            )

    def test_destructive_module_against_localhost_is_allowed(self, conftest_module, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", LOCAL_URL)
        conftest_module.pytest_collection_modifyitems(
            session=None, config=None, items=[_item("test_migrations.py")]
        )


class TestTheGuardIsInertForNonDestructiveSelections:
    def test_a_live_smoke_against_a_remote_host_is_not_blocked(self, conftest_module, monkeypatch):
        """The whole point: this selection cannot drop a table, so it must
        not be forced to set `ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1` on a
        database that holds real credentials."""
        monkeypatch.setenv("DATABASE_URL", REMOTE_URL)
        conftest_module.pytest_collection_modifyitems(
            session=None,
            config=None,
            items=[
                _item("test_agent_live_smoke_sandbox_write.py"),
                _item("test_agent_live_smoke_read_only.py"),
            ],
        )

    def test_no_database_url_is_not_blocked(self, conftest_module, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        conftest_module.pytest_collection_modifyitems(
            session=None, config=None, items=[_item("test_migrations.py")]
        )


class TestTheDirectoryWideHookIsGone:
    def test_pytest_configure_no_longer_validates_the_session(self, conftest_module):
        """A `pytest_configure` reintroduced here would restore the
        session-wide behaviour whatever this file's other tests assert, so
        its absence is pinned directly."""
        assert not hasattr(conftest_module, "pytest_configure"), (
            "tests/integration/conftest.py defines pytest_configure again -- the "
            "destructive-database guard must stay scoped to a selection that "
            "actually includes the destructive module"
        )
