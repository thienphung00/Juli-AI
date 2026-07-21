"""TDD: Fujiwa poll cycle analytics steps + sync_state (#424)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    TikTokCapability,
)
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    run_fujiwa_poll_cycle,
)
from juli_backend.workers.services.polling.sync import sync_analytics

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
SHOP_CIPHER = "ROW_test_cipher"


@pytest_asyncio.fixture
async def user(session, user_id):
    u = User(id=user_id, phone="+84901234567")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def fujiwa_shop(session, user):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Fujiwa Vietnam Store",
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
        access_token="fujiwa_access",
        refresh_token="fujiwa_refresh",
        token_expires_at=expires_at,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher=SHOP_CIPHER,
    )


@pytest.fixture
def oauth_service(session):
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            base_url="https://open-api.tiktokglobalshop.com",
        ),
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
def handoff_fn():
    async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
        return None

    return _handoff


@pytest.fixture
def mock_resources():
    resources = MagicMock()
    resources.orders.search_all.return_value = []
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"code": 0, "data": {"inventory": []}}

    analytics = MagicMock()
    analytics.list_sku_performance_all.return_value = [
        {"id": "sku-1", "product_id": "prod-1"},
    ]
    analytics.get_sku_performance.return_value = {
        "performance": {"sku_id": "sku-1", "product_id": "prod-1"}
    }
    analytics.list_product_performance_all.return_value = [{"id": "prod-1"}]
    analytics.get_product_performance.return_value = {"performance": {"intervals": []}}
    analytics.get_shop_performance.return_value = {"performance": {"intervals": []}}
    analytics.get_shop_performance_per_hour.return_value = {
        "performance": {"overall": {}}
    }
    analytics.get_bestselling_products.return_value = {"products": []}
    analytics.get_bestselling_videos.return_value = {"videos": []}
    resources.analytics = analytics

    promotion = MagicMock()
    promotion.get_activity.return_value = {"activity_id": "act-1"}
    resources.promotion = promotion
    return resources


class TestSyncAnalytics:
    @pytest.mark.asyncio
    async def test_invokes_date_window_list_and_detail_endpoints(
        self, mock_rate_limiter, handoff_fn
    ):
        resource = MagicMock()
        resource.list_sku_performance_all.return_value = [
            {"id": "sku-1", "product_id": "prod-1"},
        ]
        resource.get_sku_performance.return_value = {"performance": {}}
        resource.list_product_performance_all.return_value = [{"id": "prod-1"}]
        resource.get_product_performance.return_value = {"performance": {}}
        resource.get_shop_performance.return_value = {"performance": {}}
        resource.get_shop_performance_per_hour.return_value = {"performance": {}}
        resource.get_bestselling_products.return_value = {"products": []}
        resource.get_bestselling_videos.return_value = {"videos": []}
        promotion = MagicMock()
        promotion.get_activity.return_value = {"activity_id": "act-1"}
        sync_state: dict = {"promotion_activity_ids": ["act-1"]}

        await sync_analytics(
            resource=resource,
            promotion_resource=promotion,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id=APP_KEY,
            shop_id=PRODUCTION_AUTH_ID,
            sync_state=sync_state,
            now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )

        resource.list_sku_performance_all.assert_called_once_with(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.get_sku_performance.assert_called_once_with(
            sku_id="sku-1",
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.list_product_performance_all.assert_called_once_with(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.get_product_performance.assert_called_once_with(
            product_id="prod-1",
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.get_shop_performance.assert_called_once_with(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.get_shop_performance_per_hour.assert_called_once_with(date="2026-07-13")
        resource.get_bestselling_products.assert_called_once_with(
            date="2026-07-13",
            time_slot="1D",
        )
        resource.get_bestselling_videos.assert_called_once_with(
            date="2026-07-13",
            time_slot="1D",
        )
        promotion.get_activity.assert_called_once_with("act-1")

        assert "shop_sku_performance_last_sync_at" in sync_state
        assert "shop_product_performance_last_sync_at" in sync_state
        assert "shop_performance_last_sync_at" in sync_state
        assert "shop_performance_per_hour_last_sync_at" in sync_state
        assert "bestselling_products_last_sync_at" in sync_state
        assert "bestselling_videos_last_sync_at" in sync_state
        assert "promotion_activity_last_sync_at" in sync_state

        acquired_endpoints = {
            call.args[2] for call in mock_rate_limiter.acquire.call_args_list
        }
        assert ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH in acquired_endpoints
        assert analytics_shop_sku_performance_path("sku-1") in acquired_endpoints
        assert ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH in acquired_endpoints
        assert analytics_shop_product_performance_path("prod-1") in acquired_endpoints
        assert ANALYTICS_SHOP_PERFORMANCE_PATH in acquired_endpoints
        assert analytics_shop_performance_per_hour_path("2026-07-13") in acquired_endpoints
        assert ANALYTICS_BESTSELLING_PRODUCTS_PATH in acquired_endpoints
        assert ANALYTICS_BESTSELLING_VIDEOS_PATH in acquired_endpoints
        assert promotion_activity_path("act-1") in acquired_endpoints

    @pytest.mark.asyncio
    async def test_skips_when_rate_limited(self, mock_rate_limiter, handoff_fn):
        resource = MagicMock()
        mock_rate_limiter.acquire.return_value = False
        sync_state: dict = {}

        await sync_analytics(
            resource=resource,
            promotion_resource=MagicMock(),
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id=APP_KEY,
            shop_id=PRODUCTION_AUTH_ID,
            sync_state=sync_state,
            now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )

        resource.list_sku_performance_all.assert_not_called()
        resource.get_shop_performance.assert_not_called()
        assert sync_state == {}

    @pytest.mark.asyncio
    async def test_does_not_wire_live_analytics_endpoints(
        self, mock_rate_limiter, handoff_fn
    ):
        from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
        from juli_backend.workers.services.polling import sync as sync_mod

        resource = MagicMock()
        resource.list_sku_performance_all.return_value = []
        resource.list_product_performance_all.return_value = []
        resource.get_shop_performance.return_value = {}
        resource.get_shop_performance_per_hour.return_value = {}
        resource.get_bestselling_products.return_value = {}
        resource.get_bestselling_videos.return_value = {}

        await sync_analytics(
            resource=resource,
            promotion_resource=MagicMock(),
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            app_id=APP_KEY,
            shop_id=PRODUCTION_AUTH_ID,
            sync_state={},
            now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )

        live_methods = [name for name in dir(AnalyticsResource) if "live" in name.lower()]
        assert live_methods == []
        sync_source = Path(sync_mod.__file__).read_text(encoding="utf-8")
        assert "shop_lives" not in sync_source
        assert "live_rooms" not in sync_source


class TestRunFujiwaPollCycleAnalytics:
    @pytest.mark.asyncio
    async def test_poll_cycle_invokes_analytics_and_persists_sync_state(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        oauth_service,
        mock_rate_limiter,
        handoff_fn,
        mock_resources,
    ):
        oauth_service.refresh_merchant_tokens = AsyncMock(return_value=fujiwa_credential)

        await run_fujiwa_poll_cycle(
            session=session,
            config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            oauth_service=oauth_service,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            resolve_credential=AsyncMock(return_value=fujiwa_credential),
            create_resources=lambda _cfg: mock_resources,
        )

        mock_resources.analytics.list_sku_performance_all.assert_called()
        mock_resources.analytics.get_shop_performance.assert_called()
        mock_resources.analytics.get_bestselling_products.assert_called()
        mock_resources.analytics.get_bestselling_videos.assert_called()

        # Rate limiter consulted for analytics endpoints (backoff + acquire).
        assert mock_rate_limiter.is_exhausted.called
        assert mock_rate_limiter.acquire.called
        acquired = {call.args[2] for call in mock_rate_limiter.acquire.call_args_list}
        assert ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH in acquired
        assert ANALYTICS_SHOP_PERFORMANCE_PATH in acquired

        loaded = await TikTokSyncStateRepo(session).load(fujiwa_shop.id)
        assert "shop_sku_performance_last_sync_at" in loaded
        assert "shop_performance_last_sync_at" in loaded
        assert "bestselling_products_last_sync_at" in loaded
        assert "bestselling_videos_last_sync_at" in loaded
