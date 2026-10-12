"""P19 (4A): a runtime DB role without ``juli_ops`` membership is an explicit 503.

Before: ``SET LOCAL ROLE juli_ops`` failed with ``permission denied to set role``
and every ``/v1/ops/*`` request was an opaque 500 until the owner ran
``GRANT juli_ops TO juli_app;``. Now ``ops_role`` raises ``OpsRoleMissing`` and the
ops route class answers 503 with the exact GRANT, logging ``ops_role_missing`` once.

SQLite has no roles, so the Postgres path is driven with a fake session (the
access-layer half) and a monkeypatched staff lookup (the route half).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.models.models import User
from juli_backend.models.ops import OpsStaff
from juli_backend.services.ops import access
from juli_backend.services.ops import staff as ops_staff
from tests.support.api import build_app, client_for
from tests.support.builders import make_user

EXPECTED_DETAIL = "Thiếu quyền juli_ops cho database — chạy GRANT juli_ops TO juli_app."


class _PgError(Exception):
    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value

    def one(self) -> Any:
        return self._value


class _FakePgSession:
    """Just enough AsyncSession for ``ops_role`` on a non-SQLite dialect.

    P22: the switch is ONE statement -- ``SELECT <current role>, CASE WHEN
    pg_has_role(...) THEN set_config('role', 'juli_ops', true) END`` -- and the
    restore is ``set_config('role', <previous>, true)``.
    """

    def __init__(self, set_role_error: Exception | None = None, *, member: bool = True) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.flushed = False
        self.info: dict = {}
        self._error = set_role_error
        self._member = member

    def get_bind(self) -> Any:
        dialect = type("D", (), {"name": "postgresql"})()
        return type("B", (), {"dialect": dialect})()

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt)
        params = dict(stmt.compile().params)
        self.statements.append((sql, params))
        if "pg_has_role" in sql:
            if self._error is not None:
                raise self._error
            return _Result(("juli_app", "juli_ops" if self._member else None))
        return _Result(None)

    async def flush(self) -> None:
        self.flushed = True


def _dbapi_error(message: str, sqlstate: str | None) -> DBAPIError:
    return DBAPIError("set_config('role', 'juli_ops', true)", None, _PgError(message, sqlstate))


async def test_granted_role_switches_and_restores_in_two_statements():
    session = _FakePgSession()
    async with access.ops_role(cast(AsyncSession, session)):
        pass
    assert len(session.statements) == 2
    (enter_sql, enter_params), (restore_sql, restore_params) = session.statements
    assert "current_user" in enter_sql and "set_config('role'" in enter_sql
    assert enter_params == {"role": "juli_ops"}
    assert "set_config('role'" in restore_sql
    assert restore_params == {"role": "juli_app"}
    assert session.flushed


async def test_not_a_member_raises_ops_role_missing_naming_the_current_role():
    session = _FakePgSession(member=False)
    with pytest.raises(access.OpsRoleMissing) as caught:
        async with access.ops_role(cast(AsyncSession, session)):
            pytest.fail("the block must not run without the role")
    assert caught.value.role == "juli_app"
    assert caught.value.detail == EXPECTED_DETAIL
    assert len(session.statements) == 1, "nothing to restore: the role never changed"


async def test_insufficient_privilege_raises_ops_role_missing_with_the_grant():
    error = _dbapi_error('permission denied to set role "juli_ops"', "42501")
    session = _FakePgSession(set_role_error=error)
    with pytest.raises(access.OpsRoleMissing) as caught:
        async with access.ops_role(cast(AsyncSession, session)):
            pytest.fail("the block must not run without the role")
    assert caught.value.role == "juli_app"
    assert caught.value.detail == EXPECTED_DETAIL


async def test_message_fallback_when_driver_has_no_sqlstate():
    error = _dbapi_error('permission denied to set role "juli_ops"', None)
    session = _FakePgSession(set_role_error=error)
    with pytest.raises(access.OpsRoleMissing):
        async with access.ops_role(cast(AsyncSession, session)):
            pass


async def test_other_database_errors_are_not_masked():
    error = _dbapi_error("connection reset", "08006")
    session = _FakePgSession(set_role_error=error)
    with pytest.raises(DBAPIError):
        async with access.ops_role(cast(AsyncSession, session)):
            pass


# -- the route half ------------------------------------------------------------------


@pytest.fixture
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def test_ops_route_returns_503_with_the_grant_and_logs_once(
    session, monkeypatch, caplog, bypass_access
):
    email = f"admin-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role="admin", active=True))
    await session.flush()

    async def missing(*_args: Any, **_kwargs: Any) -> None:
        raise access.OpsRoleMissing("juli_app")

    monkeypatch.setattr(ops_staff, "resolve_staff", missing)

    app = build_app(session)

    async def current() -> User:
        return user

    app.dependency_overrides[get_current_user] = current
    with caplog.at_level("ERROR", logger="juli_backend.api.routes.ops"):
        async with client_for(app) as client:
            response = await client.get("/v1/ops/overview")

    assert response.status_code == 503
    assert response.json() == {"detail": EXPECTED_DETAIL}
    hits = [r for r in caplog.records if r.getMessage() == "ops_role_missing"]
    assert len(hits) == 1
    assert hits[0].__dict__["db_role"] == "juli_app"
