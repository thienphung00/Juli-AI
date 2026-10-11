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


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@asynccontextmanager
async def ops_role(session: AsyncSession) -> AsyncIterator[None]:
    """Run the block as ``juli_ops``; restore the previous role on the way out."""
    if is_sqlite(session):
        yield
        return
    previous = (await session.execute(text("SELECT current_user"))).scalar_one()
    if previous == OPS_ROLE:
        yield
        await session.flush()
        return
    try:
        await session.execute(text(f"SET LOCAL ROLE {OPS_ROLE}"))
    except DBAPIError as exc:
        if _is_insufficient_privilege(exc):
            raise OpsRoleMissing(str(previous)) from exc
        raise
    # On an error the transaction is rolled back by the caller, which also
    # undoes SET LOCAL; restoring would only fail on the aborted transaction.
    yield
    await session.flush()
    await session.execute(text(f"SET LOCAL ROLE {_quote_ident(str(previous))}"))
