"""Issue #1282, AGT-W5B -- end-to-end: an ES256 JWT reaches a shop-scoped
route through the real `get_current_user` -> `get_active_shop` dependency
chain, over HTTP, exactly as production traffic does.

`test_jwt_es256_verification.py` covers `verify_supabase_jwt` in isolation;
this file is the AC's "reaches a shop-scoped route" half, built the same
way `test_get_current_user.py` builds its HS256 equivalent -- a tiny
FastAPI app, a real ASGI transport, no auth dependency override.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import juli_backend.core.security.jwt as jwt_module
from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security.jwks import JwksClient
from juli_backend.database import Shop, User, get_session
from tests.unit._es256_test_keys import generate_es256_keypair, jwks_document, sign_es256_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_jwks_singleton():
    jwt_module._default_jwks_client = None
    yield
    jwt_module._default_jwks_client = None


def _install_jwks_client(*jwk_dicts: dict) -> None:
    def _handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_document(*jwk_dicts))

    jwt_module._default_jwks_client = JwksClient(
        "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        transport=httpx.MockTransport(_handle),
    )


def _create_shop_scoped_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session

    @app.get("/v1/shop-scoped")
    async def shop_scoped(shop: Shop = Depends(get_active_shop)):
        return {"shop_id": str(shop.id), "shop_name": shop.shop_name}

    return app


class TestEs256TokenReachesShopScopedRoute:
    async def test_valid_es256_token_reaches_shop_scoped_route(
        self, session: AsyncSession, user_id
    ):
        """AC: 'a token with alg: ES256 and a kid present in the project's
        JWKS verifies and reaches a shop-scoped route.'"""
        user = User(id=user_id, phone="+84903334444")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="ES256 Test Shop")
        session.add_all([user, shop])
        await session.flush()

        private_key, kid, jwk = generate_es256_keypair()
        _install_jwks_client(jwk)
        token = sign_es256_token(private_key, kid, sub=str(user_id))

        app = _create_shop_scoped_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/shop-scoped",
                headers={"Authorization": f"Bearer {token}", "X-Shop-Id": str(shop.id)},
            )

        assert resp.status_code == 200
        assert resp.json()["shop_id"] == str(shop.id)

    async def test_es256_token_signed_with_wrong_key_rejected_opaque_401(
        self, session: AsyncSession, user_id
    ):
        user = User(id=user_id, phone="+84903335555")
        session.add(user)
        await session.flush()

        _legit_private_key, kid, legit_jwk = generate_es256_keypair(kid="shop-scoped-kid")
        attacker_private_key, _kid2, _jwk2 = generate_es256_keypair()
        _install_jwks_client(legit_jwk)
        forged_token = sign_es256_token(attacker_private_key, kid, sub=str(user_id))

        app = _create_shop_scoped_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/shop-scoped",
                headers={"Authorization": f"Bearer {forged_token}", "X-Shop-Id": str(uuid.uuid4())},
            )

        assert resp.status_code == 401
        # #902 / ADR-061: the body stays opaque -- no parser detail leaked.
        assert resp.json() == {"detail": "Invalid or expired credentials"}

    async def test_es256_wrong_audience_rejected_opaque_401(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84903336666")
        session.add(user)
        await session.flush()

        private_key, kid, jwk = generate_es256_keypair()
        _install_jwks_client(jwk)
        token = sign_es256_token(private_key, kid, sub=str(user_id), aud="not-authenticated")

        app = _create_shop_scoped_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/shop-scoped",
                headers={"Authorization": f"Bearer {token}", "X-Shop-Id": str(uuid.uuid4())},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid or expired credentials"}

    async def test_unreachable_jwks_fails_closed_opaque_401(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84903337777")
        session.add(user)
        await session.flush()

        private_key, kid, _jwk = generate_es256_keypair()

        def _raise(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        jwt_module._default_jwks_client = JwksClient(
            "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
            transport=httpx.MockTransport(_raise),
        )
        token = sign_es256_token(private_key, kid, sub=str(user_id))

        app = _create_shop_scoped_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/shop-scoped",
                headers={"Authorization": f"Bearer {token}", "X-Shop-Id": str(uuid.uuid4())},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid or expired credentials"}
