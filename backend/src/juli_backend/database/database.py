import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Re-exported for backward compatibility: `Base` now lives in a dependency-free
# leaf module (juli_backend.orm_base) to avoid the database<->models import cycle.
# The redundant alias marks this as an intentional re-export for ruff/mypy.
from juli_backend.orm_base import Base as Base

logger = logging.getLogger(__name__)


#: D16: a database error never echoes its bound values. Without it, an
#: IntegrityError / DataError message (and so a log line, a traceback or a
#: ``last_error`` column built from it) carries the row being written -- a buyer
#: field among them. SQLAlchemy prints ``[SQL parameters hidden due to
#: hide_parameters=True]`` instead.
ENGINE_DEFAULTS: dict[str, Any] = {"hide_parameters": True}


def _with_defaults(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {**ENGINE_DEFAULTS, **kwargs}


def create_engine(database_url: str, **kwargs):
    return create_async_engine(database_url, **_with_defaults(kwargs))


# -- the API's pooled engine (P29) ----------------------------------------------------
#
# The API process (one uvicorn worker on the VPS in Asia) talks to the Supabase
# pooler in us-west-2 in SESSION mode (port 5432, ADR-086): one round trip is
# ~395 ms, a NEW connection ~1,257 ms (TCP + TLS + pooler auth). So:
#
# - ``pool_pre_ping`` OFF (SQLAlchemy's default, now explicit): a ping on every
#   checkout is one more round trip on every request.
# - Idle connections are kept warm instead: :class:`PoolKeepWarm` runs
#   ``SELECT 1`` on each idle pooled connection every API_DB_KEEPWARM_SECONDS
#   (60), straight on the asyncpg connection (no BEGIN/ROLLBACK), so no pooled
#   connection sits idle long enough for the pooler -- or the AWS load balancer
#   in front of it, whose TCP idle timeout is 350 s -- to drop it.
# - An idle guard backs that up without a round trip: a connection idle longer
#   than API_DB_IDLE_LIMIT_SECONDS (240, under that 350 s) is discarded AT
#   CHECKOUT and replaced (the pool's own DisconnectionError retry), rather
#   than handed to a request that would fail on it.
# - ``pool_recycle`` (API_DB_POOL_RECYCLE_SECONDS, 1800) is an AGE limit, not an
#   idle one: it bounds a connection's lifetime against server-side limits.
#   It is deliberately long: every replacement costs a reconnect AND an empty
#   asyncpg prepared-statement cache (one extra round trip per statement shape
#   on that connection), and idleness is already handled above. Connections
#   near that age are replaced by the keep-warm task in the background, so a
#   request rarely pays for the recycle.
# - Prepared statements stay ON (asyncpg's default statement cache): session
#   mode pins one server connection per client connection, so they are safe.
#   Were DATABASE_URL ever switched to the TRANSACTION pooler (port 6543),
#   ``statement_cache_size=0`` would be required -- and the tenant GUC design
#   (ADR-086) would need re-review anyway.
# - pool_size 5 + max_overflow 5: at most 10 pooler client connections from
#   the API (was SQLAlchemy's 5 + 10), leaving the session pooler's ceiling for
#   the workers' NullPool connections (#813). FIFO checkout (the default), so
#   every warm connection is used and its statement cache warms too.
# - At startup :func:`warm_pool` opens API_DB_POOL_SIZE connections in
#   parallel (and runs the dialect's first-connect initialisation), so the
#   first requests after a deploy do not pay ~1.3 s each to connect.


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("api_db_pool_setting_invalid", extra={"setting": name})
        return default
    return value if value >= 0 else default


def api_pool_settings() -> dict[str, float]:
    """The API pool's knobs (env overrides; no secret is read)."""
    return {
        "pool_size": int(_env_number("API_DB_POOL_SIZE", 5)),
        "max_overflow": int(_env_number("API_DB_MAX_OVERFLOW", 5)),
        "pool_timeout": _env_number("API_DB_POOL_TIMEOUT_SECONDS", 10),
        "pool_recycle": int(_env_number("API_DB_POOL_RECYCLE_SECONDS", 1800)),
        "idle_limit": _env_number("API_DB_IDLE_LIMIT_SECONDS", 240),
        "keepwarm": _env_number("API_DB_KEEPWARM_SECONDS", 60),
    }


_CONNECTED_AT = "juli_connected_at"
_IDLE_SINCE = "juli_idle_since"


def _install_idle_guard(engine: AsyncEngine, idle_limit: float) -> None:
    """Stamp each pooled connection's idle start; refuse a stale one at checkout."""
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, record: Any) -> None:
        now = time.monotonic()
        record.info[_CONNECTED_AT] = now
        record.info[_IDLE_SINCE] = now

    @event.listens_for(sync_engine, "checkin")
    def _on_checkin(dbapi_connection: Any, record: Any) -> None:
        if record is not None:
            record.info[_IDLE_SINCE] = time.monotonic()

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(dbapi_connection: Any, record: Any, proxy: Any) -> None:
        idle_since = record.info.get(_IDLE_SINCE)
        if idle_limit > 0 and idle_since is not None:
            idle = time.monotonic() - idle_since
            if idle > idle_limit:
                logger.info("api_db_connection_idle_replaced", extra={"idle_s": round(idle)})
                # The pool discards this connection and checks out (or opens)
                # another -- no round trip spent on a likely-dead socket.
                raise DisconnectionError(f"idle {idle:.0f}s > {idle_limit:.0f}s")


def create_api_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """The API's engine: a tuned QueuePool on Postgres; plain elsewhere (tests)."""
    if not database_url.startswith("postgresql"):
        return create_async_engine(database_url, **_with_defaults(kwargs))
    settings = api_pool_settings()
    engine = create_async_engine(
        database_url,
        pool_pre_ping=False,
        pool_size=int(settings["pool_size"]),
        max_overflow=int(settings["max_overflow"]),
        pool_timeout=settings["pool_timeout"],
        pool_recycle=int(settings["pool_recycle"]) or -1,
        **_with_defaults(kwargs),
    )
    _install_idle_guard(engine, settings["idle_limit"])
    return engine


async def _ping_one(engine: AsyncEngine, *, replace_older_than: float | None) -> None:
    """Check out one pooled connection, ``SELECT 1`` on it, give it back.

    Straight on the asyncpg connection: no BEGIN / ROLLBACK, one round trip.
    A connection older than ``replace_older_than`` is replaced here, in the
    background, instead of by ``pool_recycle`` on some request's checkout.
    """
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        # `.info` is the DBAPI connection's own dict -- where the connect event
        # stamped it (and emptied when the record reconnects).
        connected_at = raw.info.get(_CONNECTED_AT)
        if (
            replace_older_than is not None
            and connected_at is not None
            and time.monotonic() - connected_at > replace_older_than
        ):
            await conn.invalidate()
            return
        driver = raw.driver_connection
        if driver is None:  # already invalidated
            return
        try:
            await driver.execute("SELECT 1")
        except Exception:
            logger.warning("api_db_keepwarm_ping_failed", exc_info=True)
            await conn.invalidate()


async def warm_pool(engine: AsyncEngine, connections: int) -> int:
    """Hold ``connections`` pooled connections at once, pinging each; returns how many.

    Held concurrently, so the pool ends with at least that many open (idle
    ones are reused, the rest are opened -- in parallel).
    """
    if connections <= 0 or engine.dialect.name != "postgresql":
        return 0
    results = await asyncio.gather(
        *(_ping_one(engine, replace_older_than=None) for _ in range(connections)),
        return_exceptions=True,
    )
    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        logger.warning(
            "api_db_pool_warm_failed",
            extra={"failed": len(failed), "error": type(failed[0]).__name__},
        )
    return connections - len(failed)


class PoolKeepWarm:
    """Every ``interval`` seconds: ping each idle pooled connection, one at a time.

    One at a time, so a request arriving meanwhile still finds an idle
    connection; the pool is FIFO, so successive checkouts walk the idle ones.
    Connections near ``pool_recycle`` age are replaced here, and the pool is
    topped back up to ``pool_size`` (a dropped connection is reopened in the
    background, not on a request).
    """

    def __init__(self, engine: AsyncEngine, *, interval: float, recycle: float, target: int):
        self._engine = engine
        self._interval = interval
        self._replace_older_than = max(recycle - 3 * interval, interval) if recycle > 0 else None
        self._target = target
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run(), name="api-db-keepwarm")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def tick(self) -> None:
        pool: Any = self._engine.pool
        idle = int(pool.checkedin())
        for _ in range(idle):
            await _ping_one(self._engine, replace_older_than=self._replace_older_than)
        missing = self._target - int(pool.checkedin()) - int(pool.checkedout())
        if missing > 0:
            # Held at once, the idle ones AND the missing ones: holding only
            # `missing` would just check the idle ones out again.
            await warm_pool(self._engine, int(pool.checkedin()) + missing)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("api_db_keepwarm_failed", exc_info=True)


async def start_api_pool(engine: AsyncEngine) -> PoolKeepWarm | None:
    """Startup: warm the pool, then start the keep-warm task (Postgres only)."""
    if engine.dialect.name != "postgresql":
        return None
    settings = api_pool_settings()
    target = int(settings["pool_size"])
    started = time.monotonic()
    try:
        opened = await asyncio.wait_for(warm_pool(engine, target), timeout=30)
    except TimeoutError:
        opened = 0
        logger.warning("api_db_pool_warm_timeout")
    logger.info(
        "api_db_pool_warmed",
        extra={"connections": opened, "ms": round((time.monotonic() - started) * 1000)},
    )
    keepwarm = PoolKeepWarm(
        engine,
        interval=settings["keepwarm"],
        recycle=settings["pool_recycle"],
        target=target,
    )
    keepwarm.start()
    return keepwarm


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
        engine = create_async_engine(database_url, poolclass=NullPool, **ENGINE_DEFAULTS)
        factory = create_session_factory(engine)
        _worker_factories[database_url] = factory
        init_session_factory(factory)
    return factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async database session.

    Tenant context is set by route dependencies (get_active_shop)
    or task wrappers (@task_with_tenant_context) via contextvars.
    Issue #1327, ADR-085 decision 2.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Session factory not configured. Call init_session_factory() at app startup."
        )
    async with _session_factory() as session:
        yield session
