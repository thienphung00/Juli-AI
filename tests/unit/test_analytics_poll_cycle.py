"""The Fujiwa poll cycle's analytics leg and its sync-state cursors (#424).

``sync_analytics`` asks the vendor for yesterday's window on every analytics
endpoint, gated per endpoint by the rate limiter, and stamps a
``*_last_sync_at`` cursor for each leg it completed. The poll cycle persists
those cursors through ``TikTokSyncStateRepo``. The collaborators are the
contract-shaped fakes in ``tests/support/tiktok_fakes.py``: a call with the
wrong keyword fails here the way it would against the real resource.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)
from juli_backend.repositories import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    run_fujiwa_poll_cycle,
)
from juli_backend.workers.services.polling.sync import sync_analytics
from tests.support.builders import make_shop, make_user, utc_now_naive
from tests.support.tiktok_fakes import (
    FakeAnalyticsResource,
    FakeProductionReadResources,
    FakePromotionResource,
    RecordingRateLimiter,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
WINDOW = {"start_date_ge": "2026-07-13", "end_date_lt": "2026-07-14"}

CURSOR_KEYS = {
    "shop_sku_performance_last_sync_at",
    "shop_product_performance_last_sync_at",
    "shop_performance_last_sync_at",
    "shop_performance_per_hour_last_sync_at",
    "bestselling_products_last_sync_at",
    "bestselling_videos_last_sync_at",
    "promotion_activity_last_sync_at",
}


async def no_handoff(channel: str, shop_key: str, value: bytes) -> None:
    return None


async def run_sync(analytics, *, rate_limiter=None, promotion=None, handoff=no_handoff, state=None):
    sync_state = {} if state is None else state
    await sync_analytics(
        resource=analytics,
        promotion_resource=promotion,
        rate_limiter=rate_limiter or RecordingRateLimiter(),
        handoff_fn=handoff,
        app_id=APP_KEY,
        shop_id=PRODUCTION_AUTH_ID,
        sync_state=sync_state,
        now=NOW,
    )
    return sync_state


class TestSyncAnalytics:
    async def test_asks_every_endpoint_for_yesterdays_window(self):
        analytics = FakeAnalyticsResource(
            {
                "list_sku_performance_all": [{"id": "sku-1", "product_id": "prod-1"}],
                "list_product_performance_all": [{"id": "prod-1"}],
            }
        )
        promotion = FakePromotionResource()

        await run_sync(analytics, promotion=promotion, state={"promotion_activity_ids": ["act-1"]})

        assert analytics.calls_to("list_sku_performance_all") == [WINDOW]
        assert analytics.calls_to("get_sku_performance") == [{"sku_id": "sku-1", **WINDOW}]
        assert analytics.calls_to("list_product_performance_all") == [WINDOW]
        assert analytics.calls_to("get_product_performance") == [{"product_id": "prod-1", **WINDOW}]
        assert analytics.calls_to("get_shop_performance") == [WINDOW]
        assert analytics.calls_to("get_shop_performance_per_hour") == [{"date": "2026-07-13"}]
        assert analytics.calls_to("get_bestselling_products") == [
            {"date": "2026-07-13", "time_slot": "1D"}
        ]
        assert analytics.calls_to("get_bestselling_videos") == [
            {"date": "2026-07-13", "time_slot": "1D"}
        ]
        assert analytics.calls_to("list_live_performance_all") == [WINDOW]
        assert promotion.calls_to("get_activity") == [{"activity_id": "act-1"}]

    async def test_stamps_a_cursor_for_every_completed_leg(self):
        state = await run_sync(
            FakeAnalyticsResource(),
            promotion=FakePromotionResource(),
            state={"promotion_activity_ids": ["act-1"]},
        )

        assert CURSOR_KEYS <= set(state)

    async def test_acquires_the_rate_limiter_per_endpoint_including_detail_paths(self):
        limiter = RecordingRateLimiter()
        analytics = FakeAnalyticsResource(
            {
                "list_sku_performance_all": [{"id": "sku-1", "product_id": "prod-1"}],
                "list_product_performance_all": [{"id": "prod-1"}],
            }
        )

        await run_sync(
            analytics,
            rate_limiter=limiter,
            promotion=FakePromotionResource(),
            state={"promotion_activity_ids": ["act-1"]},
        )

        assert {
            ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
            analytics_shop_sku_performance_path("sku-1"),
            ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
            analytics_shop_product_performance_path("prod-1"),
            ANALYTICS_SHOP_PERFORMANCE_PATH,
            analytics_shop_performance_per_hour_path("2026-07-13"),
            ANALYTICS_BESTSELLING_PRODUCTS_PATH,
            ANALYTICS_BESTSELLING_VIDEOS_PATH,
            ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
            promotion_activity_path("act-1"),
        } <= set(limiter.acquired)

    async def test_rate_limited_leg_is_skipped_and_leaves_no_cursor(self):
        analytics = FakeAnalyticsResource()

        state = await run_sync(analytics, rate_limiter=RecordingRateLimiter(allow=False))

        assert analytics.calls == []
        assert state == {}

    async def test_live_performance_rows_are_handed_off_raw(self):
        handoffs: list[tuple[str, str, bytes]] = []

        async def capture(channel: str, shop_key: str, value: bytes) -> None:
            handoffs.append((channel, shop_key, value))

        analytics = FakeAnalyticsResource(
            {
                "list_live_performance_all": [
                    {
                        "id": "live-99",
                        "sales_performance": {
                            "gmv": {"amount": "10.00", "currency": "VND"},
                            "sku_orders": 1,
                        },
                        "interaction_performance": {"click_through_rate": "1.00%"},
                    }
                ]
            }
        )

        state = await run_sync(analytics, handoff=capture)

        live = [h for h in handoffs if h[0] == "tiktok.analytics.live.raw"]
        assert len(live) == 1
        assert state.get("shop_live_performance_last_sync_at") is not None


class TestPollCyclePersistsAnalyticsCursors:
    """The full cycle runs the analytics leg and writes its cursors through the repo."""

    @pytest.fixture
    async def fujiwa(self, session):
        user = await make_user(session)
        shop = await make_shop(session, user, tiktok_shop_id=PRODUCTION_AUTH_ID)
        credential = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="fujiwa_access",
            refresh_token="fujiwa_refresh",
            token_expires_at=utc_now_naive() + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_test_cipher",
        )
        return shop, credential

    @pytest.fixture
    def oauth_service(self, session):
        async def stub_binding_verifier(session, *, capability, access_token) -> str:
            return "ROW_stub_cipher"  # polling, not credential binding, is under test (#1200)

        return TikTokOAuthService(
            tiktok_auth=TikTokAuth(
                app_key=APP_KEY,
                app_secret=APP_SECRET,
                base_url="https://open-api.tiktokglobalshop.com",
            ),
            session=session,
            redirect_uri="https://example.com/callback",
            app_secret=APP_SECRET,
            binding_verifier=stub_binding_verifier,
        )

    async def test_runs_the_analytics_leg_and_persists_cursors(
        self, session, fujiwa, oauth_service
    ):
        shop, credential = fujiwa
        limiter = RecordingRateLimiter()
        resources = FakeProductionReadResources(
            analytics=FakeAnalyticsResource(
                {"list_sku_performance_all": [{"id": "sku-1", "product_id": "prod-1"}]}
            )
        )

        async def resolve_credential(_session):
            return credential

        await run_fujiwa_poll_cycle(
            session=session,
            config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            oauth_service=oauth_service,
            rate_limiter=limiter,
            handoff_fn=no_handoff,
            resolve_credential=resolve_credential,
            create_resources=lambda _cfg: resources,
        )

        asked = {name for name, _ in resources.analytics.calls}
        assert {
            "list_sku_performance_all",
            "get_shop_performance",
            "get_bestselling_products",
            "get_bestselling_videos",
            "list_live_performance_all",
        } <= asked
        assert limiter.exhaustion_checks, "backoff consults the limiter before each leg"
        assert {ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH, ANALYTICS_SHOP_PERFORMANCE_PATH} <= set(
            limiter.acquired
        )

        persisted = await TikTokSyncStateRepo(session).load(shop.id)
        assert {
            "shop_sku_performance_last_sync_at",
            "shop_performance_last_sync_at",
            "bestselling_products_last_sync_at",
            "bestselling_videos_last_sync_at",
        } <= set(persisted)
