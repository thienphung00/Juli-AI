"""#1906: a first-time Google `sub` gets provisioned exactly once, on real Postgres.

WHY THIS IS INTEGRATION-TIER, NOT THE SHARED `session` FIXTURE. Two things this
issue's provisioning branch depends on are Postgres-only: the
`users_insert_public` RLS policy (`WITH CHECK (id = app_current_user_id())`),
which only blocks or allows a write when a real row-level-security engine
evaluates it under the non-owner `juli_app` runtime role; and a real
unique-index row lock, which is what makes the concurrency assertion below
meaningful rather than an artifact of SQLite's single in-process connection.
`tests/unit/conftest.py::session` is SQLite even when `DATABASE_URL` names
Postgres, per this issue's release-evidence plan (`doNotInfer`) -- a
DB-level claim made through it would be untested. Every session here comes
from `tests.support.postgres.juli_app_async_sessionmaker` instead, one
physical connection per concurrent caller, the same shape
`tests/integration/test_credential_refresh_concurrency.py` already uses for
its own cross-connection race.

Skips loudly, not silently, when `DATABASE_URL` is not a reachable Postgres
(`tests.support.postgres.requires_postgres`).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.api.routes.shops import router as shops_router
from juli_backend.core.config.runtime import sync_database_url
from juli_backend.database.database import get_session
from tests.support.postgres import database_url, juli_app_async_sessionmaker, requires_postgres

pytestmark = [pytest.mark.asyncio, requires_postgres]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")

# Generated at import time, not a literal -- nothing here for a secret scanner to
# match, and it is exactly as usable as a hardcoded string for signing/verifying
# tokens within this one test run (#1906 gitleaks/security-scan finding).
TEST_JWT_SECRET = secrets.token_urlsafe(32)


@pytest.fixture(scope="module", autouse=True)
def _migrated_schema():
    """Run the real Alembic migrations once against DATABASE_URL, matching
    `test_credential_refresh_concurrency.py` -- this exercises the actual
    `users_insert_public` policy and `juli_app` grants (migrations 043/045),
    not a `Base.metadata.create_all` stand-in."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "script_location",
        os.path.join(REPO_ROOT, "backend/src/juli_backend/database/migrations"),
    )
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _jwt_secret_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)


def _make_token(
    sub: uuid.UUID | str, *, secret: str = TEST_JWT_SECRET, expired: bool = False
) -> str:
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return pyjwt.encode(
        {"sub": str(sub), "aud": "authenticated", "exp": exp}, secret, algorithm="HS256"
    )


def _app_for_session_factory(factory: async_sessionmaker) -> FastAPI:
    """A minimal app mounting the REAL `GET /v1/shops` route, backed by a
    fresh `juli_app`-scoped session per request -- one physical connection
    per call, the same as production's per-request `get_session`."""
    app = FastAPI()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.include_router(shops_router, prefix="/v1")
    return app


async def _get_shops(app: FastAPI, token: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/shops", headers={"Authorization": f"Bearer {token}"})


def _owner_engine():
    return create_engine(sync_database_url(database_url()))


def _users_row_count(sub: uuid.UUID) -> int:
    engine = _owner_engine()
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM users WHERE id = :id"), {"id": str(sub)}
            ).scalar_one()
    finally:
        engine.dispose()


def _users_row(sub: uuid.UUID):
    engine = _owner_engine()
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT id, phone FROM users WHERE id = :id"), {"id": str(sub)}
            ).fetchone()
    finally:
        engine.dispose()


class TestFirstTimeIdentityIsProvisionedOnce:
    async def test_first_request_provisions_exactly_one_row_and_returns_200_empty_shops(self):
        sub = uuid.uuid4()
        assert _users_row_count(sub) == 0

        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            resp = await _get_shops(app, _make_token(sub))

        assert resp.status_code == 200, resp.text
        assert resp.json() == []
        assert _users_row_count(sub) == 1

        row = _users_row(sub)
        assert row is not None
        assert str(row.id) == str(sub)
        assert row.phone, "the provisioned row must carry a derived placeholder phone"

    async def test_a_second_identical_request_creates_no_further_row(self):
        sub = uuid.uuid4()

        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            first = await _get_shops(app, _make_token(sub))
            second = await _get_shops(app, _make_token(sub))

        assert first.status_code == 200
        assert second.status_code == 200
        assert _users_row_count(sub) == 1

    async def test_the_provisioned_user_has_zero_shops(self):
        """Zero shops is the correct, honest state -- no shop, capability, or
        credential is granted alongside the provisioned row (#1906)."""
        sub = uuid.uuid4()

        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            resp = await _get_shops(app, _make_token(sub))

        assert resp.status_code == 200
        assert resp.json() == []


class TestTwoConcurrentFirstRequestsCreateExactlyOneRow:
    async def test_two_concurrent_requests_for_the_same_sub_both_succeed_with_one_row(self):
        """Real Postgres, real concurrency: the loser's INSERT blocks on the
        `users.id` unique-index lock until the winner commits, then raises
        `IntegrityError`, which `_provision_first_sighting` catches and turns
        into a re-read -- never surfaced to the caller."""
        sub = uuid.uuid4()
        token = _make_token(sub)

        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)

            async def _one_caller():
                return await _get_shops(app, token)

            async def _second_caller_delayed():
                await asyncio.sleep(0.05)
                return await _one_caller()

            resp_a, resp_b = await asyncio.gather(_one_caller(), _second_caller_delayed())

        assert resp_a.status_code == 200, resp_a.text
        assert resp_b.status_code == 200, resp_b.text
        assert resp_a.json() == []
        assert resp_b.json() == []
        assert _users_row_count(sub) == 1


class TestAnUnverifiedTokenProvisionsNothing:
    """ADR-061 / #902: the generic detail, never the parser's own reason --
    and no row for any of the three ways a token can fail to verify."""

    async def test_malformed_token_401_generic_detail_no_row(self):
        sub = uuid.uuid4()
        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            resp = await _get_shops(app, "not-a-jwt-at-all")

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired credentials"
        assert _users_row_count(sub) == 0

    async def test_expired_token_401_generic_detail_no_row(self):
        sub = uuid.uuid4()
        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            resp = await _get_shops(app, _make_token(sub, expired=True))

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired credentials"
        assert _users_row_count(sub) == 0

    async def test_wrongly_signed_token_401_generic_detail_no_row(self):
        sub = uuid.uuid4()
        async with juli_app_async_sessionmaker() as factory:
            app = _app_for_session_factory(factory)
            resp = await _get_shops(app, _make_token(sub, secret="wrong-secret"))

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired credentials"
        assert _users_row_count(sub) == 0
