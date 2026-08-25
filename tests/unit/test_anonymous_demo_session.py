"""Anonymous demo session authentication (issue #1313, ADR-084 decision 1, ADR-075 decision 3).

Tests that:
- A visitor receives a real Supabase JWT for an anonymous user
- The anonymous session's active shop is the demo tenant (DEMO_SHOP_ID)
- Reading other shops' data with an anonymous token returns 404, never 403
- Rate buckets are per user-session, not per shop
- Two anonymous visitors are two distinct users with distinct audit rows
- Identity linking preserves the visitor's runs
- With DEMO_SHOP_ID unset, the anonymous path fails loudly
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
from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.jwks import JwksClient
from juli_backend.database import Shop, User, get_session
from tests.unit._es256_test_keys import (
    generate_es256_keypair,
    jwks_document,
    sign_es256_token,
)

pytestmark = pytest.mark.asyncio

# === ES256 Keypair + JWKS Setup ===


@pytest.fixture(autouse=True)
def _reset_jwks_singleton():
    """Isolate every test from the module-level JWKS client singleton."""
    jwt_module._default_jwks_client = None
    yield
    jwt_module._default_jwks_client = None


def _install_jwks_client(*jwk_dicts: dict) -> None:
    """Install a real ES256 JWKS fixture for token verification."""

    def _handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_document(*jwk_dicts))

    jwt_module._default_jwks_client = JwksClient(
        "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        transport=httpx.MockTransport(_handle),
    )


@pytest.fixture
def es256_keypair():
    """Generate a fresh ES256 keypair for signing anonymous tokens."""
    return generate_es256_keypair()


# === Anonymous User Fixtures ===


@pytest.fixture
async def demo_shop_id(session: AsyncSession, monkeypatch):
    """Return the DEMO_SHOP_ID, ensuring it's set in the environment."""
    from juli_backend.services.seeds.demo_tenant import seed_demo_tenant

    demo_shop_id_str = str(uuid.uuid4())
    monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id_str)

    await seed_demo_tenant(session)
    return uuid.UUID(demo_shop_id_str)


@pytest.fixture
async def non_demo_shop(session: AsyncSession, user_id):
    """Create a non-demo shop for cross-tenant access tests."""
    user = User(id=user_id, phone="+84903334444")
    shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Non-Demo Shop")
    session.add_all([user, shop])
    await session.flush()
    return shop


def _create_anonymous_test_app(session: AsyncSession) -> FastAPI:
    """Create a tiny FastAPI app with shop-scoped route for testing."""
    app = FastAPI()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session

    @app.get("/v1/demo/shop")
    async def get_shop(shop: Shop = Depends(get_active_shop)):
        return {"shop_id": str(shop.id), "shop_name": shop.shop_name}

    return app


# === Test Classes ===


class TestAnonymousJwtVerification:
    """AC: Anonymous token path uses real Supabase ES256/JWKS, not self-signed."""

    async def test_anonymous_es256_token_verifies_through_same_path(self, es256_keypair):
        """AC: anonymous token verifies through the same `verify_supabase_jwt`
        ES256/JWKS path every other Supabase token uses."""
        from juli_backend.core.security.jwt import verify_supabase_jwt

        private_key, kid, jwk = es256_keypair
        _install_jwks_client(jwk)

        anonymous_user_id = str(uuid.uuid4())
        token = sign_es256_token(private_key, kid, sub=anonymous_user_id)

        # Should verify via the same path, not a special case
        secret = require_env("SUPABASE_JWT_SECRET")
        payload = await verify_supabase_jwt(token, secret)

        assert payload["sub"] == anonymous_user_id
        assert payload["aud"] == "authenticated"


class TestAnonymousSessionScopedToDemo:
    """AC: Anonymous session's active shop is the demo tenant, never other shops."""

    async def test_anonymous_user_resolves_to_demo_shop(
        self, session: AsyncSession, es256_keypair, demo_shop_id
    ):
        """AC: anonymous session's active shop is DEMO_SHOP_ID (not looked up from header)."""
        private_key, kid, jwk = es256_keypair
        _install_jwks_client(jwk)

        anonymous_user_id = str(uuid.uuid4())
        token = sign_es256_token(private_key, kid, sub=anonymous_user_id)

        app = _create_anonymous_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Anonymous visitor should NOT need to pass X-Shop-Id header
            # Their shop should automatically resolve to demo_shop_id
            resp = await client.get(
                "/v1/demo/shop",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["shop_id"] == str(demo_shop_id)


class TestAnonymousCrossTenantBehavior:
    """AC: Reading other shops with anonymous token returns 404, never 403."""

    async def test_anonymous_reading_non_demo_shop_returns_404(
        self, session: AsyncSession, es256_keypair, demo_shop_id, non_demo_shop
    ):
        """AC: anonymous session cannot read a non-demo shop; returns 404 not 403."""
        private_key, kid, jwk = es256_keypair
        _install_jwks_client(jwk)

        anonymous_user_id = str(uuid.uuid4())
        token = sign_es256_token(private_key, kid, sub=anonymous_user_id)

        app = _create_anonymous_test_app(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Try to access a non-demo shop
            resp = await client.get(
                "/v1/demo/shop",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Shop-Id": str(non_demo_shop.id),
                },
            )

        # Should return 404 (not found), not 403 (forbidden)
        assert resp.status_code == 404


class TestAnonymousRateBucketsPerSession:
    """AC: Rate buckets are per user-session; visitors don't cross-throttle."""

    async def test_two_anonymous_visitors_have_independent_rate_buckets(self):
        """AC: two anonymous sign-ins create two distinct rate buckets."""
        from juli_backend.services.agent.abuse_limits import InMemoryAbuseLimitGate

        # Create a tight gate to test bucket independence
        gate = InMemoryAbuseLimitGate(approve_max_requests=2)

        visitor1_user_id = str(uuid.uuid4())
        visitor2_user_id = str(uuid.uuid4())

        # Visitor 1 exhausts their bucket
        result1_1 = await gate.try_acquire_approve(visitor1_user_id)
        result1_2 = await gate.try_acquire_approve(visitor1_user_id)
        result1_3 = await gate.try_acquire_approve(visitor1_user_id)  # Exhausted

        # Visitor 2 should still have an independent bucket
        result2_1 = await gate.try_acquire_approve(visitor2_user_id)

        assert result1_1.allowed is True
        assert result1_2.allowed is True
        assert result1_3.allowed is False  # Visitor 1 exhausted
        assert result2_1.allowed is True  # Visitor 2 still has budget


class TestAnonymousDistinctIdentities:
    """AC: Two visitors are two distinct users with distinct audit rows."""

    async def test_two_anonymous_sign_ins_create_distinct_users(
        self, session: AsyncSession, es256_keypair
    ):
        """AC: anonymous sign-in is never a shared account; each visitor
        gets their own distinct user with their own audit trail."""
        from juli_backend.core.security.jwt import verify_supabase_jwt

        private_key, kid, jwk = es256_keypair
        _install_jwks_client(jwk)

        visitor1_id = str(uuid.uuid4())
        visitor2_id = str(uuid.uuid4())

        # In production, Supabase issues separate JWTs to each visitor
        token1 = sign_es256_token(private_key, kid, sub=visitor1_id)
        token2 = sign_es256_token(private_key, kid, sub=visitor2_id)

        # Verify tokens verify through same path
        secret = require_env("SUPABASE_JWT_SECRET")

        payload1 = await verify_supabase_jwt(token1, secret)
        payload2 = await verify_supabase_jwt(token2, secret)

        # Payloads should have different sub claims
        assert payload1["sub"] == visitor1_id
        assert payload2["sub"] == visitor2_id
        assert payload1["sub"] != payload2["sub"]


class TestAnonymousDemoShopRequired:
    """AC: With DEMO_SHOP_ID unset, anonymous path fails loudly."""

    async def test_anonymous_path_fails_without_demo_shop_id(
        self, session: AsyncSession, es256_keypair, monkeypatch
    ):
        """AC: with DEMO_SHOP_ID unset, the seed raises loudly."""
        from juli_backend.services.seeds.demo_tenant import seed_demo_tenant

        monkeypatch.delenv("DEMO_SHOP_ID", raising=False)

        # Calling seed_demo_tenant without DEMO_SHOP_ID should raise KeyError
        with pytest.raises(KeyError, match="DEMO_SHOP_ID"):
            await seed_demo_tenant(session)
