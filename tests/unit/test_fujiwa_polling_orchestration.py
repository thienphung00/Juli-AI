"""TDD tests for Fujiwa polling orchestration (#298).

Behaviors:
- Production-read (Fujiwa) credentials only — never SANDBOX_VN
- Sync state persisted per endpoint across poll cycles
- Rate-limit backoff completes the cycle without raising
- Token refresh runs before sync
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.constants import INVENTORY_SEARCH_PATH
from juli_backend.integrations.tiktok.factories import ProductionReadClientFactory
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
)
from juli_backend.models.models import Shop, TikTokSyncState, User
from juli_backend.repositories.repos import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    _CycleDeadline,
    _PollStep,
    _run_poll_step,
    run_fujiwa_poll_cycle,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
SHOP_CIPHER = "ROW_test_cipher"


async def _stub_binding_verifier(session, *, capability, access_token) -> str:
    """#1200: these tests exercise polling, not credential binding. A stub keeps
    them off the network and off the vendor identity path entirely."""
    return "ROW_stub_cipher"


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
async def fujiwa_product(session, fujiwa_shop):
    """A synced product row so sync_inventory's product-id source (#1948) has
    something to page: run_fujiwa_poll_cycle now reads product ids off the
    products table (via ProductsRepo, through the cycle's own session)
    rather than calling Search Inventory with none."""
    from tests.support.builders import make_product

    return await make_product(session, fujiwa_shop, tiktok_product_id="fujiwa-product-1")


@pytest_asyncio.fixture
async def fujiwa_credential(session, fujiwa_shop):
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
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
        binding_verifier=_stub_binding_verifier,
    )


@pytest.fixture
def mock_resources():
    resources = MagicMock()
    resources.orders.search_all.return_value = [
        {"id": "o1", "update_time": 1700000100},
    ]
    resources.products.search_all.return_value = [
        {"id": "p1", "updated_at": 1700000200},
    ]
    resources.returns.search_returns_all.return_value = [
        {"return_id": "r1", "update_time": 1700000300},
    ]
    resources.inventory.search.return_value = {
        "code": 0,
        "data": {
            "inventory": [
                {
                    "product_id": "p-inv",
                    "skus": [
                        {
                            "id": "sku-inv",
                            "total_available_quantity": 5,
                            "warehouse_inventory": [{"warehouse_id": "wh-1"}],
                        }
                    ],
                }
            ]
        },
    }
    resources.analytics.list_sku_performance_all.return_value = []
    resources.analytics.list_product_performance_all.return_value = []
    resources.analytics.get_shop_performance.return_value = {}
    resources.analytics.get_shop_performance_per_hour.return_value = {}
    resources.analytics.get_bestselling_products.return_value = {}
    resources.analytics.get_bestselling_videos.return_value = {}
    resources.promotion.get_activity.return_value = {}
    return resources


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
def run_poll(session, oauth_service, mock_rate_limiter, handoff_fn, poll_config, mock_resources):
    async def _run(
        *,
        fujiwa_credential,
        resolve_credential=None,
        factory=None,
        create_resources=None,
    ):
        return await run_fujiwa_poll_cycle(
            session=session,
            config=poll_config,
            oauth_service=oauth_service,
            rate_limiter=mock_rate_limiter,
            handoff_fn=handoff_fn,
            resolve_credential=resolve_credential or AsyncMock(return_value=fujiwa_credential),
            factory=factory,
            create_resources=create_resources or (lambda _cfg: mock_resources),
        )

    return _run


class TestTikTokSyncStateRepo:
    @pytest.mark.asyncio
    async def test_load_returns_empty_when_no_rows(self, session, fujiwa_shop):
        state = await TikTokSyncStateRepo(session).load(fujiwa_shop.id)
        assert state == {}

    @pytest.mark.asyncio
    async def test_save_and_load_per_endpoint(self, session, fujiwa_shop):
        repo = TikTokSyncStateRepo(session)
        await repo.save(
            fujiwa_shop.id,
            {
                "orders_last_update_time": 1700000100,
                "products_last_update_time": 1700000200,
            },
        )

        loaded = await repo.load(fujiwa_shop.id)
        assert loaded["orders_last_update_time"] == 1700000100
        assert loaded["products_last_update_time"] == 1700000200

    @pytest.mark.asyncio
    async def test_save_upserts_existing_endpoint(self, session, fujiwa_shop):
        repo = TikTokSyncStateRepo(session)
        await repo.save(fujiwa_shop.id, {"orders_last_update_time": 100})
        await repo.save(fujiwa_shop.id, {"orders_last_update_time": 200})

        rows = (
            (
                await session.execute(
                    select(TikTokSyncState).where(
                        TikTokSyncState.shop_id == fujiwa_shop.id,
                        TikTokSyncState.endpoint == "orders",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].last_update_time == 200


class TestRunFujiwaPollCycle:
    @pytest.mark.asyncio
    async def test_rejects_sandbox_write_credential(
        self,
        session,
        oauth_service,
        mock_rate_limiter,
        handoff_fn,
        poll_config,
        mock_resources,
    ):
        """#1995 widened which credentials may poll; the sandbox one is still
        refused, now by capability rather than by merchant identity."""
        sandbox_credential = MagicMock()
        sandbox_credential.merchant_authorization_id = SANDBOX_AUTH_ID
        sandbox_credential.capability = TikTokCapability.SANDBOX_WRITE.value

        with pytest.raises(ValueError, match="read-capable"):
            await run_fujiwa_poll_cycle(
                session=session,
                config=poll_config,
                oauth_service=oauth_service,
                rate_limiter=mock_rate_limiter,
                handoff_fn=handoff_fn,
                resolve_credential=AsyncMock(return_value=sandbox_credential),
                create_resources=lambda _cfg: mock_resources,
            )

    @pytest.mark.asyncio
    async def test_does_not_refresh_via_oauth_service_anymore(
        self,
        fujiwa_credential,
        fujiwa_product,
        oauth_service,
        mock_resources,
        run_poll,
    ):
        """ADR-081 decision 4 / #1232: `run_fujiwa_poll_cycle` used to call
        `oauth_service.refresh_merchant_tokens` itself before syncing. That
        call site is deleted -- the credential `resolve_credential` hands
        back is used directly, because in production that resolver
        (`resolve_production_read_credential`) now carries the lazy refresh
        layer itself (`core/security/credential_resolver.py`). `oauth_service`
        stays a required parameter only so
        `services/action_cards/refresh.py::maybe_poll_tiktok_data` keeps
        constructing and passing one unmodified; this test pins that the
        parameter is otherwise inert."""
        refresh_mock = AsyncMock(return_value=fujiwa_credential)
        oauth_service.refresh_merchant_tokens = refresh_mock

        await run_poll(fujiwa_credential=fujiwa_credential)

        refresh_mock.assert_not_awaited()
        mock_resources.orders.search_all.assert_called_once()
        mock_resources.inventory.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_persists_sync_state_per_endpoint(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        fujiwa_product,
        run_poll,
    ):
        await run_poll(fujiwa_credential=fujiwa_credential)

        loaded = await TikTokSyncStateRepo(session).load(fujiwa_shop.id)
        assert loaded["orders_last_update_time"] == 1700000100
        assert loaded["products_last_update_time"] == 1700000200
        assert loaded["returns_last_update_time"] == 1700000300
        assert "inventory_last_sync_at" in loaded

    @pytest.mark.asyncio
    async def test_resumes_from_persisted_sync_state(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        mock_resources,
        run_poll,
    ):
        await TikTokSyncStateRepo(session).save(
            fujiwa_shop.id,
            {"orders_last_update_time": 1699999999},
        )

        await run_poll(fujiwa_credential=fujiwa_credential)

        mock_resources.orders.search_all.assert_called_once_with(
            update_time_from=1699999999,
        )

    @pytest.mark.asyncio
    async def test_completes_when_all_endpoints_rate_limited(
        self,
        fujiwa_credential,
        mock_rate_limiter,
        mock_resources,
        run_poll,
    ):
        mock_rate_limiter.acquire.return_value = False
        mock_rate_limiter.is_exhausted.return_value = True
        mock_rate_limiter.time_until_reset.return_value = 0

        await run_poll(fujiwa_credential=fujiwa_credential)

        mock_resources.orders.search_all.assert_not_called()
        mock_resources.products.search_all.assert_not_called()
        mock_resources.returns.search_returns_all.assert_not_called()
        mock_resources.inventory.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_production_read_factory(
        self,
        fujiwa_credential,
        mock_resources,
        run_poll,
    ):
        factory = ProductionReadClientFactory()
        create_resources = MagicMock(return_value=mock_resources)

        await run_poll(
            fujiwa_credential=fujiwa_credential,
            factory=factory,
            create_resources=create_resources,
        )

        create_resources.assert_called_once()
        config_arg = create_resources.call_args[0][0]
        assert config_arg.merchant_auth_id == PRODUCTION_AUTH_ID
        assert config_arg.access_token == fujiwa_credential.access_token


class TestPollStepProductIdRequirement:
    """#1948: the step that needs product ids must never run without them."""

    @pytest.mark.asyncio
    async def test_a_step_wanting_product_ids_raises_when_none_supplied(self):
        """The guard that stops an optional parameter becoming a silent skip.

        ``_run_poll_step`` takes ``list_product_ids`` as optional because three
        of the four steps do not want it. Without this raise, a caller that
        forgot to thread the source would simply omit it, ``sync_inventory``
        would never be reached, and the inventory step would go quiet again --
        #1948's failure mode exactly, one layer up from where it was fixed.
        """
        sync_fn = AsyncMock()
        step = _PollStep(INVENTORY_SEARCH_PATH, "inventory", sync_fn, wants_product_ids=True)
        rate_limiter = MagicMock()
        rate_limiter.is_exhausted.return_value = False

        with pytest.raises(ValueError, match="requires list_product_ids") as excinfo:
            await _run_poll_step(
                step,
                resources=MagicMock(),
                rate_limiter=rate_limiter,
                handoff_fn=AsyncMock(),
                app_id=APP_KEY,
                shop_key="shop1",
                sync_state={},
                sleep=AsyncMock(),
                # Required since #1969. Generous on purpose: this test is about
                # the product-id guard, not the wall clock.
                deadline=_CycleDeadline(budget_seconds=600.0),
            )

        # The message names which step went unsupplied. A cycle runs four steps
        # and only one wants ids; an error that did not say which would send the
        # reader back through all four.
        assert INVENTORY_SEARCH_PATH in str(excinfo.value)
        # Raised before the worker ran -- not after a partial sync.
        sync_fn.assert_not_awaited()
