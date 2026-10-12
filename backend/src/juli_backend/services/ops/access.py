"""The ops database path: ``SET LOCAL ROLE juli_ops`` around ops-table work (P16, D25).

Ops tables (migration ``083_ops_console``) grant nothing to ``juli_app``; their
only RLS policy is ``TO juli_ops``. Every read or write of one goes through
:func:`ops_role`, which switches the transaction's role to ``juli_ops``,
flushes pending ORM writes while still in it, and switches back to the role
the transaction had before (so the tenant reads around it keep the runtime's
own role and its RLS). SQLite (unit tests) has no roles: a no-op there.

The runtime login role must be a MEMBER of ``juli_ops`` for ``SET LOCAL ROLE``
to work (``GRANT juli_ops TO juli_app;``, run once by the owner). Without it
Postgres refuses with insufficient_privilege; that is raised here as
:class:`OpsRoleMissing` so ``/v1/ops/*`` answers 503 with the exact fix rather
than an opaque 500. The deploy checks the same membership before cutover.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

OPS_ROLE = "juli_ops"

# SQLSTATE 42501 insufficient_privilege: "permission denied to set role ...".
_INSUFFICIENT_PRIVILEGE = "42501"


class OpsRoleMissing(RuntimeError):
    """The session's login role is not a member of ``juli_ops``."""

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(f"role {role!r} is not a member of {OPS_ROLE}")

    @property
    def detail(self) -> str:
        return f"Thiếu quyền {OPS_ROLE} cho database — chạy GRANT {OPS_ROLE} TO {self.role}."


def _is_insufficient_privilege(exc: DBAPIError) -> bool:
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if code is not None:
        return str(code) == _INSUFFICIENT_PRIVILEGE
    return "permission denied to set role" in str(orig)


def is_sqlite(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "sqlite"


# Switch to juli_ops AND learn the role to come back to, in ONE round trip (P22).
#
# This used to be ``SELECT current_user`` then ``SET LOCAL ROLE juli_ops``: two
# statements, ~440 ms in production, on every ops block. ``set_config('role',
# ..., true)`` IS ``SET LOCAL ROLE`` (same GUC, same membership check, same
# 42501 on refusal); the ``OFFSET 0`` subquery is a separate plan node, so
# ``current_user`` is read before the outer projection runs ``set_config``.
#
# The membership test turns "not a member" into a NULL instead of an error, so
# the role we were (needed for the 503's exact GRANT) is still in hand; the
# ``except`` below covers a member that may still not SET the role (Postgres
# 16's ``SET`` grant option).
_ENTER_SQL = text(
    "SELECT prior.who, CASE WHEN pg_has_role(session_user, :role, 'MEMBER') "
    "THEN set_config('role', :role, true) END "
    "FROM (SELECT current_user::text AS who OFFSET 0) AS prior"
)
_RESTORE_SQL = text("SELECT set_config('role', :role, true)")

#: ``session.info`` key: the transaction an open ``ops_role`` block switched.
_ACTIVE_KEY = "juli_ops_role_tx"


def _current_transaction(session: AsyncSession) -> object | None:
    sync = getattr(session, "sync_session", None)
    return sync.get_transaction() if sync is not None else None


@asynccontextmanager
async def ops_role(session: AsyncSession) -> AsyncIterator[None]:
    """Run the block as ``juli_ops``; restore the previous role on the way out.

    Re-entrant at no cost (P22): a block opened inside another block of the
    same transaction runs in the role the outer one already set, so a route can
    wrap several ops reads in one outer block and pay for one switch and one
    restore instead of one pair per read.
    """
    if is_sqlite(session):
        yield
        return
    info = getattr(session, "info", None)
    active = info.get(_ACTIVE_KEY) if info is not None else None
    if active is not None and active is _current_transaction(session):
        yield
        await session.flush()
        return
    try:
        row = (await session.execute(_ENTER_SQL.bindparams(role=OPS_ROLE))).one()
    except DBAPIError as exc:
        if _is_insufficient_privilege(exc):
            raise OpsRoleMissing(_login_role(session)) from exc
        raise
    previous, switched = str(row[0]), row[1]
    if switched is None:
        raise OpsRoleMissing(previous)
    if previous == OPS_ROLE:
        yield
        await session.flush()
        return
    if info is not None:
        info[_ACTIVE_KEY] = _current_transaction(session)
    try:
        # On an error the transaction is rolled back by the caller, which also
        # undoes SET LOCAL; restoring would only fail on the aborted transaction.
        yield
        await session.flush()
    finally:
        if info is not None:
            info.pop(_ACTIVE_KEY, None)
    await session.execute(_RESTORE_SQL.bindparams(role=previous))


def _login_role(session: AsyncSession) -> str:
    """Best-effort role name for the 503 when the switch itself raised."""
    url = getattr(session.get_bind(), "url", None)
    name = getattr(url, "username", None)
    # A Supabase pooler login is ``<role>.<project ref>``; the GRANT names the role.
    return str(name or "juli_app").split(".", 1)[0]
