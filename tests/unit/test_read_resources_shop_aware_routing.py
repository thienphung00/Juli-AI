"""Tests for shop-aware read routing in composition.build_read_resources
(issue #1302).

**Shop-aware routing logic:**
- When shop_id is provided and matches the sandbox-write credential's shop,
  build_read_resources returns SandboxWriteResources.
- For any other shop or when shop_id is None, it returns ProductionReadResources.
- When sandbox-write credential resolution fails (e.g., NotFound), a named
  warning is logged before falling back to production-read. Shop mismatch is
  NOT a fallback-worthy case -- only actual resolution failure should warn.
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
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.services.agent.composition import build_read_resources


def _shop_rows(shop_id: uuid.UUID) -> tuple[User, Shop]:
    """Helper to create User and Shop rows for testing."""
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=shop_id, user_id=user.id, shop_name="Test Shop")
    return user, shop


class TestShopAwareReadRouting:
    """Test shop-aware routing: sandbox vs. production credential selection."""

    async def test_production_read_when_shop_id_is_none(self, session: AsyncSession, monkeypatch):
        """When shop_id is None, always return ProductionReadResources."""
        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        shop_id = uuid.uuid4()
        session.add_all(_shop_rows(shop_id))
        await session.flush()
        await TikTokCredentialRepo(session).create(
            shop_id=shop_id,
            access_token="fujiwa-access",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_test_cipher",
        )

        # shop_id is None -- should use production-read regardless of what
        # sandbox credential exists
        resources = await build_read_resources(session, shop_id=None)

        assert isinstance(resources, ProductionReadResources)

    async def test_sandbox_resources_when_shop_matches_sandbox_credential(
        self, session: AsyncSession, monkeypatch
    ):
        """When shop_id matches the sandbox-write credential's shop, return
        SandboxWriteResources."""
        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        session.add_all(_shop_rows(sandbox_shop_id))
        await session.flush()
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # shop_id matches sandbox credential -- should use sandbox-write resources
        resources = await build_read_resources(session, shop_id=sandbox_shop_id)

        assert isinstance(resources, SandboxWriteResources)

    async def test_production_read_when_shop_does_not_match_sandbox_credential(
        self, session: AsyncSession, monkeypatch
    ):
        """When shop_id does NOT match the sandbox-write credential's shop,
        return ProductionReadResources (no warning for normal shop mismatch)."""
        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        sandbox_shop_id = uuid.uuid4()
        other_shop_id = uuid.uuid4()

        session.add_all(_shop_rows(sandbox_shop_id))
        session.add_all(_shop_rows(other_shop_id))
        await session.flush()

        # Create sandbox credential for one shop
        await TikTokCredentialRepo(session).create(
            shop_id=sandbox_shop_id,
            access_token="sandbox-access",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        # Create production credential for other shop
        await TikTokCredentialRepo(session).create(
            shop_id=other_shop_id,
            access_token="fujiwa-access",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_test_cipher",
        )

        # shop_id doesn't match sandbox credential -- should use production-read
        resources = await build_read_resources(session, shop_id=other_shop_id)

        assert isinstance(resources, ProductionReadResources)

    async def test_fallback_logs_warning_when_sandbox_resolution_fails(
        self, session: AsyncSession, monkeypatch, caplog
    ):
        """When sandbox-write credential resolution fails (raises an exception),
        a named warning log must be emitted before falling back to
        production-read. Shop mismatch is NOT a fallback-worthy case -- only
        actual resolution failure should warn."""
        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        shop_id = uuid.uuid4()
        session.add_all(_shop_rows(shop_id))
        await session.flush()

        # Create only production credential (no sandbox credential to resolve)
        await TikTokCredentialRepo(session).create(
            shop_id=shop_id,
            access_token="fujiwa-access",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_test_cipher",
        )

        # Attempt to get read resources with a shop_id. No sandbox credential
        # exists, so resolve_sandbox_write_credential will raise NotFound.
        with caplog.at_level("WARNING"):
            resources = await build_read_resources(session, shop_id=shop_id)

        # Should fall back to production-read
        assert isinstance(resources, ProductionReadResources)

        # Should emit a named warning log with the fallback reason
        record_details = [
            (r.name, r.getMessage(), getattr(r, "reason", None), getattr(r, "shop_id", None))
            for r in caplog.records
        ]
        assert any(
            record.name == "juli_backend.services.agent.composition"
            and record.levelname == "WARNING"
            and record.getMessage() == "agent_read_resources_sandbox_fallback"
            and getattr(record, "reason", None) == "sandbox_resolution_failed"
            and getattr(record, "shop_id", None) == str(shop_id)
            for record in caplog.records
        ), (
            f"Expected warning log with name 'agent_read_resources_sandbox_fallback' "
            f"not found. Records: {record_details}"
        )
