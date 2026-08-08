"""Issue #627 — material enqueue (#625) reaches Shared Compute orchestrator."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    GoldKpiEnvelope,
    Shop,
    User,
)
from juli_backend.repositories.repos import OrdersRepo
from juli_backend.services.cdp_speed.enqueue_reason import webhook_catalog_enqueue_reason
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.services.webhook.deployed import handle_tiktok_webhook_delivery
from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate
from juli_backend.services.webhook.material_worker import run_material_analytics_compute

APP_KEY = "material_627_app_key"
APP_SECRET = "material_627_app_secret"
INTEGRATION_ORDER_ID = "577000000000627-int"


def _sign(body: bytes) -> str:
    """Compute HMAC-SHA256 signature for webhook: HMAC-SHA256(app_secret, app_key + body).

    The path is NOT included in webhook signatures (unlike API request signing).
    """
    sign_string = f"{APP_KEY}{body.decode()}"
    return hmac.new(APP_SECRET.encode(), sign_string.encode(), hashlib.sha256).hexdigest()


def _order_status_payload(*, shop_id: str = PRODUCTION_AUTH_ID) -> bytes:
    return json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": shop_id,
            "timestamp": 1_700_000_000,
            "data": {
                "order_id": "577000000000625",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1_700_000_000,
                "payment": {"total_amount": "120000.00", "currency": "VND"},
            },
        }
    ).encode()


async def _integration_fake_fetch_executor(
    session,
    *,
    shop_id: uuid.UUID,
    shop_key: str,
    fetch_plan,
    idempotency_key: str,
) -> BronzeAppendTracker:
    del shop_key
    tracker = BronzeAppendTracker()
    handoff = make_targeted_fetch_bronze_handoff(
        session,
        shop_id=shop_id,
        job_token=job_correlation_token(shop_id, idempotency_key),
        tracker=tracker,
        clock=lambda: datetime(2026, 7, 31, 12, 30, tzinfo=UTC),
    )
    fixture_order = {
        "order_id": INTEGRATION_ORDER_ID,
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "99000.00",
        "currency": "VND",
        "update_time": int(datetime(2026, 7, 31, 12, 30, tzinfo=UTC).timestamp()),
    }
    for resource in fetch_plan.resources:
        if resource.resource_attr == "orders":
            await handoff(
                "tiktok.orders.raw",
                "integration-shop",
                json.dumps(fixture_order).encode(),
            )
    return tracker


@pytest.fixture
def material_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest_asyncio.fixture
async def user(session, user_id):
    user = User(id=user_id, phone="+84901234627")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def material_shop(session, user):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Material 627 Store",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add(shop)
    await session.flush()
    return shop


class TestMaterialEnqueueToSharedComputeOrchestrator:
    @pytest.mark.asyncio
    async def test_webhook_enqueue_runs_orchestrator_silver_orders(
        self,
        session,
        material_shop,
        material_env,
        monkeypatch,
    ):
        from juli_backend.services.webhook import material_dispatch

        gate = InMemoryMaterialEnqueueGate()
        enqueued: list[tuple[str, str]] = []

        class _SyncDispatcher:
            def enqueue(
                self,
                shop_key: str,
                *,
                event_type: str,
                enqueue_reason: str,
            ) -> str:
                enqueued.append((shop_key, event_type, enqueue_reason))
                return "integration-task-627"

        monkeypatch.setattr(material_dispatch, "_dispatcher", _SyncDispatcher())
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
        assert enqueued == [(PRODUCTION_AUTH_ID, "ORDER_STATUS_CHANGE", "webhook_catalog:1")]

        compute_result = await run_material_analytics_compute(
            session,
            shop_key=PRODUCTION_AUTH_ID,
            event_type="ORDER_STATUS_CHANGE",
            enqueue_reason=webhook_catalog_enqueue_reason(1),
            idempotency_key="integration-task-627",
            gate=gate,
            fetch_executor=_integration_fake_fetch_executor,
        )
        assert compute_result is not None
        assert compute_result.silver_promoted >= 1

        orders = await OrdersRepo(session).list(material_shop.id)
        promoted = [o for o in orders if o.tiktok_order_id == INTEGRATION_ORDER_ID]
        assert len(promoted) == 1

        bronze_rows = (
            (
                await session.execute(
                    select(BronzeOrderRawPayload).where(
                        BronzeOrderRawPayload.shop_id == material_shop.id,
                        BronzeOrderRawPayload.ingest_source == "targeted_fetch",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(bronze_rows) == 1
        assert bronze_rows[0].payload["order_id"] == INTEGRATION_ORDER_ID
        token = job_correlation_token(material_shop.id, "integration-task-627")
        assert bronze_rows[0].source_event_id.startswith(f"{token}:")

        gold = await session.get(GoldKpiEnvelope, material_shop.id)
        assert gold is not None

        bronze_count = (
            await session.execute(
                select(func.count())
                .select_from(BronzeOrderRawPayload)
                .where(BronzeOrderRawPayload.shop_id == material_shop.id)
            )
        ).scalar_one()
        assert bronze_count == 1
