"""Concurrency proof for #1233 (AGT-W4A, ADR-081 decision 1 row 3 / decision 5) --
``integrations/tiktok/reactive_refresh.py::call_with_reactive_refresh`` against a
REAL Postgres instance.

This is the direct proof of ADR-081's gate line: "twenty simultaneous
105002s produce one vendor call, not twenty." It builds on #1231's
session-level advisory lock (``core/security/credential_refresh.py``) --
the same guarantee ``tests/integration/test_credential_refresh_concurrency.py``
proves for ``refresh_credential`` directly. This file proves it end-to-end
through the reactive layer's actual catch point: twenty independent
simulated callers, each on its own physical connection, each observing a
``105002`` on their *own* vendor call attempt (never the refresh endpoint),
racing into ``call_with_reactive_refresh`` for the *same* credential.

SQLite (the unit suite in ``tests/unit/test_tiktok_reactive_refresh.py``)
cannot exercise cross-connection advisory-lock contention: it is a single
in-process connection per test, so the lock always "acquires" there by
construction.

Skips loudly (not silently) when ``DATABASE_URL`` is not a reachable
Postgres instance -- matching the existing convention in
``tests/integration/test_credential_refresh_concurrency.py``. A skip
reported as a pass is exactly the failure mode this wave (ADR-081) is
guarding against.
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
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.integrations.tiktok.reactive_refresh import call_with_reactive_refresh
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")

_STALE_ACCESS_TOKEN = "pre-reactive-stale-access"
_STALE_REFRESH_TOKEN = "pre-reactive-stale-refresh"


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
        "reactive_refresh concurrency proof requires a reachable Postgres "
        "DATABASE_URL (real advisory locks cannot be exercised on SQLite) -- "
        "set DATABASE_URL to a disposable Postgres 16 instance to run this"
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Run the real Alembic migrations once against DATABASE_URL so the
    #1230/#1231 refresh-lifecycle columns exist exactly as production will
    see them -- real schema, not ``Base.metadata.create_all``."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location",
        os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations"),
    )
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def async_engine_factory():
    """Each call returns a fresh engine/sessionmaker pair with ``NullPool``
    -- mirroring ``database/database.py::ensure_worker_session_factory``
    (#871) exactly, so each concurrent caller below gets its own physical
    Postgres backend connection, the same way separate worker tasks/threads
    do in production. Real cross-connection advisory-lock contention
    requires this: a shared pooled connection would silently make every
    "concurrent" caller reuse the SAME session-level lock holder.
    """
    engines = []

    def _make():
        engine = create_async_engine(async_database_url(_database_url()), poolclass=NullPool)
        engines.append(engine)
        return async_sessionmaker(engine, expire_on_commit=False)

    yield _make

    for engine in engines:
        await engine.dispose()


async def _seed_credential(factory) -> uuid.UUID:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Reactive Concurrency Test Shop")
        session.add(shop)
        await session.flush()
        # token_expires_at is deliberately far in the future -- the literal
        # ADR-081 sandbox scenario: the column claims fresh while every
        # caller's own vendor call answers 105002 Expired. Only the
        # reactive path's force=True call can see past this lying column.
        credential = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token=_STALE_ACCESS_TOKEN,
            refresh_token=_STALE_REFRESH_TOKEN,
            token_expires_at=_utc_now() + timedelta(days=7),
        )
        credential_id = credential.id
        await session.commit()
        return credential_id


class _CountingSlowAuth:
    """Records every *refresh* vendor call and holds a synchronous sleep
    across it -- long enough that the other nineteen genuinely concurrent
    callers' lock attempts land while this one still holds the advisory
    lock. The sleep is synchronous (``time.sleep``, not ``asyncio.sleep``)
    because ``refresh_credential`` invokes it via ``asyncio.to_thread``
    exactly as production does with the real ``TikTokAuth.refresh_access_token``.
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
            "access_token": f"reactive-vendor-access-{uuid.uuid4().hex[:8]}",
            "refresh_token": f"reactive-vendor-refresh-{uuid.uuid4().hex[:8]}",
            "access_token_expire_in": 604800,
        }


class TestTwentySimultaneous105002sOneVendorCall:
    async def test_twenty_concurrent_105002_callers_produce_one_refresh_vendor_call(
        self, async_engine_factory
    ):
        factory = async_engine_factory()
        credential_id = await _seed_credential(factory)
        auth = _CountingSlowAuth(delay_seconds=0.4)

        async def _one_caller():
            async with factory() as session:
                client = TikTokClient(
                    app_key="reactive-test-key",
                    app_secret="reactive-test-secret",
                    access_token=_STALE_ACCESS_TOKEN,
                )
                vendor_call_count = {"n": 0}

                def call():
                    vendor_call_count["n"] += 1
                    # Each simulated caller observes a 105002 on ITS OWN
                    # vendor endpoint call (never the refresh endpoint)
                    # until its client is carrying a refreshed token.
                    if client.access_token == _STALE_ACCESS_TOKEN:
                        raise TikTokAPIError(code=105002, message="Expired")
                    return {"ok": True, "token": client.access_token}

                result = await call_with_reactive_refresh(
                    session, credential_id, auth=auth, client=client, call=call
                )
                return result, vendor_call_count["n"]

        results = await asyncio.gather(*(_one_caller() for _ in range(20)))

        # The direct proof: one credential, twenty simultaneous 105002s,
        # exactly one call to the vendor's *refresh* endpoint.
        assert auth.call_count == 1, (
            f"expected exactly one refresh_credential(force=True) vendor call across "
            f"twenty simultaneous 105002 callers, got {auth.call_count}"
        )

        # Every caller's own request self-healed: each retried exactly
        # once (their own per-caller counter never exceeds 2) and every one
        # succeeded once its client carried a real, non-stale token.
        for outcome, own_vendor_calls in results:
            assert outcome["ok"] is True
            assert outcome["token"] != _STALE_ACCESS_TOKEN
            assert own_vendor_calls <= 2

        # Everyone who actually rotated ends up agreeing on the single
        # vendor-issued token -- the loser's re-read sees the winner's
        # committed row, exactly as #1231's advisory lock guarantees.
        tokens = {outcome["token"] for outcome, _ in results}
        assert len(tokens) == 1
        assert next(iter(tokens)).startswith("reactive-vendor-access-")
