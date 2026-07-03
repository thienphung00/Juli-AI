"""Shared runtime helpers for production ASGI entrypoints."""

from __future__ import annotations

import os
import socket
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if key not in query:
            query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def _supabase_ipv4_hostaddr(hostname: str, port: int | None) -> str | None:
    """Resolve Supabase host to IPv4 for VPSes without working IPv6 egress."""
    try:
        infos = socket.getaddrinfo(
            hostname,
            port or 5432,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return None
    if not infos:
        return None
    return infos[0][4][0]


def sync_database_url(raw_url: str) -> str:
    """Normalize DATABASE_URL for sync drivers (Alembic / psycopg2)."""
    url = raw_url.strip()
    if "supabase.co" not in url:
        return url

    if "sslmode=" not in url:
        url = _append_query_params(url, {"sslmode": "require"})

    if "hostaddr=" in url:
        return url

    parsed = urlparse(url)
    if not parsed.hostname:
        return url

    hostaddr = _supabase_ipv4_hostaddr(parsed.hostname, parsed.port)
    if hostaddr is None:
        return url
    return _append_query_params(url, {"hostaddr": hostaddr})


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
