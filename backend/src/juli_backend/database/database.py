from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Re-exported for backward compatibility: `Base` now lives in a dependency-free
# leaf module (juli_backend.orm_base) to avoid the database<->models import cycle.
# The redundant alias marks this as an intentional re-export for ruff/mypy.
from juli_backend.orm_base import Base as Base


def create_engine(database_url: str, **kwargs):
    return create_async_engine(database_url, **kwargs)


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    global _session_factory
    _session_factory = factory


# One engine per database URL, per process. Worker tasks call
# ensure_worker_session_factory() on every invocation; building a fresh engine each
# time opens a new connection pool and leaves the previous one undisposed, which
# exhausts the Supabase pooler's client ceiling (#813).
_worker_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def ensure_worker_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory for ``database_url``, creating it once.

    Repeated calls return the same factory and create no additional engines.
    """
    factory = _worker_factories.get(database_url)
    if factory is None:
        # NullPool, deliberately (#871): worker tasks each enter through
        # asyncio.run(), so every invocation runs on a fresh event loop. A pooled
        # asyncpg connection created on one loop is poison on the next — checkout
        # raises "Future attached to a different loop" and the task dies before
        # doing any work. With no pooling, each session opens and closes its own
        # connection inside the currently running loop, nothing loop-bound survives
        # between tasks, and the Supabase session-mode pooler only ever sees
        # in-flight connections (the #813 concern, solved without a shared pool).
        engine = create_async_engine(database_url, poolclass=NullPool)
        factory = create_session_factory(engine)
        _worker_factories[database_url] = factory
        init_session_factory(factory)
    return factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async database session."""
    if _session_factory is None:
        raise RuntimeError(
            "Session factory not configured. Call init_session_factory() at app startup."
        )
    async with _session_factory() as session:
        yield session
