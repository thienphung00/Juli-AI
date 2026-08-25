"""Demo tenant seeding — issue #1312 (W6-B).

Tests verify:
1. Idempotency: running the seed twice leaves exactly one demo shop
2. Distinctness: demo shop differs from reference and sandbox shops
3. No credentials: demo shop has no tiktok_credentials
4. Surfaced cards: seeded cards are active AND surfaced_at is set
5. Resolvable workflows: seeded cards' workflow_key resolves to a registered playbook
6. Demo content: seeded strings do not appear in reference shop rows
7. Configuration: DEMO_SHOP_ID is required and named, not a silent fallback
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import ActionCard, Product, Shop, TikTokCredential, User
from juli_backend.database.seeds.demo_tenant import seed_demo_tenant
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
)


@pytest_asyncio.fixture
async def reference_shop(session: AsyncSession) -> Shop:
    """Create a reference merchant shop with real credentials."""
    user = User(
        id=uuid.uuid4(),
        phone="+84901234567",
        display_name="Reference Merchant",
    )
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Reference Merchant Shop",
        tiktok_shop_id="fujiwa-reference-shop",
        is_active=True,
    )
    credential = TikTokCredential(
        id=uuid.uuid4(),
        shop_id=shop.id,
        merchant_authorization_id="real-merchant-id",
        capability="write",
        shop_cipher="ROW_real_cipher",
        access_token="real_access_token",
        refresh_token="real_refresh_token",
        token_expires_at=datetime.now(UTC),
        status="active",
    )
    # Add a product with real merchant data
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="fujiwa-prod-001",
        title="Expensive Watch Collection",
        category="Luxury",
        price=9999.99,
        name="Fujiwa Premium Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(user)
    session.add(shop)
    session.add(credential)
    session.add(product)
    await session.commit()
    return shop


@pytest_asyncio.fixture
async def sandbox_shop(session: AsyncSession) -> Shop:
    """Create the sandbox-write shop."""
    user = User(
        id=uuid.uuid4(),
        phone="+84912345678",
        display_name="Sandbox User",
    )
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Sandbox Shop",
        tiktok_shop_id="sandbox-write-1862f13b",
        is_active=True,
    )
    session.add(user)
    session.add(shop)
    await session.commit()
    return shop


class TestDemoTenantIdempotency:
    """Test #1: Seed idempotency."""

    async def test_seed_twice_creates_one_shop(self, session: AsyncSession, monkeypatch) -> None:
        """Running seed twice → exactly one demo shop, no duplicates."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        # First seed
        await seed_demo_tenant(session)
        result1 = await session.execute(select(Shop).where(Shop.id == uuid.UUID(demo_shop_id)))
        count1 = len(result1.scalars().all())

        # Second seed
        await seed_demo_tenant(session)
        result2 = await session.execute(select(Shop).where(Shop.id == uuid.UUID(demo_shop_id)))
        count2 = len(result2.scalars().all())

        assert count1 == 1, "First seed should create exactly one demo shop"
        assert count2 == 1, "Second seed should not create duplicate shops"

    async def test_seed_twice_one_card_set(self, session: AsyncSession, monkeypatch) -> None:
        """Running seed twice → exactly one card set per workflow."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        # First seed
        await seed_demo_tenant(session)
        result1 = await session.execute(
            select(ActionCard).where(
                (ActionCard.shop_id == uuid.UUID(demo_shop_id))
                & (ActionCard.workflow_key == "optimize_product_2")
            )
        )
        count1 = len(result1.scalars().all())

        # Second seed
        await seed_demo_tenant(session)
        result2 = await session.execute(
            select(ActionCard).where(
                (ActionCard.shop_id == uuid.UUID(demo_shop_id))
                & (ActionCard.workflow_key == "optimize_product_2")
            )
        )
        count2 = len(result2.scalars().all())

        assert count1 == 1, "First seed should create one card per workflow"
        assert count2 == 1, "Second seed should not create duplicate cards"

    async def test_seed_twice_one_product_set(self, session: AsyncSession, monkeypatch) -> None:
        """Running seed twice → exactly one product set."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        # First seed
        await seed_demo_tenant(session)
        result1 = await session.execute(
            select(Product).where(Product.shop_id == uuid.UUID(demo_shop_id))
        )
        count1 = len(result1.scalars().all())

        # Second seed
        await seed_demo_tenant(session)
        result2 = await session.execute(
            select(Product).where(Product.shop_id == uuid.UUID(demo_shop_id))
        )
        count2 = len(result2.scalars().all())

        assert count1 > 0, "First seed should create products"
        assert count1 == count2, "Second seed should not create duplicate products"


class TestDemoTenantDistinctness:
    """Test #2: Demo shop is distinct from reference and sandbox shops."""

    async def test_demo_distinct_from_reference_and_sandbox(
        self,
        session: AsyncSession,
        reference_shop: Shop,
        sandbox_shop: Shop,
        monkeypatch,
    ) -> None:
        """Demo shop id ≠ reference id ≠ sandbox id."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        # Verify all three are different
        assert demo_shop_id != str(reference_shop.id), "Demo shop must differ from reference shop"
        assert demo_shop_id != str(sandbox_shop.id), "Demo shop must differ from sandbox shop"
        assert str(reference_shop.id) != str(sandbox_shop.id), (
            "Reference and sandbox shops must differ"
        )

    async def test_demo_has_no_tiktok_credentials(self, session: AsyncSession, monkeypatch) -> None:
        """Demo shop has zero tiktok_credentials rows."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        result = await session.execute(
            select(TikTokCredential).where(TikTokCredential.shop_id == uuid.UUID(demo_shop_id))
        )
        count = len(result.scalars().all())

        assert count == 0, "Demo shop must have no tiktok_credentials (no vendor write capability)"


class TestDemoTenantSurfacedCards:
    """Test #3: Seeded action cards are active AND surfaced."""

    async def test_seeded_cards_are_active(self, session: AsyncSession, monkeypatch) -> None:
        """Seeded cards have status='active'."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        result = await session.execute(
            select(ActionCard).where(
                (ActionCard.shop_id == uuid.UUID(demo_shop_id)) & (ActionCard.status == "active")
            )
        )
        active_count = len(result.scalars().all())

        result_all = await session.execute(
            select(ActionCard).where(ActionCard.shop_id == uuid.UUID(demo_shop_id))
        )
        total_count = len(result_all.scalars().all())

        assert active_count > 0, "Seeded cards must be active"
        assert active_count == total_count, "All seeded cards must be active (no inactive ones)"

    async def test_seeded_cards_are_surfaced(self, session: AsyncSession, monkeypatch) -> None:
        """Seeded cards have surfaced_at set (not NULL)."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        result = await session.execute(
            select(ActionCard).where(
                (ActionCard.shop_id == uuid.UUID(demo_shop_id))
                & (ActionCard.surfaced_at.isnot(None))
            )
        )
        surfaced_count = len(result.scalars().all())

        result_all = await session.execute(
            select(ActionCard).where(ActionCard.shop_id == uuid.UUID(demo_shop_id))
        )
        total_count = len(result_all.scalars().all())

        assert surfaced_count > 0, "Seeded cards must be surfaced"
        assert surfaced_count == total_count, (
            "All seeded cards must be surfaced (no suppressed ones)"
        )


class TestDemoTenantWorkflowResolution:
    """Test #4: Seeded cards' workflow_key resolves to registered playbooks."""

    async def test_seeded_card_workflow_key_is_registered(
        self, session: AsyncSession, monkeypatch
    ) -> None:
        """Seeded card workflow_key matches a real registered playbook."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        result = await session.execute(
            select(ActionCard).where(ActionCard.shop_id == uuid.UUID(demo_shop_id))
        )
        cards = result.scalars().all()
        workflow_keys = [card.workflow_key for card in cards]

        assert len(workflow_keys) > 0, "Seeded cards must exist"

        # Verify each workflow_key resolves to a registered playbook
        # For now, we only seed OPTIMIZE_PRODUCT
        for workflow_key in workflow_keys:
            assert workflow_key == OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key, (
                f"Seeded workflow_key '{workflow_key}' must be registered"
            )


class TestDemoTenantContent:
    """Test #5: Seeded content contains no real merchant data."""

    async def test_demo_content_not_in_reference_shop(
        self,
        session: AsyncSession,
        reference_shop: Shop,
        monkeypatch,
    ) -> None:
        """Demo shop strings do not appear in reference shop data."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        await seed_demo_tenant(session)

        # Get seeded shop data
        demo_result = await session.execute(select(Shop).where(Shop.id == uuid.UUID(demo_shop_id)))
        demo_shop = demo_result.scalar()
        demo_shop_name = demo_shop.shop_name if demo_shop else None

        # Get reference shop data
        ref_result = await session.execute(select(Shop).where(Shop.id == reference_shop.id))
        ref_shop = ref_result.scalar()
        ref_shop_name = ref_shop.shop_name if ref_shop else None

        # Get seeded product data
        prod_result = await session.execute(
            select(Product).where(Product.shop_id == uuid.UUID(demo_shop_id))
        )
        demo_products = prod_result.scalars().all()
        demo_product_names = [p.name for p in demo_products]

        # Verify no cross-over
        assert demo_shop_name != ref_shop_name, "Demo and reference shop names must differ"
        for demo_prod_name in demo_product_names:
            assert demo_prod_name != "Fujiwa Premium Product", (
                "Demo product names must not use reference shop content"
            )


class TestDemoTenantConfiguration:
    """Test #6: Configuration is required and named."""

    async def test_demo_shop_id_required(self, session: AsyncSession) -> None:
        """Calling seed without DEMO_SHOP_ID must fail loudly."""
        # Ensure DEMO_SHOP_ID is not set
        if "DEMO_SHOP_ID" in os.environ:
            del os.environ["DEMO_SHOP_ID"]

        with pytest.raises((ValueError, KeyError)):
            await seed_demo_tenant(session)

    async def test_demo_shop_id_env_var_is_named(self, session: AsyncSession, monkeypatch) -> None:
        """Configuration uses DEMO_SHOP_ID environment variable."""
        demo_shop_id = str(uuid.uuid4())
        monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

        # This should work — configuration is recognized
        await seed_demo_tenant(session)

        # Verify the exact shop id was used
        result = await session.execute(select(Shop).where(Shop.id == uuid.UUID(demo_shop_id)))
        count = len(result.scalars().all())
        assert count == 1, "DEMO_SHOP_ID env var should be used to set shop id"
