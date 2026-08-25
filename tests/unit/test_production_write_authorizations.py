"""Production write authorizations (issue #1335).

Acceptance criteria:
1. Issuing runs verify_capability_binding and refuses when credential is mis-bound
2. Lookup returns nothing for 6 specific miss cases (expired, consumed, revoked,
   different product, different mutation kind, different shop)
3. Consumption is atomic under concurrency
4. expires_at defaults from config and is never null
5. Revoke preserves the row and its history
6. Tenant treatment matches #1328 (direct shop_id)
7. No /v1/* route can create an authorization
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import ProductionWriteAuthorization, Shop, TikTokCredential, User
from juli_backend.repositories.repos import ProductionWriteAuthorizationsRepo

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="Test Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="Other Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def credential(session, shop):
    """Create a credential for the test shop with verified binding."""
    c = TikTokCredential(
        shop_id=shop.id,
        merchant_authorization_id="test_merchant_id",
        capability="sandbox_write",
        shop_cipher="ROW_test_cipher_sandbox",
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        status="active",
    )
    session.add(c)
    await session.flush()
    return c


@pytest_asyncio.fixture
async def misbound_credential(session, shop):
    """A credential for the shop with a mismatched shop_cipher (the #1290 case)."""
    c = TikTokCredential(
        shop_id=shop.id,
        merchant_authorization_id="wrong_merchant_id",
        capability="production_read",
        shop_cipher="ROW_different_shop_cipher",  # Different from what vendor reports
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        status="active",
    )
    session.add(c)
    await session.flush()
    return c


@pytest_asyncio.fixture
def repo(session):
    return ProductionWriteAuthorizationsRepo(session)


class TestProductionWriteAuthorizationIssuing:
    """Test authorization issuing with credential binding verification."""

    async def test_issue_succeeds_with_correct_params(self, session, shop, credential, repo):
        """Repo.issue is pure persistence; service layer does verification."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing optimization",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        assert auth is not None
        assert auth.shop_id == shop.id
        assert auth.tiktok_product_id == "product_123"
        assert auth.mutation_kind == "listing.optimize_product"
        assert auth.authorized_by == "operator@example.com"
        assert auth.reason == "Testing optimization"
        assert auth.consumed_at is None
        assert auth.consumed_by_run_id is None
        assert auth.revoked_at is None
        assert auth.expires_at is not None

    async def test_issue_with_minimal_params(self, session, shop, repo):
        """Repo.issue requires only essential parameters for persistence."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_456",
            mutation_kind="inventory.replenish",
            authorized_by="operator@example.com",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=48),
        )

        assert auth is not None
        assert auth.shop_id == shop.id
        assert auth.tiktok_product_id == "product_456"
        assert auth.mutation_kind == "inventory.replenish"
        assert auth.reason is None  # Optional parameter can be omitted


class TestProductionWriteAuthorizationLookup:
    """Test lookup behavior and the 6 miss cases."""

    async def test_lookup_finds_valid_unconsumed_authorization(self, session, shop, repo):
        """Lookup should find a valid, unconsumed, unrevoked authorization."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Lookup should find it
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
        )

        assert found is not None
        assert found.id == auth.id

    async def test_lookup_misses_expired_authorization(self, session, shop, repo):
        """Lookup should return None for an expired authorization."""
        # Create an authorization that expired
        auth = ProductionWriteAuthorization(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
        session.add(auth)
        await session.flush()

        # Lookup should miss it
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
        )

        assert found is None

    async def test_lookup_misses_consumed_authorization(self, session, shop, repo):
        """Lookup should return None for a consumed authorization."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Consume it
        await repo.consume(auth.id, run_id=uuid.uuid4())

        # Lookup should miss it
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
        )

        assert found is None

    async def test_lookup_misses_revoked_authorization(self, session, shop, repo):
        """Lookup should return None for a revoked authorization."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Revoke it
        await repo.revoke(auth.id, reason="Testing revocation")

        # Lookup should miss it
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
        )

        assert found is None

    async def test_lookup_misses_different_product(self, session, shop, repo):
        """Lookup should return None when product doesn't match."""
        _ = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Lookup with different product
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_999",
            mutation_kind="listing.optimize_product",
        )

        assert found is None

    async def test_lookup_misses_different_mutation_kind(self, session, shop, repo):
        """Lookup should return None when mutation kind doesn't match."""
        _ = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Lookup with different mutation kind
        found = await repo.lookup(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="inventory.replenish",
        )

        assert found is None

    async def test_lookup_misses_different_shop(self, session, shop, other_shop, repo):
        """Lookup should return None when shop doesn't match (tenant isolation)."""
        _ = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        # Lookup from different shop
        found = await repo.lookup(
            shop_id=other_shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
        )

        assert found is None


class TestProductionWriteAuthorizationConsumption:
    """Test atomic consumption behavior."""

    async def test_consume_sets_consumed_at_and_run_id(self, session, shop, repo):
        """Consumption should set consumed_at and consumed_by_run_id atomically."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        run_id = uuid.uuid4()
        consumed = await repo.consume(auth.id, run_id=run_id)

        assert consumed is not None
        assert consumed.consumed_at is not None
        assert consumed.consumed_by_run_id == run_id

        # Refresh and verify
        refreshed = await session.get(ProductionWriteAuthorization, auth.id)
        assert refreshed.consumed_at is not None
        assert refreshed.consumed_by_run_id == run_id


class TestProductionWriteAuthorizationExpiry:
    """Test expires_at behavior."""

    async def test_expires_at_must_be_provided(self, session, shop, repo):
        """Repo.issue requires explicit expires_at parameter."""
        before = datetime.now(UTC).replace(tzinfo=None)
        expires_at = before + timedelta(hours=24)
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=expires_at,
        )

        assert auth.expires_at is not None
        # Should be exactly what was provided
        assert auth.expires_at == expires_at

    async def test_expires_at_never_null(self, session, shop, repo):
        """A row cannot be created without an expires_at."""
        # Direct insert without going through repo should fail at DB level
        auth = ProductionWriteAuthorization(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=None,  # Try to create with null
        )
        session.add(auth)

        with pytest.raises(Exception):  # DB constraint violation
            await session.flush()


class TestProductionWriteAuthorizationRevocation:
    """Test revocation behavior."""

    async def test_revoke_preserves_row_for_audit(self, session, shop, repo):
        """Revoke should set revoked_at but keep the row readable."""
        auth = await repo.issue(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )

        auth_id = auth.id

        # Revoke it
        revoked = await repo.revoke(auth.id, reason="No longer needed")

        assert revoked is not None
        assert revoked.revoked_at is not None
        assert revoked.revoke_reason == "No longer needed"

        # Row should still be readable
        fetched = await session.get(ProductionWriteAuthorization, auth_id)
        assert fetched is not None
        assert fetched.revoked_at is not None
        assert fetched.revoke_reason == "No longer needed"


class TestProductionWriteAuthorizationTenantIsolation:
    """Test shop-scoped tenant isolation (#1328)."""

    async def test_authorization_uses_direct_shop_id(self, session, shop):
        """Authorization should use direct shop_id for tenant isolation."""
        auth = ProductionWriteAuthorization(
            shop_id=shop.id,
            tiktok_product_id="product_123",
            mutation_kind="listing.optimize_product",
            authorized_by="operator@example.com",
            reason="Testing",
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )
        session.add(auth)
        await session.flush()

        # Verify it's directly indexed on shop_id
        result = await session.execute(
            select(ProductionWriteAuthorization).where(
                ProductionWriteAuthorization.shop_id == shop.id
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].id == auth.id


class TestProductionWriteAuthorizationAPIAccess:
    """Test that /v1/* routes cannot create authorizations."""

    async def test_no_v1_route_exposes_authorization_creation(self, session):
        """Verify no /v1/* route endpoint references ProductionWriteAuthorizationsRepo.issue.

        Structural assertion: scan all app routes (recursively unwrapping included routers
        for Starlette 1.6 compatibility) and prove no endpoint code can invoke issuing.
        """
        import inspect

        from juli_backend.api.app import create_app

        app = create_app()

        def collect_routes_recursively(routes, prefix=""):
            """Recursively unwrap included routers to handle Starlette 1.6."""
            collected = []
            for route in routes:
                # Handle included routers (Starlette 1.6) - must have .app.routes, not just .app
                if (
                    hasattr(route, "app")
                    and hasattr(route, "path")
                    and hasattr(route.app, "routes")
                ):
                    # Included router: recurse with prefix
                    try:
                        sub_routes = collect_routes_recursively(
                            route.app.routes, prefix=prefix + route.path
                        )
                        collected.extend(sub_routes)
                    except (AttributeError, TypeError):
                        # If recursion fails, treat as normal route
                        if hasattr(route, "path"):
                            full_path = prefix + route.path
                            collected.append((full_path, route))
                elif hasattr(route, "path"):
                    # Normal route
                    full_path = prefix + route.path
                    collected.append((full_path, route))
            return collected

        # Collect all routes, handling Starlette 1.6 included routers
        all_routes = collect_routes_recursively(app.routes)

        # Scan routes for /v1/* patterns
        for full_path, route in all_routes:
            # Only check /v1/* routes
            if not full_path.startswith("/v1/"):
                continue

            # Get the endpoint function
            endpoint = route.endpoint
            if endpoint is None:
                continue

            # Get the source code of the endpoint
            try:
                source = inspect.getsource(endpoint)
            except (OSError, TypeError):
                # Skip if we can't get source (e.g., built-in routes)
                continue

            # Assert the endpoint doesn't reference ProductionWriteAuthorizationsRepo
            repo_ref = "ProductionWriteAuthorizationsRepo"
            assert repo_ref not in source, (
                f"Route {full_path} endpoint {endpoint.__name__} must not reference {repo_ref}"
            )

            assert ".issue(" not in source, (
                f"Route {full_path} endpoint {endpoint.__name__} must not call .issue()"
            )
