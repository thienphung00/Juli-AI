"""AC2 — get_current_user validates JWT and returns User with shops.
AC3 — Missing/expired JWT returns 401 Unauthorized.
Issue #894 — SUPABASE_JWT_SECRET must be obtained via the fail-fast require_env
helper; there must be no code path where an empty/missing secret verifies a
token."""

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.dependencies import get_current_user
from juli_backend.database import Shop, User, get_session

pytestmark = pytest.mark.asyncio

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"


def _make_token(
    user_id: uuid.UUID,
    secret: str = TEST_JWT_SECRET,
    expired: bool = False,
) -> str:
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return pyjwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "exp": exp},
        secret,
        algorithm="HS256",
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_raw_hs256_token(user_id: uuid.UUID, key: bytes, expired: bool = False) -> str:
    """Craft a JWT signed with an arbitrary raw HMAC key, bypassing PyJWT's
    encode-time InvalidKeyError guard against empty keys. Reproduces the
    forged-empty-key payload the ADR-061 finding describes: an attacker who
    knows the service falls back to `""` when the secret env var is unset
    can mint a token signed with that empty key."""
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "aud": "authenticated", "exp": int(exp.timestamp())}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session

    @app.get("/me")
    async def me(user: User = Depends(get_current_user)):
        return {"user_id": str(user.id), "phone": user.phone}

    return app


class TestGetCurrentUserExtractsContext:
    """AC2: Valid JWT → returns authenticated User."""

    async def test_valid_jwt_returns_user(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84901234567", display_name="Seller")
        session.add(user)
        await session.flush()

        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(user_id)
        assert resp.json()["phone"] == "+84901234567"

    async def test_valid_jwt_for_user_with_shops(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84909999999")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="My Shop")
        session.add_all([user, shop])
        await session.flush()

        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(user_id)


class TestMissingOrExpiredJwtReturns401:
    """AC3: Missing, expired, or invalid JWT → 401."""

    async def test_missing_auth_header_returns_401(self, session: AsyncSession):
        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me")

        assert resp.status_code == 401

    async def test_expired_jwt_returns_401(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84908888888")
        session.add(user)
        await session.flush()

        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id, expired=True)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401

    async def test_invalid_signature_returns_401(self, session: AsyncSession, user_id):
        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id, secret="wrong-secret")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401

    async def test_user_not_in_db_returns_401(self, session: AsyncSession):
        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(uuid.uuid4())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401


class TestJwtSecretFailsClosed:
    """Issue #894 — no defaulting lookup of SUPABASE_JWT_SECRET may ever be used
    to verify a token; the dependency must fail fast instead."""

    async def test_get_current_user_raises_when_secret_env_absent_defense_in_depth(
        self, session: AsyncSession, user_id, monkeypatch
    ):
        """Defence in depth only: calls the get_current_user dependency
        directly (not via a booted app) and asserts it raises when the
        variable is absent — it must NOT silently fall back to an
        empty-string key. This does NOT exercise app startup; the primary,
        startup-level assertion (ADR-061 / issue #926) is covered by
        tests/unit/test_api_main.py::TestLifespanAssertsJwtSecretAtStartup,
        which boots api/main.py's actual lifespan."""
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        token = _make_token(user_id)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
            await get_current_user(credentials=credentials, session=session)

    async def test_empty_key_signed_token_rejected_with_401(self, session: AsyncSession, user_id):
        """Exit gate: a token signed with an empty-string key is rejected with
        401 when the service is running with a real secret configured — the
        forged-empty-key attack the fail-open bug enabled must not succeed."""
        user = User(id=user_id, phone="+84901111111")
        session.add(user)
        await session.flush()

        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        forged_token = _make_raw_hs256_token(user_id, key=b"")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {forged_token}"})

        assert resp.status_code == 401

    async def test_correctly_signed_token_still_accepted(self, session: AsyncSession, user_id):
        """Exit gate: no regression to the happy path once the secret is
        obtained via require_env."""
        user = User(id=user_id, phone="+84902222222")
        session.add(user)
        await session.flush()

        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(user_id)
