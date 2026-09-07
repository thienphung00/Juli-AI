"""The migration connection is vouched for, and the resolver stays pure (#1552).

TWO SEPARATE PROPERTIES, tested separately on purpose.

`migration_db_url()` resolves a string and opens nothing. An earlier version of
this fix folded a privilege check into it, which made three unrelated suites
fail: they drive the script with deliberately unreachable URLs and suddenly got
a connection error instead of the behaviour they were asserting.

`_decide_migration_privilege` holds the decision and is pure, so the refusal is
testable everywhere — no CI Postgres will hand you a login as a second role.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

_HELPERS = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "safe_alembic_helpers.py"


def _load():
    spec = importlib.util.spec_from_file_location("safe_alembic_helpers", _HELPERS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_it_refuses_a_role_that_cannot_update_alembic_version():
    """The load-bearing case, and it needs no database.

    This is the decision the whole fix exists to make. Folding it into a
    connection would make it untestable in CI, where every role needs a
    password.
    """
    helpers = _load()

    with pytest.raises(RuntimeError) as excinfo:
        helpers._decide_migration_privilege("juli_app", can_update=False)

    message = str(excinfo.value)
    assert "juli_app" in message, f"the error must name the refused role; got: {message}"
    assert "DATABASE_DIRECT_URL" in message, (
        f"the error must point at the variable that fixes it; got: {message}"
    )


def test_it_does_not_tell_the_operator_to_grant_the_privilege_away():
    """The remedy must not be "grant UPDATE on alembic_version to this role".

    A role can hold that grant and still read zero rows under RLS on every other
    table — measured in a rolled-back transaction, where the grant turns the
    check green while users, shops, tiktok_credentials and products all read 0.
    Following that advice would leave the backup empty and the guard green.
    """
    helpers = _load()

    with pytest.raises(RuntimeError) as excinfo:
        helpers._decide_migration_privilege("juli_app", can_update=False)

    assert "grant" not in str(excinfo.value).lower(), (
        f"the error suggests granting a privilege, re-opening the hazard it "
        f"exists to close; got: {excinfo.value}"
    )


def test_it_accepts_a_role_that_can_update_alembic_version():
    """Alone this proves little — it held before the fix too. It earns its place
    beside the refusal above, by showing the check is selective."""
    helpers = _load()

    # Asserted rather than left as "does not raise": the contract is that an
    # accepted role returns None, and a bare call records nothing about what
    # was checked.
    assert helpers._decide_migration_privilege("postgres", can_update=True) is None


@requires_postgres
def test_the_resolver_opens_no_connection(monkeypatch):
    """`migration_db_url()` must stay pure.

    Asserted with a URL that cannot be connected to: if the resolver dials the
    database, this raises instead of returning. Three suites depend on that,
    which is how the earlier version was caught.
    """
    helpers = _load()
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/nope")

    resolved = helpers.migration_db_url()

    assert "nope" in resolved, "the resolver must return the URL it was given"


@requires_postgres
def test_the_verifier_accepts_the_real_database():
    """The connected half, against whatever role the suite runs as."""
    helpers = _load()
    result = helpers.verify_migration_privileges(os.environ["DATABASE_URL"])
    assert result["checked"] is True
