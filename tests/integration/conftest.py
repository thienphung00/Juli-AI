"""Shared fixtures for integration tests under ``tests/integration/``."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.integrations.tiktok.auth import TikTokAuth
from tests.integration.tiktok_sandbox import (
    sandbox_app_key,
    sandbox_app_secret,
)

#: The module whose tests actually run `alembic downgrade base`. The
#: non-local-host guard belongs to *these* tests, not to the directory.
_DESTRUCTIVE_TEST_MODULE = "test_migrations.py"


def pytest_collection_modifyitems(session, config, items):
    """Guard against destructive migration tests pointing at non-local databases.

    Runs after collection and before any test executes, so a destructive run
    against a remote database still dies before it can drop a table. Issue
    #734; rescoped from `pytest_configure` because that hook fires for the
    *session*, not for a selection.

    **Why the rescope matters.** The old hook validated on nothing more than
    `DATABASE_URL` being set — its own comment read "only validate if
    migration tests will run (DATABASE_URL is set)", but those are not the
    same condition. Selecting a single non-destructive live smoke in this
    directory was enough to trip it, and the error it raised named exactly
    one escape hatch: `ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1`. So the
    documented way to run a read-only smoke against the only database that
    has real credentials in it was to set a flag whose meaning is "you may
    run `alembic downgrade base` here" — against that same database. An
    operator following the message on production would arm precisely the
    catastrophe the guard exists to prevent. Scoping it to the destructive
    module removes the incentive without weakening the guard: every path
    that can actually drop a table is still checked.
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return
    if not any(item.path.name == _DESTRUCTIVE_TEST_MODULE for item in items):
        return

    # Import here to avoid circular imports
    from tests.integration.test_migrations import _validate_destructive_db_url

    _validate_destructive_db_url(database_url)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def bind_agent_abuse_limit_gate_for_integration_tests():
    """Default to a generous in-memory gate (ADR-075 decision 4, #1223) so
    every integration test that builds `create_app()` directly -- without
    running FastAPI's `lifespan()`, which is where `bind_agent_abuse_limit_gate()`
    normally runs (`api/main.py`) -- doesn't 500 with "Agent abuse-limit
    gate is not bound" the first time it hits approve, confirmations, or
    the SSE events route. Exact mirror of
    `tests/unit/conftest.py::bind_agent_abuse_limit_gate_for_unit_tests` --
    see that fixture's own docstring for why a permissive default (not
    "leave unbound") is correct here: these routes are exercised
    pervasively across many integration files
    (`test_agent_confirmation_decision_endpoint.py`,
    `test_agent_confirmation_decision_postgres.py`,
    `test_agent_events_streaming_matrix.py`), not by one dedicated caller.
    Production is unaffected -- uvicorn always runs `lifespan()` before
    serving traffic, so the real fail-closed `bind_agent_abuse_limit_gate()`
    binding is what actually answers `get_agent_abuse_limit_gate()` there.
    """
    from juli_backend.services.agent.abuse_limits import (
        InMemoryAbuseLimitGate,
        set_agent_abuse_limit_gate,
    )

    set_agent_abuse_limit_gate(
        InMemoryAbuseLimitGate(
            approve_max_requests=100_000,
            approve_burst_max_requests=100_000,
            confirmation_max_requests=100_000,
            sse_max_concurrent=100_000,
        )
    )
    yield
    set_agent_abuse_limit_gate(None)


@pytest.fixture(autouse=True)
def token_encryption_key(request, monkeypatch):
    """A deterministic encryption key for every test that mints its own
    credential rows — but never for a `live` test.

    `database/token_crypto.py` reads `TIKTOK_TOKEN_ENCRYPTION_KEY` from the
    environment at call time. A `live` smoke resolves a REAL stored
    credential (`resolve_sandbox_write_credential`) that was encrypted with
    the deployment's real key, so substituting the fake one here does not
    isolate the test — it decrypts to garbage and the smoke can never reach
    the vendor at all. Live tests therefore keep whatever key the
    environment actually carries; everything else keeps the fake, so no test
    that mints its own rows depends on a real secret being present.
    """
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("TIKTOK_TOKEN_ENCRYPTION_KEY", "unit-test-token-encryption-key")


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )

    def _create_tables(sync_conn):
        Base.metadata.create_all(sync_conn)

    async with eng.begin() as conn:
        await conn.run_sync(_create_tables)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def tiktok_auth_client() -> TikTokAuth:
    return TikTokAuth(app_key=sandbox_app_key(), app_secret=sandbox_app_secret())


# --------------------------------------------------------------------------
# Two-tenant Postgres fixtures (#1483 / ADR-089).
#
# Defined here rather than imported from `two_tenant.py` so consuming modules
# get them by name. Importing a fixture and then naming it as a parameter is an
# F811 redefinition, and the repository's existing workaround for that is a
# `# noqa: F401` — a suppression identity the ratchet (#1462) counts. conftest
# discovery avoids needing one.
#
# Both are module-scoped and lazy: a test that does not request them never
# opens a connection, so this costs nothing to the SQLite-backed majority of
# the integration suite.
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def owner_engine():
    """A sync engine connected as the table owner, on a database at head.

    Seeding runs as the owner deliberately: it is set-up, not the thing under
    test, and doing it under RLS would make a fixture failure look like an
    isolation failure.

    The migration is this fixture's job, not the session fixture's. A module
    using these fixtures is in `_ISOLATED_DATABASE_MODULES`, and
    `_isolated_migration_database` hands it an EMPTY database — it provisions,
    it does not migrate, because the destructive modules it was built for each
    run their own upgrade. Without this the first query is `UndefinedTable`.

    `ensure_roles` and `seed_supabase_bootstrap_grants` run before the upgrade
    for the same reason `tests/conftest.py` does it: `juli_app` has to exist
    before `SET ROLE` can reach it, and the CI substrate needs the grants.
    """
    import os
    import sys
    from pathlib import Path as _Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine as _create_engine

    from juli_backend.core.config.runtime import sync_database_url as _sync_url

    url = os.environ.get("DATABASE_URL", "").strip()
    sync_url = _sync_url(url)

    repo_root = _Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "agent-runtime" / "scripts" / "ci"))
    from ensure_postgrest_client_roles import (  # noqa: E402
        ensure_roles,
        seed_supabase_bootstrap_grants,
    )

    ensure_roles(url)
    seed_supabase_bootstrap_grants(url)

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(repo_root / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")

    engine = _create_engine(sync_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def two_tenants(owner_engine):
    """Two fully seeded tenants.

    Two, not one: with a single tenant "returned rows" and "returned every row"
    are the same observation, and telling them apart is the entire point.
    """
    from tests.integration.two_tenant import seed_tenant

    return (
        seed_tenant(owner_engine, label="tenant-a"),
        seed_tenant(owner_engine, label="tenant-b"),
    )
