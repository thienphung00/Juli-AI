"""P61-A (D71.1): an agent read is built from the run's shop's OWN credential.

Before P61-A, `composition.build_read_resources` resolved the singleton
configured production merchant for every non-sandbox shop and signed with
`PRODUCTION_AUTH_ID`, so an agent run for shop B read the reference shop's
catalogue. These tests pin the resolver choice per shop on the in-memory
database, capturing the `ClientFactoryConfig` handed to the read factory:

- sandbox shop -> sandbox-write resources (unchanged, #1302);
- shop A / shop B -> each its own token, cipher and merchant id;
- shop without a read credential -> `NoReadCredentialForShop`;
- `shop_id=None` -> `AgentReadShopRequired`;
- a resolved credential owned by another shop -> `AgentReadCredentialMismatch`,
  before any client is built.

Also covers the analytics backfill auto top-up, which had the same bug shape
(the shop's credential, signed with the configured merchant id).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import NoReadCredentialForShop
from juli_backend.integrations.tiktok import (
    SANDBOX_AUTH_ID,
    ClientFactoryConfig,
    SandboxWriteResources,
    TikTokCapability,
)
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.services.agent import composition
from juli_backend.services.agent.composition import (
    AgentReadCredentialMismatch,
    AgentReadShopRequired,
    build_read_resources,
)

MERCHANT_A = "merchant-a-test"
MERCHANT_B = "merchant-b-test"


class _CapturingFactory:
    """Stands in for `ProductionReadClientFactory`; records every config."""

    configs: list[ClientFactoryConfig] = []

    def create_resources(self, config: ClientFactoryConfig) -> dict[str, Any]:
        type(self).configs.append(config)
        return {"merchant": config.merchant_auth_id}


@pytest.fixture
def captured(monkeypatch) -> list[ClientFactoryConfig]:
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
    _CapturingFactory.configs = []
    monkeypatch.setattr(composition, "ProductionReadClientFactory", _CapturingFactory)
    return _CapturingFactory.configs


async def _shop(session: AsyncSession) -> uuid.UUID:
    shop_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
    session.add_all([user, Shop(id=shop_id, user_id=user.id, shop_name=f"Shop {shop_id}")])
    await session.flush()
    return shop_id


async def _credential(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    merchant: str,
    capability: TikTokCapability,
    token: str,
    cipher: str,
) -> None:
    await TikTokCredentialRepo(session).create(
        shop_id=shop_id,
        access_token=token,
        refresh_token=f"{token}-refresh",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=merchant,
        capability=capability.value,
        shop_cipher=cipher,
    )


async def _two_shops(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    shop_a = await _shop(session)
    shop_b = await _shop(session)
    await _credential(
        session,
        shop_a,
        merchant=MERCHANT_A,
        capability=TikTokCapability.PRODUCTION_READ,
        token="token-a",
        cipher="CIPHER_A",
    )
    await _credential(
        session,
        shop_b,
        merchant=MERCHANT_B,
        capability=TikTokCapability.SELLER_CONNECT,
        token="token-b",
        cipher="CIPHER_B",
    )
    return shop_a, shop_b


class TestAgentReadResourcesPerShop:
    async def test_shop_a_reads_with_its_own_credential(self, session, captured) -> None:
        shop_a, _ = await _two_shops(session)

        await build_read_resources(session, shop_a)

        assert [(c.access_token, c.shop_cipher, c.merchant_auth_id) for c in captured] == [
            ("token-a", "CIPHER_A", MERCHANT_A)
        ]

    async def test_shop_b_reads_with_its_own_credential_never_a(self, session, captured) -> None:
        _, shop_b = await _two_shops(session)

        resources = await build_read_resources(session, shop_b)

        assert resources == {"merchant": MERCHANT_B}
        assert [(c.access_token, c.shop_cipher, c.merchant_auth_id) for c in captured] == [
            ("token-b", "CIPHER_B", MERCHANT_B)
        ]
        assert all("token-a" != c.access_token for c in captured)

    async def test_sandbox_shop_keeps_sandbox_resources(self, session, captured) -> None:
        await _two_shops(session)
        sandbox_shop = await _shop(session)
        await _credential(
            session,
            sandbox_shop,
            merchant=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            token="token-sandbox",
            cipher="CIPHER_SANDBOX",
        )

        resources = await build_read_resources(session, sandbox_shop)

        assert isinstance(resources, SandboxWriteResources)
        assert captured == []

    async def test_shop_without_read_credential_fails_closed(self, session, captured) -> None:
        await _two_shops(session)
        bare_shop = await _shop(session)

        with pytest.raises(NoReadCredentialForShop) as excinfo:
            await build_read_resources(session, bare_shop)

        assert str(bare_shop) in str(excinfo.value)
        assert captured == []

    async def test_shop_id_none_is_refused(self, session, captured) -> None:
        await _two_shops(session)
        no_shop: Any = None

        with pytest.raises(AgentReadShopRequired):
            await build_read_resources(session, no_shop)

        assert captured == []

    async def test_credential_owned_by_another_shop_is_refused(
        self, session, captured, monkeypatch
    ) -> None:
        shop_a, shop_b = await _two_shops(session)
        a_credential = await TikTokCredentialRepo(session).get_by_shop_and_capability(
            shop_a, TikTokCapability.PRODUCTION_READ
        )

        async def _wrong_owner(_session, _shop_id):
            return a_credential

        monkeypatch.setattr(composition, "resolve_read_credential_for_shop", _wrong_owner)

        with pytest.raises(AgentReadCredentialMismatch) as excinfo:
            await build_read_resources(session, shop_b)

        assert str(shop_b) in str(excinfo.value)
        assert captured == []


class TestAnalyticsBackfillTopupPerShop:
    async def test_topup_signs_with_the_shops_own_merchant_id(
        self, session: AsyncSession, monkeypatch
    ) -> None:
        from juli_backend.services.analytics_backfill import orchestrator

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
        _, shop_b = await _two_shops(session)

        configs: list[ClientFactoryConfig] = []

        class _Stop(Exception):
            pass

        class _Factory:
            def create_resources(self, config: ClientFactoryConfig) -> Any:
                configs.append(config)
                raise _Stop

        monkeypatch.setattr(orchestrator, "ProductionReadClientFactory", _Factory)

        with pytest.raises(_Stop):
            await orchestrator.backfill_analytics_history_auto_topup(
                session, shop_id=shop_b, start_date=date(2026, 3, 16), end_date=date(2026, 3, 16)
            )

        assert [(c.access_token, c.shop_cipher, c.merchant_auth_id) for c in configs] == [
            ("token-b", "CIPHER_B", MERCHANT_B)
        ]

    async def test_topup_skips_a_shop_without_read_credential(
        self, session: AsyncSession, monkeypatch
    ) -> None:
        from juli_backend.services.analytics_backfill import orchestrator

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
        await _two_shops(session)
        bare_shop = await _shop(session)

        result = await orchestrator.backfill_analytics_history_auto_topup(
            session, shop_id=bare_shop, start_date=date(2026, 3, 16), end_date=date(2026, 3, 16)
        )

        assert result.completed_partitions == 0
        assert result.shop_id == bare_shop
