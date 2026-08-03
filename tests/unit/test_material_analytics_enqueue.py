"""Issue #532 — material webhook Analytics precompute enqueue contract tests.

AC1 → material types enqueue one shop Analytics compute job after successful ingest
AC2 → worker performs (or skips when warm) poll-step fetches then precompute
AC3 → #68 coalesces to ≤1 compute enqueue per shop per 15 minutes
AC4 → non-material catalog types do not enqueue compute
AC5 → concurrent material events do not fan out unbounded jobs (mutex)
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User
from juli_backend.services.cdp_speed.enqueue_reason import webhook_catalog_enqueue_reason
from juli_backend.services.etl.consumer import ProcessOutcome
from juli_backend.services.tiktok.webhook_catalog import (
    COALESCE_68_SECONDS,
    INVENTORY_CHANGED_CATALOG_ID,
    MATERIAL_CATALOG_IDS,
    catalog_id_for_event,
    is_material_catalog_id,
)
from juli_backend.services.webhook.material_dispatch import (
    maybe_enqueue_material_analytics_compute,
)
from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate
from juli_backend.services.webhook.material_handoff import make_material_etl_handoff

NON_MATERIAL_TYPES = (
    "RECIPIENT_ADDRESS_UPDATE",  # 3
    "PACKAGE_UPDATE",  # 4
    "CANCELLATION_STATUS_CHANGE",  # 11
    "INBOUND_FBT_ORDER_STATUS_CHANGE",  # 21
    "FBT_INVENTORY_UPDATE",  # 24
    "PRODUCT_AUDIT_STATUS_CHANGE",  # 37
    "FBT_MCF_ORDER_STATUS",  # 58
    "AFTERSALES_REQUEST_STATUS_UPDATE",  # 64
    "RMA_STATUS_UPDATE",  # 65
)

MATERIAL_TYPES = (
    "ORDER_STATUS_CHANGE",  # 1
    "REVERSE_STATUS_UPDATE",  # 2
    "PRODUCT_STATUS_CHANGE",  # 5
    "RETURN_STATUS_CHANGE",  # 12
    "INVENTORY_STATUS_CHANGE",  # 27
    "ACTIVITY_STATUS_CHANGE",  # 39
    "REFUND_SUCCESS",  # 67
    "INVENTORY_CHANGED",  # 68
)


@pytest.fixture(autouse=True)
def _material_compute_env(monkeypatch):
    """Material enqueue requires TikTok + Redis env (#625)."""
    monkeypatch.setenv("TIKTOK_APP_KEY", "test_app_key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def _event_payload(event_type: str, shop_id: str = "tiktok_shop_532") -> bytes:
    body: dict = {
        "type": event_type,
        "shop_id": shop_id,
        "timestamp": 1_700_000_000,
        "data": {},
    }
    if event_type == "ORDER_STATUS_CHANGE":
        body["data"] = {
            "order_id": "577000000000532",
            "order_status": "AWAITING_SHIPMENT",
            "update_time": 1_700_000_000,
        }
    elif event_type == "INVENTORY_CHANGED":
        body["shop_id"] = shop_id
        body["data"] = {
            "seller_id": shop_id,
            "sku_id": "sku-532",
            "update_time": 1_700_000_000,
        }
    return json.dumps(body).encode()


class TestMaterialCatalogClassification:
    def test_material_catalog_ids_match_issue_scope(self):
        assert MATERIAL_CATALOG_IDS == frozenset({1, 2, 5, 12, 27, 39, 67, 68})

    @pytest.mark.parametrize("event_type", MATERIAL_TYPES)
    def test_material_event_types_classified(self, event_type: str):
        catalog_id = catalog_id_for_event(event_type)
        assert catalog_id is not None
        assert is_material_catalog_id(catalog_id)

    @pytest.mark.parametrize("event_type", NON_MATERIAL_TYPES)
    def test_non_material_event_types_not_classified(self, event_type: str):
        catalog_id = catalog_id_for_event(event_type)
        assert catalog_id is not None
        assert not is_material_catalog_id(catalog_id)


class TestMaterialEnqueueAfterHandoff:
    @pytest.mark.asyncio
    async def test_ac1_material_handoff_enqueues_after_processed(self, monkeypatch):
        consumer = MagicMock()
        consumer.ingest = AsyncMock(return_value=ProcessOutcome.PROCESSED)
        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = "celery-task-532"
        gate = InMemoryMaterialEnqueueGate()

        from juli_backend.services.webhook import material_dispatch

        monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)
        monkeypatch.setattr(material_dispatch, "_gate", gate)

        handoff = make_material_etl_handoff(consumer)
        payload = _event_payload("ORDER_STATUS_CHANGE")
        await handoff("tiktok.order_status_change", "tiktok_shop_532", payload)

        dispatcher.enqueue.assert_called_once_with(
            "tiktok_shop_532",
            event_type="ORDER_STATUS_CHANGE",
            enqueue_reason=webhook_catalog_enqueue_reason(1),
        )

    @pytest.mark.asyncio
    async def test_material_handoff_skips_on_duplicate(self, monkeypatch):
        consumer = MagicMock()
        consumer.ingest = AsyncMock(return_value=ProcessOutcome.DUPLICATE)
        dispatcher = MagicMock()
        gate = InMemoryMaterialEnqueueGate()

        from juli_backend.services.webhook import material_dispatch

        monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)
        monkeypatch.setattr(material_dispatch, "_gate", gate)

        handoff = make_material_etl_handoff(consumer)
        await handoff(
            "tiktok.order_status_change",
            "tiktok_shop_532",
            _event_payload("ORDER_STATUS_CHANGE"),
        )

        assert dispatcher.enqueue.call_count == 0

    @pytest.mark.parametrize("event_type", NON_MATERIAL_TYPES)
    @pytest.mark.asyncio
    async def test_ac4_non_material_types_do_not_enqueue(self, event_type: str):
        dispatcher = MagicMock()
        gate = InMemoryMaterialEnqueueGate()

        task_id = maybe_enqueue_material_analytics_compute(
            "tiktok_shop_532",
            event_type,
            dispatcher=dispatcher,
            gate=gate,
        )

        assert task_id is None
        dispatcher.enqueue.assert_not_called()


class TestCatalog68Coalesce:
    def test_ac3_coalesce_blocks_second_enqueue_within_15_minutes(self):
        base = 1_700_000_000.0
        clock = MagicMock(side_effect=[base, base + 60, base + COALESCE_68_SECONDS + 1])
        gate = InMemoryMaterialEnqueueGate(clock=clock)
        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = "task-1"

        first = maybe_enqueue_material_analytics_compute(
            "shop-68",
            "INVENTORY_CHANGED",
            dispatcher=dispatcher,
            gate=gate,
        )
        second = maybe_enqueue_material_analytics_compute(
            "shop-68",
            "INVENTORY_CHANGED",
            dispatcher=dispatcher,
            gate=gate,
        )
        third = maybe_enqueue_material_analytics_compute(
            "shop-68",
            "INVENTORY_CHANGED",
            dispatcher=dispatcher,
            gate=gate,
        )

        assert first == "task-1"
        assert second is None
        assert third == "task-1"
        assert dispatcher.enqueue.call_count == 2


class TestConcurrentMaterialMutex:
    def test_ac5_mutex_blocks_concurrent_material_enqueues(self):
        gate = InMemoryMaterialEnqueueGate()
        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = "task-mutex"

        first = maybe_enqueue_material_analytics_compute(
            "shop-mutex",
            "ORDER_STATUS_CHANGE",
            dispatcher=dispatcher,
            gate=gate,
        )
        second = maybe_enqueue_material_analytics_compute(
            "shop-mutex",
            "PRODUCT_STATUS_CHANGE",
            dispatcher=dispatcher,
            gate=gate,
        )

        assert first == "task-mutex"
        assert second is None
        assert dispatcher.enqueue.call_count == 1

        gate.release("shop-mutex")
        third = maybe_enqueue_material_analytics_compute(
            "shop-mutex",
            "PRODUCT_STATUS_CHANGE",
            dispatcher=dispatcher,
            gate=gate,
        )
        assert third == "task-mutex"
        assert dispatcher.enqueue.call_count == 2


@pytest_asyncio.fixture
async def shop(session):
    user = User(id=uuid.uuid4(), phone="+849305000532")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Material Analytics Shop 532",
        tiktok_shop_id="tiktok_shop_532_worker",
    )
    session.add(s)
    await session.flush()
    return s


class TestMaterialWorkerPipeline:
    @pytest.mark.asyncio
    async def test_ac2_worker_runs_shared_compute_hook(self, session, shop, monkeypatch):
        from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeResult
        from juli_backend.services.webhook import material_worker

        compute_calls: list[str] = []

        async def fake_compute(sess, job):
            compute_calls.append(job.shop_key)
            return SharedComputeResult(
                bronze_appended=1,
                silver_promoted=1,
                gold_written=True,
            )

        gate = InMemoryMaterialEnqueueGate()
        gate.try_acquire(shop.tiktok_shop_id, INVENTORY_CHANGED_CATALOG_ID)

        result = await material_worker.run_material_analytics_compute(
            session,
            shop_key=shop.tiktok_shop_id,
            event_type="INVENTORY_CHANGED",
            enqueue_reason=webhook_catalog_enqueue_reason(INVENTORY_CHANGED_CATALOG_ID),
            idempotency_key="unit-test-worker-627",
            gate=gate,
            compute_hook=fake_compute,
        )

        assert compute_calls == [shop.tiktok_shop_id]
        assert result is not None
        assert result.gold_written is True
