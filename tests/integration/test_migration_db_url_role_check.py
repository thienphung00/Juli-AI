"""migration_db_url() refuses a connection that cannot actually migrate (#1552).

THIS TEST CALLS THE FUNCTION. An earlier version of this module asserted
`"has_table_privilege" in inspect.getsource(migration_db_url)` — it grepped the
implementation's own text, so it passed against any function containing that
string in a comment and proved nothing about behaviour. It also tested only that
the OWNER is accepted, which was true before the fix as well.

What matters is the refusal, because the defect it prevents is silent: with
DATABASE_DIRECT_URL unset, `pg_dump` runs as the RLS-bound runtime role and
produces a backup that reports success and contains zero rows.
"""

from __future__ import annotations

import getpass
import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

_HELPERS = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "safe_alembic_helpers.py"


def _load_helpers():
    spec = importlib.util.spec_from_file_location("safe_alembic_helpers", _HELPERS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _runtime_role_url(owner_url: str) -> str:
    """A URL that authenticates as juli_app against the same test database.

    Local Postgres uses trust auth, so no password is involved. The role is
    NOLOGIN by design (migration 043); granting LOGIN here is scoped to this
    disposable test database and never touches a real deployment.
    """
    tail = owner_url.split("@", 1)[1]
    return f"postgresql://juli_app@{tail}"


@pytest.fixture
def juli_app_login(owner_engine: Engine):
    with owner_engine.begin() as conn:
        conn.execute(text("ALTER ROLE juli_app LOGIN"))
    yield
    with owner_engine.begin() as conn:
        conn.execute(text("ALTER ROLE juli_app NOLOGIN"))


def test_it_refuses_the_runtime_role_and_names_it(monkeypatch, juli_app_login):
    """The load-bearing case: juli_app must be refused, not silently accepted.

    juli_app holds no privilege on alembic_version — verified below rather than
    assumed, so this test fails loudly if a future migration grants it and
    quietly re-opens the hazard.
    """
    helpers = _load_helpers()
    owner_url = os.environ["DATABASE_URL"]

    from sqlalchemy import create_engine

    probe = create_engine(helpers.sync_database_url(owner_url))
    with probe.connect() as conn:
        can_update = conn.execute(
            text("SELECT has_table_privilege('juli_app','public.alembic_version','UPDATE')")
        ).scalar_one()
    probe.dispose()
    assert can_update is False, (
        "juli_app can UPDATE alembic_version — the premise of this guard has changed"
    )

    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", _runtime_role_url(owner_url))

    with pytest.raises(RuntimeError) as excinfo:
        helpers.migration_db_url()

    message = str(excinfo.value)
    assert "juli_app" in message, f"the error must name the refused role; got: {message}"
    assert "DATABASE_DIRECT_URL" in message, (
        f"the error must point at the variable that fixes it; got: {message}"
    )


def test_it_does_not_suggest_granting_the_privilege_away(monkeypatch, juli_app_login):
    """The remedy must not be 'grant UPDATE on alembic_version to this role'.

    A role can hold that grant and still read zero rows under RLS on every other
    table, so following such advice turns the guard green while leaving the
    backup empty. The only correct remedy is to point the URL at the owner.
    """
    helpers = _load_helpers()
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", _runtime_role_url(os.environ["DATABASE_URL"]))

    with pytest.raises(RuntimeError) as excinfo:
        helpers.migration_db_url()

    message = str(excinfo.value).lower()
    assert "grant" not in message, (
        "the error suggests granting a privilege, which re-opens the hazard it "
        f"exists to close; got: {excinfo.value}"
    )


def test_it_accepts_the_owner_via_direct_url(monkeypatch, juli_app_login):
    """DATABASE_DIRECT_URL wins over a runtime DATABASE_URL.

    Alone this proves little — it passed before the fix too. It earns its place
    only next to the refusal above, by showing the guard is selective rather
    than simply refusing everything.
    """
    helpers = _load_helpers()
    owner_url = os.environ["DATABASE_URL"]

    monkeypatch.setenv("DATABASE_URL", _runtime_role_url(owner_url))
    monkeypatch.setenv("DATABASE_DIRECT_URL", owner_url)

    resolved = helpers.migration_db_url()
    assert getpass.getuser() in resolved or "postgres" in resolved
