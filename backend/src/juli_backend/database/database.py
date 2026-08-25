from collections.abc import AsyncIterator

from sqlalchemy import event, text
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
    """Create an async session factory with tenant context seam attached.

    The returned factory creates sessions that automatically apply tenant
    context (SET LOCAL GUCs) on transaction begin, reading from contextvars
    set by HTTP middleware or Celery task wrappers.

    Issue #1327, ADR-085 decision 2: the seam runs automatically on every
    transaction, no opt-in required.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Attach tenant context setter to AsyncSession's "after_begin" event
    @event.listens_for(AsyncSession, "after_begin")
    async def apply_tenant_context(session, transaction, connection):
        """Apply tenant context (SET LOCAL GUCs) when a transaction begins.

        This runs automatically for any AsyncSession, reading tenant context
        from contextvars. If no context is available and system_scope() is
        not active, raises TenantContextRequiredError BEFORE any user SQL.

        Issue #1327: automatic seam, runs on every transaction.
        """
        from juli_backend.database.tenant_context import (
            TenantContextRequiredError,
            _system_scope_active,
            get_tenant_context,
        )

        shop_id, user_id = get_tenant_context()

        # Fail-closed in Python before any SQL
        if not _system_scope_active and (shop_id is None or user_id is None):
            raise TenantContextRequiredError(
                f"Tenant context required for transaction: shop_id={shop_id}, "
                f"user_id={user_id}, system_scope_active={_system_scope_active}"
            )

        # Apply SET LOCAL (transaction-scoped) on Postgres only
        try:
            if shop_id is not None:
                await session.execute(text(f"SET LOCAL app.current_shop_id = '{shop_id}'"))
            if user_id is not None:
                await session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
        except Exception:
            # On SQLite, SET LOCAL fails with syntax error (expected for testing)
            bind = session.get_bind()
            db_url = str(getattr(bind, "url", ""))
            if "sqlite" not in db_url.lower():
                raise
            # Silently skip GUC setting on SQLite (testing only)

    return factory


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
    """FastAPI dependency that yields an async database session.

    Tenant context (app.current_shop_id, app.current_user_id) is applied
    automatically via SET LOCAL when a transaction begins, reading from
    contextvars that are set by HTTP middleware or Celery task wrappers.

    This seam is automatic and requires no opt-in from route handlers.
    Issue #1327, ADR-085 decision 2.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Session factory not configured. Call init_session_factory() at app startup."
        )
    async with _session_factory() as session:
        yield session
