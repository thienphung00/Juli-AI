"""The analytical read engine (decision #67, batch-1124-c-data Q5).

Analytical reads -- ``metrics.query``, the screens' and the export's reads of the stored facts,
Chat's tools -- go to a read-only replica of the primary when ``DATABASE_READ_URL`` is set
(Supabase read replica, through its own pooler). Unset, they use the request's own session
(today's behaviour: dev and CI need nothing).

- Writes never use it: ingest, materialize, cards and the Connector keep the primary engine.
  The read engine's connections start every transaction READ ONLY on Postgres, and an ORM write
  through a read session raises :class:`ReadOnlySessionError` before it reaches the server.
- RLS: the read session gets the same tenant GUCs (``app.current_shop_id`` /
  ``app.current_user_id``) as the request, from the tenant contextvars the route dependency set.
  With no tenant in context the read stays on the primary session (fail closed, never an
  unscoped replica read).
- Replica lag: a request that wrote (a flush, an ORM insert / update / delete, or
  :func:`mark_wrote`) reads from the primary, so it sees what it just wrote.

Add-only: nothing here changes the primary engine (``database.py``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import ORMExecuteState, Session

from juli_backend.database.database import ENGINE_DEFAULTS, create_api_engine
from juli_backend.database.tenant_context import (
    _apply_tenant_context_to_session,
    get_tenant_context,
)

READ_URL_ENV = "DATABASE_READ_URL"
#: ``session.info`` keys
WROTE_KEY = "juli_wrote"
READ_KEY = "juli_read_session"


class ReadOnlySessionError(RuntimeError):
    """A write was attempted through the analytical read session."""


_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def _asyncpg_url(raw: str) -> str:
    """The minimal sync -> asyncpg form; the API process installs the full conversion
    (``core.config.runtime.async_database_url``: libpq query, Supabase ssl) at boot."""
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


#: the URL conversion (``database`` may not import ``core``: the API wires it, ``configure``)
_url_of: Callable[[str], str] = _asyncpg_url


def configure(url_normaliser: Callable[[str], str]) -> None:
    """Install the process's async-URL conversion (the API's ``async_database_url``)."""
    global _url_of
    _url_of = url_normaliser


def read_database_url() -> str | None:
    """``DATABASE_READ_URL`` as an async URL, or ``None`` when unset (= the primary)."""
    raw = (os.environ.get(READ_URL_ENV) or "").strip()
    if not raw:
        return None
    return _url_of(raw)


def read_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """The process-wide read session factory, created on first use; ``None`` when unset."""
    url = read_database_url()
    if url is None:
        return None
    factory = _factories.get(url)
    if factory is None:
        kwargs: dict[str, Any] = dict(ENGINE_DEFAULTS)
        if url.startswith("postgresql+asyncpg"):
            kwargs["connect_args"] = {"server_settings": {"default_transaction_read_only": "on"}}
        engine = create_api_engine(url, **kwargs)
        factory = async_sessionmaker(engine, expire_on_commit=False, info={READ_KEY: True})
        _factories[url] = factory
    return factory


def reset_read_engine_for_tests() -> None:
    """Forget the cached factories (tests flip the env var)."""
    _factories.clear()


def mark_wrote(session: AsyncSession) -> None:
    """Pin this request's later analytical reads to the primary (it wrote something)."""
    session.info[WROTE_KEY] = True


def wrote(session: AsyncSession) -> bool:
    return bool(session.info.get(WROTE_KEY)) or bool(
        session.new or session.dirty or session.deleted
    )


def is_read_session(session: AsyncSession) -> bool:
    return bool(session.info.get(READ_KEY))


@event.listens_for(Session, "after_flush")
def _flushed(session: Session, _ctx: Any) -> None:
    session.info[WROTE_KEY] = True


@event.listens_for(Session, "do_orm_execute")
def _orm_execute(state: ORMExecuteState) -> None:
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    if state.session.info.get(READ_KEY):
        raise ReadOnlySessionError("write through the analytical read session")
    state.session.info[WROTE_KEY] = True


@event.listens_for(Session, "before_flush")
def _no_flush_on_read(session: Session, _ctx: Any, _instances: Any) -> None:
    if session.info.get(READ_KEY) and (session.new or session.dirty or session.deleted):
        raise ReadOnlySessionError("write through the analytical read session")


@asynccontextmanager
async def read_session(primary: AsyncSession) -> AsyncIterator[AsyncSession]:
    """The session an analytical read uses: the replica when configured, else ``primary``.

    ``primary`` itself when: no ``DATABASE_READ_URL``; it already is a read session; the request
    wrote; or no tenant (shop + user) is in context (fail closed)."""
    factory = read_session_factory()
    if factory is None or is_read_session(primary) or wrote(primary):
        yield primary
        return
    shop_id, user_id = get_tenant_context()
    if shop_id is None or user_id is None:
        yield primary
        return
    async with factory() as session:
        async with session.begin():
            await _apply_tenant_context_to_session(session, shop_id, user_id)
            yield session


__all__ = [
    "READ_URL_ENV",
    "ReadOnlySessionError",
    "is_read_session",
    "mark_wrote",
    "configure",
    "read_database_url",
    "read_session",
    "read_session_factory",
    "reset_read_engine_for_tests",
    "wrote",
]
