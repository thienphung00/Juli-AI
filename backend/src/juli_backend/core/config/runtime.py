"""Shared runtime helpers for production ASGI entrypoints."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

# Local dev: load repo-root .env when cwd is the project root (does not override
# vars already set by systemd / fetch-secrets on the VPS).
_repo_root = Path(__file__).resolve().parents[5]
load_dotenv(_repo_root / ".env", override=False)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


_ENVIRONMENT_ENV_VAR = "ENVIRONMENT"
_ENVIRONMENT_DEVELOPMENT = "development"
_ENVIRONMENT_PRODUCTION = "production"
_ALLOWED_ENVIRONMENTS = (_ENVIRONMENT_DEVELOPMENT, _ENVIRONMENT_PRODUCTION)


def _environment() -> str:
    """Read the ``ENVIRONMENT`` discriminator, validated against a closed set.

    Unset defaults to ``"development"`` — the non-production value — so local
    dev and tests need no configuration and a forgotten variable can never
    silently mean production. An unrecognised value fails fast with a message
    naming the variable and the permitted values, rather than being coerced
    or ignored.
    """
    raw = os.environ.get(_ENVIRONMENT_ENV_VAR, "").strip()
    if not raw:
        return _ENVIRONMENT_DEVELOPMENT
    if raw not in _ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(_ALLOWED_ENVIRONMENTS)
        raise RuntimeError(f"Invalid {_ENVIRONMENT_ENV_VAR}={raw!r}; must be one of: {allowed}")
    return raw


def is_production() -> bool:
    """Whether the process is running in the production environment.

    The single accessor the rest of the application should branch on instead
    of reading ``ENVIRONMENT`` (or any other ad-hoc flag) directly. See
    ``_environment`` for the default and validation behaviour.
    """
    return _environment() == _ENVIRONMENT_PRODUCTION


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if key not in query:
            query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def _is_direct_supabase_host(hostname: str | None) -> bool:
    return bool(hostname and hostname.startswith("db.") and hostname.endswith(".supabase.co"))


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
    return str(infos[0][4][0])


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

    if _is_direct_supabase_host(parsed.hostname):
        hostaddr = _supabase_ipv4_hostaddr(parsed.hostname, parsed.port)
        if hostaddr is None:
            raise RuntimeError(
                "DATABASE_URL uses Supabase direct host db.*.supabase.co, which is "
                "IPv6-only. On IPv4-only networks (most VPS hosts), use the Session "
                "pooler URI from Supabase Dashboard → Connect → Session mode "
                "(aws-0-<region>.pooler.supabase.com:5432, user postgres.<project-ref>)."
            )
        return _append_query_params(url, {"hostaddr": hostaddr})

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


def is_production_write_enabled() -> bool:
    """Whether the production-write capability is enabled (issue #1330, #1336).

    Fail-closed: unset or invalid values default to False (capability disabled).
    Only "true" (case-insensitive) enables the capability. This is the gate for
    check 7 (RLS preconditions) and #1336's precondition checks.

    When enabled, the boot check verifies that the database connection enforces
    RLS on all tenant-scoped tables before allowing operation. When disabled
    (default), the check is a no-op regardless of connection role (today's
    deployed configuration).
    """
    value = os.environ.get("PRODUCTION_WRITE_ENABLED", "").strip().lower()
    if value not in ("true", "1", "yes"):
        return False
    return True


def is_production_write_kill_switch_active() -> bool:
    """Whether the production-write kill switch is active (issue #1337).

    Read PER TOOL CALL, not at boot. This is the emergency stop for production
    writes — it provides latency without deploy or restart.

    Fail-closed: unset defaults to False (kill switch off, writes allowed).
    Unparseable values are treated as "on" (fail-closed: writes off).

    Only "false", "0", or "no" (case-insensitive) disable the kill switch.
    Any other value, including unset, is interpreted as active.

    This is distinct from PRODUCTION_WRITE_ENABLED: one is the deliberate
    capability gate (must be on to write production), the other is the
    emergency stop (when on, no production writes happen).
    """
    value = os.environ.get("PRODUCTION_WRITE_KILL_SWITCH", "").strip().lower()
    # Fail-closed: only explicit "off" values disable; everything else means "active"
    # Empty/unset means OFF (no kill switch active)
    if not value:
        return False
    # Explicit "off" values mean kill switch is OFF
    if value in ("false", "0", "no"):
        return False
    # Everything else (including malformed) is fail-closed as "active"
    return True
