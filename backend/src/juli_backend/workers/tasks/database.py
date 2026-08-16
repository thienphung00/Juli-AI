"""Shared database helpers for worker tasks."""

from __future__ import annotations

import os

from juli_backend.core.async_db import async_database_url


def get_async_database_url() -> str:
    """Get the async database URL for worker tasks.

    Converts sync postgresql:// URLs to postgresql+asyncpg:// form (required for asyncio),
    and falls back to sqlite+aiosqlite for testing when DATABASE_URL is unset.

    This ensures all worker tasks use async drivers, not sync psycopg2 which crashes
    in asyncio context (issue #741).
    """
    raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    return async_database_url(raw_url)


def get_sync_database_url() -> str:
    """Get the sync (Alembic/psycopg2-style) database URL for the one worker
    seam that deliberately stays synchronous: `ToolExecutionLedger`
    (`services/agent/runner/ledger.py`, #1121) -- that module's own
    docstring explains why its DB access is a plain `sqlalchemy.orm.Session`
    rather than the `AsyncSession` every other worker surface uses (issue
    #1145 wires the ledger into `workers/tasks/agent_workflow.py`).

    Mirrors `get_async_database_url()`: falls back to a sync SQLite URL when
    `DATABASE_URL` is unset. `os.getenv("DATABASE_URL", ...)` stays the
    single choke point this file already is (`test_worker_database_url.py`'s
    AC5) -- `agent_workflow.py` calls this helper rather than reading the
    env var itself.

    Imports `core.config.runtime` via its depth-2 public root
    (`from juli_backend.core.config import runtime`, not
    `from juli_backend.core.config.runtime import sync_database_url`) --
    the same `.importlinter.toml` cross-package depth cap
    `get_async_database_url`'s own `core.async_db` shim exists to respect;
    `runtime.py` is not re-exported at `core.config`'s own `__init__.py`, so
    the submodule is reached by name instead of adding a second shim module.
    """
    from juli_backend.core.config import runtime as runtime_module

    raw_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    return runtime_module.sync_database_url(raw_url)
