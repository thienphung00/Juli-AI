"""Runtime helper tests for production ASGI entrypoints."""

from __future__ import annotations

import pytest

from backend.runtime import async_database_url, cors_allow_origins, require_env


def test_async_database_url_converts_postgresql_scheme():
    raw = "postgresql://user:pass@localhost:5432/juli"
    assert async_database_url(raw) == (
        "postgresql+asyncpg://user:pass@localhost:5432/juli"
    )


def test_async_database_url_adds_supabase_ssl():
    raw = "postgresql://user:pass@db.project.supabase.co:5432/postgres"
    assert async_database_url(raw) == (
        "postgresql+asyncpg://user:pass@db.project.supabase.co:5432/postgres?ssl=require"
    )


def test_cors_allow_origins_splits_csv(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://app-juli.com, https://www.app-juli.com",
    )
    assert cors_allow_origins() == [
        "https://app-juli.com",
        "https://www.app-juli.com",
    ]


def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_ENV", raising=False)
    with pytest.raises(RuntimeError, match="MISSING_TEST_ENV"):
        require_env("MISSING_TEST_ENV")
