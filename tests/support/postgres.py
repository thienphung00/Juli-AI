"""The one definition of "this test needs a real Postgres".

Thirty modules used to define ``_database_url`` and ``requires_postgres``
each; a change to the gate (say, making it fail closed in CI) had thirty
places to land. Import these instead.

Today the gate is *fail-open*: without a reachable ``DATABASE_URL`` the test
skips, in CI too. ``tests/conftest.py`` already refuses a non-disposable URL in
CI; refusing a *missing* one is the next step and is blocked on the
``-k "contract or boundary or ownership"`` job in ``pr.yml``, which runs unit
tests with no Postgres service and relies on these skips. Consolidating the
definition here is the prerequisite for flipping it in one place.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.core.config.runtime import async_database_url, sync_database_url

RUNTIME_ROLE = "juli_app"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def postgres_reachable() -> bool:
    return database_url().startswith("postgresql")


requires_postgres = pytest.mark.skipif(
    not postgres_reachable(),
    reason="DATABASE_URL does not point at a Postgres database",
)


# --- running a test as the deployed runtime role ---------------------------
#
# An RLS claim made on an owner connection is not a claim at all: Postgres
# exempts the table owner from every row policy, so the assertion passes with
# or without the fix. These two factories put a test session under exactly the
# policies the deployed worker faces.
#
# WHY THE ROLE IS SET IN THE STARTUP PACKET AND NOT ON THE `connect` EVENT.
#
# The obvious shape — `@event.listens_for(engine, "connect")` issuing
# `SET ROLE juli_app` on the raw cursor — is what
# `test_action_card_refresh_task_scope.py` uses, and it is subtly wrong for
# any test that opens more than one session. Measured on this repo's own
# Postgres, 2026-09-10:
#
#     session 1: current_user = juli_app      rows visible under RLS = 0
#     session 2: current_user = macos         rows visible under RLS = 1
#
# The `SET ROLE` runs inside the implicit transaction the DBAPI shim opens, and
# SQLAlchemy's reset-on-return issues a ROLLBACK when the connection goes back
# to the pool — which undoes it. The second checkout is the OWNER again, and
# every RLS assertion made on it silently passes for the wrong reason.
#
# `server_settings={"role": ...}` (asyncpg) and `options="-c role=..."`
# (psycopg2) set the parameter in the connection's startup packet instead, so
# it is the connection's own default: a ROLLBACK or a `RESET` returns TO it
# rather than away from it. Verified across three consecutive checkouts on both
# drivers.


@asynccontextmanager
async def juli_app_async_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """An `async_sessionmaker` whose every session runs as `juli_app`.

    Bound to an ENGINE, not to a pre-opened connection: a session that joins an
    externally supplied, already-active connection treats `commit()` as a
    SAVEPOINT release, so `SET LOCAL` survives it and no commit-related tenancy
    defect can be observed. Here `commit()` is a real COMMIT, the same as the
    worker's own `ensure_worker_session_factory`.
    """
    engine = create_async_engine(
        async_database_url(database_url()),
        connect_args={"server_settings": {"role": RUNTIME_ROLE}},
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@contextmanager
def juli_app_sync_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """The sync twin, for the paths that are synchronous by construction —
    `ToolExecutionLedger` and anything else running on
    `agent_workflow._sync_ledger_session`'s throwaway `Session`."""
    engine = create_engine(
        sync_database_url(database_url()),
        connect_args={"options": f"-c role={RUNTIME_ROLE}"},
    )
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


@contextmanager
def owner_sync_engine() -> Iterator[Engine]:
    """A sync engine as the table owner, for seeding and for reading back.

    Seeding owner-side is set-up, not the thing under test — doing it under RLS
    would make a fixture failure look like an isolation failure. Reading back
    owner-side is deliberate too: an assertion should see what is in the table,
    not what one particular scope is allowed to see.
    """
    engine = create_engine(sync_database_url(database_url()))
    try:
        yield engine
    finally:
        engine.dispose()


__all__ = [
    "RUNTIME_ROLE",
    "database_url",
    "juli_app_async_sessionmaker",
    "juli_app_sync_sessionmaker",
    "owner_sync_engine",
    "postgres_reachable",
    "requires_postgres",
]
