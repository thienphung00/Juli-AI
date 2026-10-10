"""The ops database path: ``SET LOCAL ROLE juli_ops`` around ops-table work (P16, D25).

Ops tables (migration ``083_ops_console``) grant nothing to ``juli_app``; their
only RLS policy is ``TO juli_ops``. Every read or write of one goes through
:func:`ops_role`, which switches the transaction's role to ``juli_ops``,
flushes pending ORM writes while still in it, and switches back to the role
the transaction had before (so the tenant reads around it keep the runtime's
own role and its RLS). SQLite (unit tests) has no roles: a no-op there.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

OPS_ROLE = "juli_ops"


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
    await session.execute(text(f"SET LOCAL ROLE {OPS_ROLE}"))
    try:
        yield
        await session.flush()
    finally:
        if session.in_transaction() and session.is_active:
            await session.execute(text(f"SET LOCAL ROLE {_quote_ident(str(previous))}"))
