"""Shared runtime helpers for production ASGI entrypoints."""

from __future__ import annotations

import os


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def async_database_url(raw_url: str) -> str:
    """Convert a sync Postgres URL to SQLAlchemy asyncpg form."""
    url = raw_url.strip()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "supabase.co" in url and "ssl=" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}ssl=require"
    return url


def cors_allow_origins() -> list[str]:
    origins = os.environ.get(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in origins.split(",") if origin.strip()]
