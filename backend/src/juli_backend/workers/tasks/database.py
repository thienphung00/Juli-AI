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
