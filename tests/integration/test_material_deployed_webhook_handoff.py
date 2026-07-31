"""Issue #625 AC4 — deployed webhook assembly enqueues compute after real ETL.

Exercises production ``handle_tiktok_webhook_delivery`` with real ``EtlConsumer.ingest``
against integration SQLite fixtures. Celery is spied only at the material dispatch enqueue
boundary — ingest is not stubbed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import OrdersRepo, WorkflowWebhookSignalsRepo
from juli_backend.services.webhook.app import WEBHOOK_PATH
from juli_backend.services.webhook.deployed import handle_tiktok_webhook_delivery
from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate

APP_KEY = "material_ac4_app_key"
APP_SECRET = "material_ac4_app_secret"
ORDER_ID = "577000000000625"


def _sign(body: bytes) -> str:
    sign_string = f"{APP_KEY}{WEBHOOK_PATH}{body.decode()}"
    return hmac.new(APP_SECRET.encode(), sign_string.encode(), hashlib.sha256).hexdigest()


def _order_status_payload(*, shop_id: str = PRODUCTION_AUTH_ID) -> bytes:
    return json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": shop_id,
            "timestamp": 1_700_000_000,
            "data": {
                "order_id": ORDER_ID,
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1_700_000_000,
                "payment": {"total_amount": "120000.00", "currency": "VND"},
            },
        }
    ).encode()


@pytest.fixture
def material_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest_asyncio.fixture
async def user(session, user_id):
    user = User(id=user_id, phone="+84901234625")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def material_shop(session, user):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Material AC4 Store",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add(shop)
    await session.flush()
    return shop


class TestDeployedMaterialWebhookHandoff:
    @pytest.mark.asyncio
    async def test_ac4_deployed_delivery_enqueues_after_real_etl(
        self,
        session,
        material_shop,
        material_env,
        monkeypatch,
    ):
        from juli_backend.services.webhook import material_dispatch

        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = "integration-task-625"
        gate = InMemoryMaterialEnqueueGate()
        monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)
        monkeypatch.setattr(material_dispatch, "_gate", gate)

        body = _order_status_payload()
        result = await handle_tiktok_webhook_delivery(
            session=session,
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            body=body,
            signature=_sign(body),
            headers={"Content-Type": "application/json"},
        )

        assert result.status_code == 200

        orders = await OrdersRepo(session).list(material_shop.id)
        assert len(orders) == 1
        assert orders[0].tiktok_order_id == ORDER_ID

        signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(material_shop.id)
        assert len(signals) == 1
        assert signals[0].catalog_id == 1
        assert signals[0].event_type == "ORDER_STATUS_CHANGE"

        dispatcher.enqueue.assert_called_once_with(PRODUCTION_AUTH_ID)
