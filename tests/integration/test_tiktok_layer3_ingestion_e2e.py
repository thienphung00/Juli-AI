"""Layer 3 mock integration tests — Issue #302.

Exercises the full ingestion path without live TikTok API calls:
polling orchestration (#298) → ETL upserts (#299) → webhook catalog handoff (#354).

Fixtures reuse Layer 0/1 contract-collection samples via recorded replay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.constants import ORDER_SEARCH_PATH
from juli_backend.integrations.tiktok.factories import ProductionReadClientFactory
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import ProcessedEvent, Shop, User
from juli_backend.repositories.repos import (
    OrdersRepo,
    ProductsRepo,
    TikTokCredentialRepo,
    TikTokSyncStateRepo,
    WorkflowWebhookSignalsRepo,
)
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion.handoff import make_etl_handoff
from juli_backend.services.webhook.app import WEBHOOK_PATH, create_app
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    run_fujiwa_poll_cycle,
)

from tests.integration.tiktok_recorded_replay import load_sample, recorded_tiktok_replay

APP_KEY = "layer3_app_key"
APP_SECRET = "layer3_app_secret"
SHOP_CIPHER = "ROW_layer3_cipher"

ORDERS_FIXTURE = load_sample("orders-search-response.json")
PRODUCTS_FIXTURE = load_sample("products-search-response.json")
RETURNS_FIXTURE = load_sample("returns-search-response.json")

EXPECTED_ORDER_ID = ORDERS_FIXTURE["response"]["data"]["orders"][0]["id"]
EXPECTED_PRODUCT_ID = PRODUCTS_FIXTURE["response"]["data"]["products"][0]["id"]
EXPECTED_ORDER_CURSOR = ORDERS_FIXTURE["response"]["data"]["orders"][0]["update_time"]
EXPECTED_PRODUCT_CURSOR = PRODUCTS_FIXTURE["response"]["data"]["products"][0]["update_time"]
EXPECTED_RETURN_CURSOR = RETURNS_FIXTURE["response"]["data"]["return_orders"][0]["update_time"]


def _sign_webhook(app_key: str, app_secret: str, body: bytes) -> str:
    sign_string = f"{app_key}{WEBHOOK_PATH}{body.decode()}"
    return hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest_asyncio.fixture
async def user(session, user_id):
    u = User(id=user_id, phone="+84901234569")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def fujiwa_shop(session, user):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Fujiwa Layer3 Store",
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
        access_token="layer3_access",
        refresh_token="layer3_refresh",
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
def poll_config():
    return FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET)


@pytest.fixture
def dlq_messages():
    return []


@pytest.fixture
def publish_dlq(dlq_messages):
    async def _publish(topic: str, key: str, value: bytes) -> None:
        dlq_messages.append({"topic": topic, "key": key, "value": value})

    return _publish


@pytest.fixture
def etl_consumer(session, publish_dlq):
    return EtlConsumer(session=session, publish_dlq=publish_dlq)


@pytest.fixture
def etl_handoff(etl_consumer):
    return make_etl_handoff(etl_consumer)


@pytest.fixture
def run_replay_poll(session, oauth_service, mock_rate_limiter, etl_handoff, poll_config):
    async def _run(*, fujiwa_credential, fail_paths=None):
        with recorded_tiktok_replay(fail_paths=fail_paths):
            await run_fujiwa_poll_cycle(
                session=session,
                config=poll_config,
                oauth_service=oauth_service,
                rate_limiter=mock_rate_limiter,
                handoff_fn=etl_handoff,
                resolve_credential=AsyncMock(return_value=fujiwa_credential),
                factory=ProductionReadClientFactory(),
            )
            await session.commit()

    return _run


class TestPollToEtlIngestion:
    @pytest.mark.asyncio
    async def test_poll_cycle_persists_canonical_entities_via_etl(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """Recorded poll responses upsert orders and products through ETL."""
        await run_replay_poll(fujiwa_credential=fujiwa_credential)

        orders = await OrdersRepo(session).list(fujiwa_shop.id)
        products = await ProductsRepo(session).list(fujiwa_shop.id)

        assert len(orders) == 1
        assert orders[0].tiktok_order_id == EXPECTED_ORDER_ID
        assert len(products) == 1
        assert products[0].tiktok_product_id == EXPECTED_PRODUCT_ID

    @pytest.mark.asyncio
    async def test_repoll_is_idempotent_for_etl_upserts(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """Second poll with identical fixtures does not duplicate canonical rows."""
        await run_replay_poll(fujiwa_credential=fujiwa_credential)
        order_count_after_first = len(await OrdersRepo(session).list(fujiwa_shop.id))
        product_count_after_first = len(await ProductsRepo(session).list(fujiwa_shop.id))
        processed_after_first = (
            await session.execute(select(func.count()).select_from(ProcessedEvent))
        ).scalar_one()

        await run_replay_poll(fujiwa_credential=fujiwa_credential)

        assert len(await OrdersRepo(session).list(fujiwa_shop.id)) == order_count_after_first
        assert len(await ProductsRepo(session).list(fujiwa_shop.id)) == product_count_after_first
        processed_after_second = (
            await session.execute(select(func.count()).select_from(ProcessedEvent))
        ).scalar_one()
        assert processed_after_second == processed_after_first

    @pytest.mark.asyncio
    async def test_rate_limit_backoff_completes_poll_without_raising(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        oauth_service,
        etl_handoff,
        poll_config,
    ):
        """Positive TTL backoff sleeps once, then the poll cycle completes."""
        rate_limiter = MagicMock()
        rate_limiter.is_exhausted.side_effect = [True, False, False, False, False]
        rate_limiter.time_until_reset.return_value = 0.01
        rate_limiter.acquire.return_value = True

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with recorded_tiktok_replay():
            await run_fujiwa_poll_cycle(
                session=session,
                config=poll_config,
                oauth_service=oauth_service,
                rate_limiter=rate_limiter,
                handoff_fn=etl_handoff,
                resolve_credential=AsyncMock(return_value=fujiwa_credential),
                factory=ProductionReadClientFactory(),
                sleep=fake_sleep,
            )
            await session.commit()

        assert sleep_calls == [0.01]
        assert len(await OrdersRepo(session).list(fujiwa_shop.id)) == 1

    @pytest.mark.asyncio
    async def test_partial_endpoint_failure_preserves_sync_state_and_partial_etl(
        self,
        session,
        fujiwa_shop,
        fujiwa_credential,
        run_replay_poll,
    ):
        """When orders fail, products/returns still persist and prior cursors remain."""
        repo = TikTokSyncStateRepo(session)
        seeded_orders_cursor = EXPECTED_ORDER_CURSOR - 1
        await repo.save(
            fujiwa_shop.id,
            {"orders_last_update_time": seeded_orders_cursor},
        )
        await session.commit()

        await run_replay_poll(
            fujiwa_credential=fujiwa_credential,
            fail_paths=frozenset({ORDER_SEARCH_PATH}),
        )

        loaded = await repo.load(fujiwa_shop.id)
        assert loaded["orders_last_update_time"] == seeded_orders_cursor
        assert loaded["products_last_update_time"] == EXPECTED_PRODUCT_CURSOR
        assert loaded["returns_last_update_time"] == EXPECTED_RETURN_CURSOR

        assert len(await OrdersRepo(session).list(fujiwa_shop.id)) == 0
        assert len(await ProductsRepo(session).list(fujiwa_shop.id)) == 1


class TestWebhookCatalogEtlHandoff:
    @pytest.fixture
    def webhook_body(self) -> bytes:
        return json.dumps(
            {
                "type": "ORDER_STATUS_CHANGE",
                "shop_id": PRODUCTION_AUTH_ID,
                "timestamp": 1_700_000_000,
                "data": {
                    "order_id": "577000000000302",
                    "order_status": "AWAITING_SHIPMENT",
                    "update_time": 1_700_000_000,
                    "payment": {"total_amount": "120000.00", "currency": "VND"},
                },
            }
        ).encode()

    @pytest_asyncio.fixture
    async def webhook_client(self, session, engine, etl_handoff):
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        app = create_app(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            handoff_fn=etl_handoff,
            session_factory=session_factory,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_catalog_webhook_routes_to_etl_and_persists_order(
        self,
        session,
        fujiwa_shop,
        webhook_client,
        webhook_body,
    ):
        signature = _sign_webhook(APP_KEY, APP_SECRET, webhook_body)

        response = await webhook_client.post(
            WEBHOOK_PATH,
            content=webhook_body,
            headers={"Authorization": signature, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"code": 0}

        orders = await OrdersRepo(session).list(fujiwa_shop.id)
        assert len(orders) == 1
        assert orders[0].tiktok_order_id == "577000000000302"

        signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(fujiwa_shop.id)
        assert len(signals) == 1
        assert signals[0].catalog_id == 1
        assert signals[0].event_type == "ORDER_STATUS_CHANGE"

    @pytest.mark.asyncio
    async def test_duplicate_catalog_webhook_dedupes_etl_and_signals(
        self,
        session,
        fujiwa_shop,
        webhook_client,
        webhook_body,
    ):
        signature = _sign_webhook(APP_KEY, APP_SECRET, webhook_body)
        headers = {"Authorization": signature, "Content-Type": "application/json"}

        first = await webhook_client.post(WEBHOOK_PATH, content=webhook_body, headers=headers)
        second = await webhook_client.post(WEBHOOK_PATH, content=webhook_body, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200

        assert len(await OrdersRepo(session).list(fujiwa_shop.id)) == 1
        assert len(await WorkflowWebhookSignalsRepo(session).list_for_shop(fujiwa_shop.id)) == 1
        processed_count = (
            await session.execute(
                select(func.count())
                .select_from(ProcessedEvent)
                .where(ProcessedEvent.shop_id == fujiwa_shop.id)
            )
        ).scalar_one()
        assert processed_count == 1
