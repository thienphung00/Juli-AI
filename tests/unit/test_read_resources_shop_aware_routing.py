"""Shop-aware read routing for agent workflows (issue #1302).

When an agent run is on the sandbox shop, its read resources are built from
the sandbox-write credential (which can read its own products). Runs on other
shops use the Fujiwa production-read credential.

This decouples the read credential decision from hardcoded shop IDs, instead
routing based on capability-derived comparison: if the sandbox-write
credential's shop matches the run's shop, use it for reads; otherwise,
fall back to production-read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    ProductionReadResources,
    SandboxWriteResources,
    TikTokCapability,
)
from juli_backend.repositories.repos import TikTokCredentialRepo


def _shop_rows(shop_id: uuid.UUID):
    """Helper to create shop rows for testing."""
    from juli_backend.models.models import Shop, User

    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=shop_id, user_id=user.id, shop_name="Test Shop")
    return [user, shop]


class TestBuildReadResourcesShopAware:
    """Unit tests for shop-aware read routing in `build_read_resources`."""

    async def test_sandbox_shop_run_uses_sandbox_write_credential_for_reads(
        self, session: AsyncSession, monkeypatch
    ):
        """When a run's shop matches the sandbox-write credential's shop,
        read resources are built from the sandbox-write credential, not Fujiwa."""
        from juli_backend.services.agent import composition as composition_module

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        production_shop_id = uuid.uuid4()

        # Seed both shops
        session.add_all(_shop_rows(sandbox_shop_id))
        session.add_all(_shop_rows(production_shop_id))
        await session.flush()

        # Seed sandbox-write credential for sandbox_shop_id
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access-token",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # Seed Fujiwa production-read credential (for a different shop)
        await TikTokCredentialRepo(session).create(
            shop_id=production_shop_id,
            access_token="fujiwa-access-token",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_fujiwa_cipher",
        )

        # Build read resources for sandbox_shop_id
        resources = await composition_module.build_read_resources(session, shop_id=sandbox_shop_id)

        # Verify it's SandboxWriteResources (built from sandbox credential)
        assert isinstance(resources, SandboxWriteResources)

    async def test_production_shop_run_uses_fujiwa_production_read_credential(
        self, session: AsyncSession, monkeypatch
    ):
        """When a run's shop does not match the sandbox-write credential's shop,
        read resources are built from the Fujiwa production-read credential."""
        from juli_backend.services.agent import composition as composition_module

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        production_shop_id = uuid.uuid4()

        # Seed both shops
        session.add_all(_shop_rows(sandbox_shop_id))
        session.add_all(_shop_rows(production_shop_id))
        await session.flush()

        # Seed sandbox-write credential for sandbox_shop_id
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access-token",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # Seed Fujiwa production-read credential
        await TikTokCredentialRepo(session).create(
            shop_id=production_shop_id,
            access_token="fujiwa-access-token",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_fujiwa_cipher",
        )

        # Build read resources for production_shop_id (not the sandbox shop)
        resources = await composition_module.build_read_resources(
            session, shop_id=production_shop_id
        )

        # Verify it's ProductionReadResources (built from Fujiwa credential)
        assert isinstance(resources, ProductionReadResources)

    async def test_no_sandbox_write_credential_falls_back_to_production_read(
        self, session: AsyncSession, monkeypatch
    ):
        """When no sandbox-write credential is provisioned, the routing
        falls back to the existing production-read path."""
        from juli_backend.services.agent import composition as composition_module

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        some_shop_id = uuid.uuid4()
        production_shop_id = uuid.uuid4()

        # Seed both shops
        session.add_all(_shop_rows(some_shop_id))
        session.add_all(_shop_rows(production_shop_id))
        await session.flush()

        # NO sandbox-write credential seeded

        # Seed only Fujiwa production-read credential
        await TikTokCredentialRepo(session).create(
            shop_id=production_shop_id,
            access_token="fujiwa-access-token",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_fujiwa_cipher",
        )

        # Build read resources for some_shop_id (not Fujiwa)
        resources = await composition_module.build_read_resources(session, shop_id=some_shop_id)

        # Verify it's ProductionReadResources (built from Fujiwa, not sandbox)
        assert isinstance(resources, ProductionReadResources)

    async def test_shop_aware_routing_uses_real_credential_resolvers(
        self, session: AsyncSession, monkeypatch
    ):
        """The routing decision must use the existing credential resolvers
        from core.security, not hardcoded shop ids (ADR-068 amendment
        requirement 3: capability-derived routing)."""
        from juli_backend.core.security import resolve_sandbox_write_credential
        from juli_backend.services.agent import composition as composition_module

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        session.add_all(_shop_rows(sandbox_shop_id))
        await session.flush()

        # Seed sandbox-write credential
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access-token",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # Verify sandbox write credential resolver finds the credential for sandbox_shop_id
        sandbox_cred = await resolve_sandbox_write_credential(session)
        assert sandbox_cred.shop_id == sandbox_shop_id

        # When we build read resources for this shop, it should use the
        # sandbox-write credential (via the resolver, not a hardcoded id)
        resources = await composition_module.build_read_resources(session, shop_id=sandbox_shop_id)

        # Since the shop matches, we get SandboxWriteResources
        assert isinstance(resources, SandboxWriteResources)

    async def test_mismatched_shop_never_uses_sandbox_write_credential(
        self, session: AsyncSession, monkeypatch
    ):
        """A run on a different shop should never use the sandbox-write
        credential, even if provisioned, proving the routing is truly
        shop-aware, not just "always prefer sandbox if it exists"."""
        from juli_backend.services.agent import composition as composition_module

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        different_shop_id = uuid.uuid4()

        session.add_all(_shop_rows(sandbox_shop_id))
        session.add_all(_shop_rows(different_shop_id))
        await session.flush()

        # Seed sandbox-write credential for sandbox_shop_id
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access-token",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # Seed Fujiwa for different_shop_id
        await TikTokCredentialRepo(session).create(
            shop_id=different_shop_id,
            access_token="fujiwa-access-token",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_fujiwa_cipher",
        )

        # Build read resources for different_shop_id (not the sandbox shop)
        resources = await composition_module.build_read_resources(
            session, shop_id=different_shop_id
        )

        # Must be ProductionReadResources, not SandboxWriteResources
        assert isinstance(resources, ProductionReadResources)
        assert not isinstance(resources, SandboxWriteResources)
