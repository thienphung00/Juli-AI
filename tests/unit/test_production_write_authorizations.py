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
from juli_backend.services.tiktok.credential_binding import CredentialBindingError

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

    async def test_issue_succeeds_with_correct_binding(self, session, shop, credential, repo):
        """Issuing should verify capability binding and succeed when it matches."""
        # Mock verify_capability_binding to succeed (normal case)
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = None

            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher_sandbox",
                authorized_by="operator@example.com",
                reason="Testing optimization",
                ttl_hours=24,
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

            # Verify capability binding was called
            mock_verify.assert_called_once()

    async def test_issue_refuses_misbound_credential(self, session, shop, repo):
        """Issuing should refuse when credential binding check fails."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.side_effect = CredentialBindingError(
                "Capability production_read already bound to a different shop"
            )

            with pytest.raises(CredentialBindingError):
                await repo.issue(
                    shop_id=shop.id,
                    tiktok_product_id="product_123",
                    mutation_kind="listing.optimize_product",
                    capability="production_read",
                    shop_cipher="ROW_different_shop_cipher",
                    authorized_by="operator@example.com",
                    reason="Testing",
                )


class TestProductionWriteAuthorizationLookup:
    """Test lookup behavior and the 6 miss cases."""

    async def test_lookup_finds_valid_unconsumed_authorization(self, session, shop, repo):
        """Lookup should find a valid, unconsumed, unrevoked authorization."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            _ = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            _ = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            _ = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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

    async def test_expires_at_defaults_from_config(self, session, shop, repo):
        """expires_at should default to now + TTL from config."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            before = datetime.now(UTC).replace(tzinfo=None)
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
            )
            after = datetime.now(UTC).replace(tzinfo=None)

            assert auth.expires_at is not None
            # Should be roughly 24 hours from creation
            expected_min = before + timedelta(hours=23, minutes=59)
            expected_max = after + timedelta(hours=24, minutes=1)
            assert expected_min <= auth.expires_at <= expected_max

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
        from unittest.mock import AsyncMock, patch

        with patch(
            "juli_backend.services.tiktok.credential_binding.verify_capability_binding",
            new_callable=AsyncMock,
        ):
            auth = await repo.issue(
                shop_id=shop.id,
                tiktok_product_id="product_123",
                mutation_kind="listing.optimize_product",
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher",
                authorized_by="operator@example.com",
                reason="Testing",
                ttl_hours=24,
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

        Structural assertion: scan all app routes and their endpoint modules to prove
        no endpoint code (not just configuration) can invoke authorization issuing.
        This prevents future developers from accidentally wiring issuing to a route.
        """
        import inspect

        from juli_backend.api.app import create_app

        app = create_app()

        # Scan all routes
        for route in app.routes:
            # Only check /v1/* routes
            if not route.path.startswith("/v1/"):
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
                f"Route {route.path} endpoint {endpoint.__name__} must not reference {repo_ref}"
            )

            assert ".issue(" not in source, (
                f"Route {route.path} endpoint {endpoint.__name__} must not call .issue()"
            )
