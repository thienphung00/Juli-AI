"""End-to-end Fujiwa polling sync-state integration tests — Issue #367.

Exercises a full poll cycle through real orchestration, sync workers, and
``TikTokSyncStateRepo`` persistence. Uses deterministic recorded-response replay
from contract-collection samples (always runs in CI). Optional sandbox-backed
live refresh is skipped when Partner Center secrets are absent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.constants import ORDER_SEARCH_PATH
from juli_backend.integrations.tiktok.factories import ProductionReadClientFactory
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import Shop, TikTokSyncState, User
from juli_backend.repositories.repos import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    run_fujiwa_poll_cycle,
)

from tests.integration.tiktok_recorded_replay import load_sample, recorded_tiktok_replay

APP_KEY = "replay_app_key"
APP_SECRET = "replay_app_secret"
SHOP_CIPHER = "ROW_replay_cipher"

ORDERS_FIXTURE = load_sample("orders-search-response.json")
PRODUCTS_FIXTURE = load_sample("products-search-response.json")
RETURNS_FIXTURE = load_sample("returns-search-response.json")

EXPECTED_ORDER_CURSOR = ORDERS_FIXTURE["response"]["data"]["orders"][0]["update_time"]
EXPECTED_PRODUCT_CURSOR = PRODUCTS_FIXTURE["response"]["data"]["products"][0]["update_time"]
EXPECTED_RETURN_CURSOR = RETURNS_FIXTURE["response"]["data"]["return_orders"][0]["update_time"]


@pytest_asyncio.fixture
async def user(session, user_id):
    u = User(id=user_id, phone="+84901234568")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def fujiwa_shop(session, user):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Fujiwa Replay Store",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add(shop)
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def fujiwa_credential(session, fujiwa_shop):
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    return await TikTokCredentialRepo(session).create(
        shop_id=fujiwa_shop.id,
        access_token="replay_access",
        refresh_token="replay_refresh",
        token_expires_at=expires_at,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher=SHOP_CIPHER,
    )


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        base_url="https://open-api.tiktokglobalshop.com",
    )


@pytest.fixture
def oauth_service(tiktok_auth, session):
    return TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri="https://example.com/callback",
        app_secret=APP_SECRET,
    )


@pytest.fixture
def mock_rate_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    limiter.is_exhausted.return_value = False
    limiter.time_until_reset.return_value = 0
    return limiter


@pytest.fixture
def handoff_calls():
    return []


@pytest.fixture
def handoff_fn(handoff_calls):
    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append({"channel": channel, "shop_key": shop_key})

    return _handoff


@pytest.fixture
def poll_config():
    return FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET)


@pytest.fixture
def run_replay_poll(session, oauth_service, mock_rate_limiter, handoff_fn, poll_config):
    async def _run(*, fujiwa_credential, fail_paths=None):
        with recorded_tiktok_replay(fail_paths=fail_paths):
            await run_fujiwa_poll_cycle(
                session=session,
                config=poll_config,
                oauth_service=oauth_service,
                rate_limiter=mock_rate_limiter,
                handoff_fn=handoff_fn,
                resolve_credential=AsyncMock(return_value=fujiwa_credential),
                factory=ProductionReadClientFactory(),
            )

    return _run


async def _count_sync_state_rows(session, shop_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(TikTokSyncState)
            .where(TikTokSyncState.shop_id == shop_id)
        )
    ).scalar_one()


class TestFujiwaPollingSyncStateE2E:
    @pytest.mark.asyncio
    async def test_initial_poll_persists_sync_state_from_recorded_responses(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """Full poll cycle writes per-endpoint cursors readable after completion."""
        repo = TikTokSyncStateRepo(session)
        assert await repo.load(fujiwa_shop.id) == {}

        await run_replay_poll(fujiwa_credential=fujiwa_credential)

        loaded = await repo.load(fujiwa_shop.id)
        assert loaded["orders_last_update_time"] == EXPECTED_ORDER_CURSOR
        assert loaded["products_last_update_time"] == EXPECTED_PRODUCT_CURSOR
        assert loaded["returns_last_update_time"] == EXPECTED_RETURN_CURSOR
        assert "inventory_last_sync_at" in loaded

    @pytest.mark.asyncio
    async def test_repoll_is_idempotent_and_does_not_corrupt_sync_state(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """Second poll with the same replay fixtures keeps stable checkpoint values."""
        repo = TikTokSyncStateRepo(session)

        await run_replay_poll(fujiwa_credential=fujiwa_credential)
        after_first = await repo.load(fujiwa_shop.id)
        row_count_after_first = await _count_sync_state_rows(session, fujiwa_shop.id)

        await run_replay_poll(fujiwa_credential=fujiwa_credential)
        after_second = await repo.load(fujiwa_shop.id)
        row_count_after_second = await _count_sync_state_rows(session, fujiwa_shop.id)

        # Cursor endpoints stay stable on identical replay fixtures. Inventory uses a
        # wall-clock watermark (int(time.time())), so it may advance by ≤1s between polls.
        for key in (
            "orders_last_update_time",
            "products_last_update_time",
            "returns_last_update_time",
        ):
            assert after_second[key] == after_first[key]
        assert "inventory_last_sync_at" in after_second
        assert after_second["inventory_last_sync_at"] >= after_first["inventory_last_sync_at"]
        # orders + products + returns + inventory + 6 analytics watermarks (#424)
        assert row_count_after_second == row_count_after_first == 10
        assert "shop_sku_performance_last_sync_at" in after_second
        assert "bestselling_videos_last_sync_at" in after_second

    @pytest.mark.asyncio
    async def test_partial_endpoint_failure_preserves_existing_sync_state(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """When one endpoint fails, previously persisted cursors for others remain intact."""
        repo = TikTokSyncStateRepo(session)
        seeded_orders_cursor = EXPECTED_ORDER_CURSOR - 1
        await repo.save(
            fujiwa_shop.id,
            {"orders_last_update_time": seeded_orders_cursor},
        )

        await run_replay_poll(
            fujiwa_credential=fujiwa_credential,
            fail_paths=frozenset({ORDER_SEARCH_PATH}),
        )

        loaded = await repo.load(fujiwa_shop.id)
        assert loaded["orders_last_update_time"] == seeded_orders_cursor
        assert loaded["products_last_update_time"] == EXPECTED_PRODUCT_CURSOR
        assert loaded["returns_last_update_time"] == EXPECTED_RETURN_CURSOR
