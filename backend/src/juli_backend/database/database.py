from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async database session."""
    if _session_factory is None:
        raise RuntimeError(
            "Session factory not configured. Call init_session_factory() at app startup."
        )
    async with _session_factory() as session:
        yield session
