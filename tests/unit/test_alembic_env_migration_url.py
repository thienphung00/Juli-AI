"""alembic runs migrations as the OWNER, not the runtime role (#1575).

THE DEFECT. `env.py` read `DATABASE_URL` directly. Since #1339's cutover that
variable names `juli_app`, the RLS-bound runtime role, which holds no privilege
on `public.alembic_version` — so `alembic upgrade` failed on production with
`permission denied for table alembic_version` before applying anything. Every
other step in the migration path (pg_dump, the revision read, the row counts)
resolved through `safe_alembic_helpers`, which prefers `DATABASE_DIRECT_URL`.
The backup and the migration were running as two different roles.

WHY THE ASSERTIONS LOOK LIKE THIS. Asserting "a migration connects" would pass
against either variable — locally both URLs reach a database, and trust auth
hands you a session as whichever role you name. So these tests assert the
RESOLVED VALUE, which differs between the fixed and broken code by construction.

WHY A SUBPROCESS. `env.py` cannot be imported: it executes `context.config` at
module scope and raises outside an alembic run. Mirroring its logic in the test
would pass while `env.py` itself drifted — the exact failure mode this issue is
about. So the second test runs the real file through alembic's OFFLINE mode,
which executes `env.py` and opens no connection, then reads back the URL
`env.py` set on the Config object.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from juli_backend.core.config.runtime import migration_database_url

REPO_ROOT = Path(__file__).resolve().parents[2]

OWNER = "postgresql://owner_role@localhost:5432/juli_owner"
RUNTIME = "postgresql://juli_app@localhost:5432/juli_runtime"


@pytest.fixture
def env(monkeypatch):
    """Both variables cleared, so each test states exactly what it sets."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    return monkeypatch


# --- the resolver: precedence, stated as values ----------------------------


def test_direct_url_wins_when_both_are_set(env):
    """The production case. Both are set on the VPS; the owner must win.

    This is the one assertion that fails against the pre-fix code.
    """
    env.setenv("DATABASE_URL", RUNTIME)
    env.setenv("DATABASE_DIRECT_URL", OWNER)

    resolved = migration_database_url()

    assert "owner_role" in resolved, (
        f"migrations must run as the owner from DATABASE_DIRECT_URL; resolved to {resolved!r}"
    )
    assert "juli_app" not in resolved, (
        f"the RLS-bound runtime role cannot write alembic_version; resolved to {resolved!r}"
    )


def test_database_url_is_used_when_no_direct_url_is_set(env):
    """Developer machines and CI set only DATABASE_URL. That must keep working."""
    env.setenv("DATABASE_URL", OWNER)

    assert "juli_owner" in migration_database_url()


def test_an_empty_direct_url_falls_back_rather_than_resolving_to_nothing(env):
    """`DATABASE_DIRECT_URL=` in an env file is unset, not "use the empty string".

    /etc/juli/api.env is regenerated wholesale by fetch-secrets.sh, so a key
    present-but-blank is a real state, not a hypothetical one.
    """
    env.setenv("DATABASE_URL", OWNER)
    env.setenv("DATABASE_DIRECT_URL", "   ")

    assert "juli_owner" in migration_database_url()


def test_it_raises_rather_than_silently_migrating_a_default_database(env):
    """With no default given and nothing set, refuse. Do not invent a target."""
    with pytest.raises(RuntimeError) as excinfo:
        migration_database_url()

    assert "DATABASE_DIRECT_URL" in str(excinfo.value)


def test_the_default_applies_only_when_nothing_is_set(env):
    """env.py passes a default so a bare `alembic` still works in a checkout."""
    assert "juli_owner" in migration_database_url(default=OWNER)

    env.setenv("DATABASE_DIRECT_URL", RUNTIME)
    assert "juli_runtime" in migration_database_url(default=OWNER), (
        "an explicit variable must beat the fallback default"
    )


# --- env.py itself, through a real alembic run -----------------------------


def _resolved_by_env_py(database_url: str, direct_url: str | None) -> str:
    """Run the real env.py offline and return the URL it selected.

    Offline mode ("base:base": no migration steps) executes env.py and opens no
    connection, so this runs anywhere — no Postgres, no roles, no CI substrate.
    """
    script = textwrap.dedent(
        """
        import sys
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "base:base", sql=True)
        sys.stderr.write("RESOLVED=" + (cfg.get_main_option("sqlalchemy.url") or ""))
        """
    )
    child_env = dict(os.environ)
    child_env["DATABASE_URL"] = database_url
    child_env.pop("DATABASE_DIRECT_URL", None)
    if direct_url is not None:
        child_env["DATABASE_DIRECT_URL"] = direct_url
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "backend" / "src"), str(REPO_ROOT), child_env.get("PYTHONPATH", "")]
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"offline alembic run failed ({result.returncode}):\n{result.stderr[-3000:]}"
    )
    marker = "RESOLVED="
    assert marker in result.stderr, f"env.py set no URL:\n{result.stderr[-3000:]}"
    return result.stderr.rsplit(marker, 1)[1].strip()


def test_env_py_prefers_the_direct_url_when_alembic_actually_runs():
    """The end-to-end proof, against the real env.py rather than a copy of it.

    Pre-fix this returns the juli_app URL, which is what broke production.
    """
    resolved = _resolved_by_env_py(RUNTIME, OWNER)

    assert "owner_role" in resolved, (
        f"alembic must connect as the owner; env.py resolved {resolved!r}"
    )
    assert "juli_app" not in resolved, (
        f"alembic must not connect as the runtime role; env.py resolved {resolved!r}"
    )


def test_env_py_still_uses_database_url_alone():
    """No DATABASE_DIRECT_URL — every developer checkout and CI. Must not regress."""
    resolved = _resolved_by_env_py(OWNER, None)

    assert "juli_owner" in resolved, f"env.py resolved {resolved!r}"
