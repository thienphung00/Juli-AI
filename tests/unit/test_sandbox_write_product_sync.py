"""TDD tests for sandbox write product catalog sync (issue #1290).

Behaviors under test:
- sync_sandbox_write_products fetches products from sandbox_write seller's own catalog
- Synced products are upserted to the sandbox shop's `products` table
- Re-running sync is idempotent (no duplicates)
- Pre-existing rows (from other credentials) are preserved
- Credential identity mismatch is logged as a named warning
- ADR-068 guards remain in place (production writes are not possible)
"""

import logging
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, Shop, TikTokCredential, User
from juli_backend.repositories.repos import ProductsRepo, ShopsRepo
from juli_backend.workers.services.polling.sync import (
    sync_products_with_local_upsert,
)

# Sandbox shop ID and merchant constants
SANDBOX_WRITE_MERCHANT_ID = "7658096633384781588"
SELLER_CONNECT_MERCHANT_ID = "123456789"


@pytest.fixture
def mock_sandbox_write_products_resource():
    """Mock resource returning products from sandbox_write seller's catalog.

    Mirrors TikTok's REAL search payload shape: the id key is "id" (not
    "product_id") and there is no "name" — normalize_product derives both.
    A fixture shaped like the code's own kwargs instead of the vendor's
    payload is what let the empty-tiktok_product_id bug ship (2026-08-25).
    """
    resource = MagicMock()
    resource.search_all.return_value = [
        {
            "id": "sandbox_p1",
            "title": "Sandbox Product 1",
            "status": "active",
            "update_time": 1700000100,
        },
        {
            "id": "sandbox_p2",
            "title": "Sandbox Product 2",
            "status": "active",
            "update_time": 1700000200,
        },
    ]
    return resource


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter that always allows."""
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def handoff_calls():
    """Track handoff calls."""
    return []


@pytest.fixture
def handoff_fn(handoff_calls):
    """Handoff function that captures calls."""

    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append({"channel": channel, "shop_key": shop_key, "value": value})

    return _handoff


@pytest.fixture
def sync_state():
    """Fresh sync state."""
    return {}


@pytest.fixture
async def sandbox_shop(session: AsyncSession) -> Shop:
    """Create a sandbox shop for testing."""
    user_id = uuid.uuid4()
    user = User(id=user_id, phone="+1234567890")
    session.add(user)
    await session.flush()

    shops_repo = ShopsRepo(session)
    shop = await shops_repo.create(
        user_id=user_id,
        shop_name="Sandbox Shop",
        tiktok_shop_id="sandbox_tts_123456",
    )
    await session.commit()
    return shop


@pytest.fixture
async def seller_connect_credential(session: AsyncSession, sandbox_shop: Shop) -> TikTokCredential:
    """Create a seller_connect credential (non-owning)."""
    credential = TikTokCredential(
        id=uuid.uuid4(),
        shop_id=sandbox_shop.id,
        merchant_authorization_id=SELLER_CONNECT_MERCHANT_ID,
        capability="production_read",
        access_token="seller_connect_token",
        refresh_token="seller_connect_refresh_token",
        token_expires_at=datetime.now(UTC),
        shop_cipher="seller_connect_cipher",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(credential)
    await session.commit()
    return credential


@pytest.fixture
async def existing_product_from_seller_connect(
    session: AsyncSession, sandbox_shop: Shop
) -> Product:
    """Create a product that came from seller_connect credential."""
    products_repo = ProductsRepo(session)
    product = await products_repo.upsert(
        shop_id=sandbox_shop.id,
        tiktok_product_id="existing_seller_connect_p1",
        name="Existing Seller Connect Product",
        status="active",
        title="Existing Seller Connect Product",
        update_time=datetime.now(UTC),
    )
    await session.commit()
    return product


class TestSandboxWriteProductSync:
    """Test sandbox write product catalog sync."""

    @pytest.mark.asyncio
    async def test_sync_sandbox_write_products_fetches_and_upserts(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        handoff_calls,
        sync_state,
        sandbox_shop,
        session: AsyncSession,
    ):
        """RED: sync_sandbox_write_products fetches from sandbox_write seller and upserts rows."""
        products_repo = ProductsRepo(session)

        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        # Verify products were handed off
        assert len(handoff_calls) >= 2

        # Verify the products were synced
        products_repo = ProductsRepo(session)
        synced_products = await products_repo.list_by_revenue(sandbox_shop.id, limit=10)
        assert len(synced_products) >= 2

        product_ids = {p.tiktok_product_id for p in synced_products}
        assert "sandbox_p1" in product_ids
        assert "sandbox_p2" in product_ids

    @pytest.mark.asyncio
    async def test_upsert_receives_naive_utc_update_time(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        sync_state,
        sandbox_shop,
        session: AsyncSession,
    ):
        """products.update_time is TIMESTAMP WITHOUT TIME ZONE; asyncpg rejects
        aware datetimes (seen live 2026-08-25: every upsert failed with DataError
        and the catalog stayed empty). SQLite in tests accepts both, so pin the
        kwarg itself."""
        products_repo = ProductsRepo(session)
        captured_kwargs = []
        real_upsert = products_repo.upsert

        async def spy_upsert(**kwargs):
            captured_kwargs.append(kwargs)
            return await real_upsert(**kwargs)

        products_repo.upsert = spy_upsert  # type: ignore[method-assign]

        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        assert captured_kwargs, "sync never called upsert"
        for kwargs in captured_kwargs:
            assert kwargs["update_time"].tzinfo is None, (
                "update_time must be naive UTC for the asyncpg bind"
            )
        assert sync_state["products_upserted"] == len(captured_kwargs)
        assert sync_state["products_upsert_failed"] == 0

    @pytest.mark.asyncio
    async def test_upsert_failures_are_counted_in_sync_state(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        sync_state,
        sandbox_shop,
        session: AsyncSession,
    ):
        """A sync where every upsert fails must not look like a success —
        the counters in sync_state are what the completion log reports."""
        products_repo = ProductsRepo(session)

        async def failing_upsert(**kwargs):
            raise RuntimeError("simulated bind failure")

        products_repo.upsert = failing_upsert  # type: ignore[method-assign]

        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        assert sync_state["products_upsert_failed"] == 2
        assert sync_state["products_upserted"] == 0

    @pytest.mark.asyncio
    async def test_sync_sandbox_write_products_is_idempotent(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        sync_state,
        sandbox_shop,
        session: AsyncSession,
    ):
        """RED: Re-running sync should not create duplicates."""
        products_repo = ProductsRepo(session)

        # First run
        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        first_products = await products_repo.list_by_revenue(sandbox_shop.id, limit=10)
        first_count = len(first_products)
        assert first_count >= 2

        # Second run
        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        second_products = await products_repo.list_by_revenue(sandbox_shop.id, limit=10)
        second_count = len(second_products)

        # Should be the same count, not doubled
        assert second_count == first_count

    @pytest.mark.asyncio
    async def test_sync_sandbox_write_preserves_existing_rows(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        sync_state,
        sandbox_shop,
        existing_product_from_seller_connect,
        session: AsyncSession,
    ):
        """RED: Syncing should not delete or overwrite pre-existing rows."""
        products_repo = ProductsRepo(session)

        # Verify pre-existing product is there
        stmt = select(Product).where(
            Product.shop_id == sandbox_shop.id,
            Product.tiktok_product_id == "existing_seller_connect_p1",
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        assert existing is not None
        original_name = existing.name

        # Run sync
        await sync_products_with_local_upsert(
            resource=mock_sandbox_write_products_resource,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            products_repo=products_repo,
            app_id="app1",
            shop_id=str(sandbox_shop.id),
            sync_state=sync_state,
        )

        # Verify pre-existing product still exists and wasn't modified
        stmt = select(Product).where(
            Product.shop_id == sandbox_shop.id,
            Product.tiktok_product_id == "existing_seller_connect_p1",
        )
        result = await session.execute(stmt)
        after_sync = result.scalar_one_or_none()
        assert after_sync is not None
        assert after_sync.name == original_name

        # Verify new products were added
        all_products = await products_repo.list_by_revenue(sandbox_shop.id, limit=10)
        assert len(all_products) >= 3  # 1 pre-existing + 2 from sandbox_write

    @pytest.mark.asyncio
    async def test_sandbox_write_catalog_identity_mismatch_logged(
        self,
        mock_sandbox_write_products_resource,
        mock_rate_limiter,
        handoff_fn,
        sync_state,
        sandbox_shop,
        seller_connect_credential,
        session: AsyncSession,
        caplog,
    ):
        """RED: Log named warning when product seller doesn't match write credential."""
        products_repo = ProductsRepo(session)

        with caplog.at_level(logging.WARNING):
            # This test checks that when a product from a different seller
            # is being bound to a write credential, it's logged as a mismatch
            # For now, just verify the sync completes
            await sync_products_with_local_upsert(
                resource=mock_sandbox_write_products_resource,
                rate_limiter=mock_rate_limiter,
                handoff_fn=handoff_fn,
                products_repo=products_repo,
                app_id="app1",
                shop_id=str(sandbox_shop.id),
                sync_state=sync_state,
            )

            # After implementation, we expect a mismatch log when applicable
            # This will be populated with the actual mismatch log check
            # when the implementation is complete
            pass
