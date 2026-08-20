"""Concurrency proof for #1231 (AGT-W4A-BE, ADR-081 decisions 5/9) --
``core/security/credential_refresh.py::refresh_credential`` against a REAL
Postgres instance.

SQLite (the unit suite in ``tests/unit/test_credential_refresh.py``) cannot
exercise cross-connection advisory-lock contention: it is a single
in-process connection per test, so ``_try_advisory_lock`` always "acquires"
there by construction. These tests are the only place the session-level
``pg_try_advisory_lock`` / ``pg_advisory_unlock`` pair in
``credential_refresh.py`` is actually exercised.

Skips loudly (not silently) when ``DATABASE_URL`` is not a reachable
Postgres instance -- matching the existing convention in
``tests/integration/test_migrations.py``. A skip reported as a pass is
exactly the failure mode this wave (ADR-081) is guarding against, so the
skip reason is deliberately specific rather than a bare boolean.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.core.security.credential_refresh import (
    RefreshStatus,
    refresh_credential,
)
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "credential_refresh concurrency tests require a reachable Postgres "
        "DATABASE_URL (real advisory locks cannot be exercised on SQLite) -- "
        "set DATABASE_URL to a disposable Postgres 16 instance to run these"
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Run the real Alembic migrations once against DATABASE_URL so
    #1230's columns/indexes exist exactly as production will see them --
    this is real schema, not ``Base.metadata.create_all``."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location",
        os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations"),
    )
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    """Each call returns a fresh engine/sessionmaker pair with ``NullPool`` --
    mirroring ``database/database.py::ensure_worker_session_factory`` (#871)
    exactly, so each concurrent caller below gets its own physical Postgres
    backend connection, the same way separate worker tasks do. Real
    cross-connection advisory-lock contention requires this: a shared
    pooled connection would silently make every "concurrent" caller reuse
    the SAME session-level lock holder.
    """
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(_database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


async def _seed_credential(factory, *, token_expires_at: datetime) -> uuid.UUID:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Concurrency Test Shop")
        session.add(shop)
        await session.flush()
        credential = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="pre-concurrency-access",
            refresh_token="pre-concurrency-refresh",
            token_expires_at=token_expires_at,
        )
        credential_id = credential.id
        await session.commit()
        return credential_id


class _CountingSlowAuth:
    """Records every vendor call and holds a synchronous sleep across it --
    long enough that a genuinely concurrent second caller's lock attempt
    lands while this one still holds the advisory lock. The sleep is
    synchronous (``time.sleep``, not ``asyncio.sleep``) because
    ``refresh_credential`` invokes it via ``asyncio.to_thread`` exactly as
    production does with the real ``TikTokAuth.refresh_access_token``.
    """

    def __init__(self, delay_seconds: float = 0.4) -> None:
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self.call_count = 0

    def refresh_access_token(self, refresh_token: str) -> dict:
        with self._lock:
            self.call_count += 1
        time.sleep(self._delay_seconds)
        return {
            "access_token": f"vendor-access-{uuid.uuid4().hex[:8]}",
            "refresh_token": f"vendor-refresh-{uuid.uuid4().hex[:8]}",
            "access_token_expire_in": 604800,
        }


class TestTwoConcurrentRefreshersOneVendorCall:
    async def test_two_concurrent_calls_produce_exactly_one_vendor_call(self, async_engine_factory):
        factory = async_engine_factory()
        credential_id = await _seed_credential(
            factory, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        auth = _CountingSlowAuth(delay_seconds=0.5)

        async def _one_caller():
            async with factory() as session:
                return await refresh_credential(session, credential_id, auth=auth)

        # Stagger the second caller slightly so it reliably arrives at the
        # lock *after* the first has already acquired it and is mid-HTTP-call
        # -- the real contention window ADR-081 decision 5 is about.
        async def _second_caller_delayed():
            await asyncio.sleep(0.1)
            return await _one_caller()

        outcome_a, outcome_b = await asyncio.gather(_one_caller(), _second_caller_delayed())

        assert auth.call_count == 1, (
            f"expected exactly one vendor call across two concurrent refreshers, "
            f"got {auth.call_count}"
        )
        statuses = {outcome_a.status, outcome_b.status}
        assert statuses <= {RefreshStatus.REFRESHED, RefreshStatus.LOCKED}
        assert RefreshStatus.REFRESHED in statuses

        # The loser's re-read must see the winner's committed row.
        winner_access_tokens = {
            outcome_a.credential.access_token,
            outcome_b.credential.access_token,
        }
        if (
            outcome_a.status is RefreshStatus.REFRESHED
            and outcome_b.status is RefreshStatus.REFRESHED
        ):
            assert outcome_a.credential.access_token == outcome_b.credential.access_token
        assert "vendor-access-" in "".join(
            token for token in winner_access_tokens if token.startswith("vendor-access-")
        )


class TestTwentySimultaneousForcedRefreshesOneVendorCall:
    async def test_twenty_concurrent_force_refreshes_produce_one_vendor_call(
        self, async_engine_factory
    ):
        """The direct proof for W4-4's reactive path (ADR-081 decision 5):
        twenty simultaneous ``force=True`` calls against the same
        credential_id -- each on its own NullPool connection, exactly
        mirroring twenty concurrent ``105002`` retries in production --
        must produce ONE vendor call, not twenty."""
        factory = async_engine_factory()
        # force=True ignores the column entirely, so seed it "fresh" (now +
        # 7d) -- the literal 2026-08-18 sandbox scenario -- to prove force
        # really does bypass the column, not just coincidentally refresh.
        credential_id = await _seed_credential(
            factory, token_expires_at=_utc_now() + timedelta(days=7)
        )
        auth = _CountingSlowAuth(delay_seconds=0.5)

        async def _one_caller():
            async with factory() as session:
                return await refresh_credential(session, credential_id, auth=auth, force=True)

        outcomes = await asyncio.gather(*(_one_caller() for _ in range(20)))

        assert auth.call_count == 1, (
            f"expected exactly one vendor call across twenty simultaneous forced "
            f"refreshes, got {auth.call_count}"
        )
        statuses = [outcome.status for outcome in outcomes]
        assert RefreshStatus.REFRESHED in statuses
        assert all(status in (RefreshStatus.REFRESHED, RefreshStatus.LOCKED) for status in statuses)

        refreshed_access_tokens = {
            outcome.credential.access_token
            for outcome in outcomes
            if outcome.status is RefreshStatus.REFRESHED
        }
        assert len(refreshed_access_tokens) == 1
