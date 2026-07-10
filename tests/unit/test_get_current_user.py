"""AC2 — get_current_user validates JWT and returns User with shops.
AC3 — Missing/expired JWT returns 401 Unauthorized."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.dependencies import get_current_user
from juli_backend.database import User, Shop, get_session


pytestmark = pytest.mark.asyncio

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"


def _make_token(
    user_id: uuid.UUID,
    secret: str = TEST_JWT_SECRET,
    expired: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return pyjwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "exp": exp},
        secret,
        algorithm="HS256",
    )


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
            resp = await client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )

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
            resp = await client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )

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
            resp = await client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401

    async def test_invalid_signature_returns_401(self, session: AsyncSession, user_id):
        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(user_id, secret="wrong-secret")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401

    async def test_user_not_in_db_returns_401(self, session: AsyncSession):
        os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
        app = _create_test_app(session)
        token = _make_token(uuid.uuid4())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 401
