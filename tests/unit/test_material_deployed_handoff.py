"""Issue #625 — deployed material webhook handoff → compute enqueue.

AC1 → each locked material catalog id enqueues exactly one compute job after ETL
AC2 → #68 coalesce: burst yields ≤1 enqueue per shop per 15 minutes
AC3 → concurrent material events do not fan out unbounded jobs (shop mutex)
AC4 → deployed assembly enqueues compute
    (see tests/integration/test_material_deployed_webhook_handoff.py)
AC5 → missing TikTok+Redis env skips enqueue with logged reason
AC6 → material handoff path does not call forbidden poll/sync helpers
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juli_backend.services.etl.consumer import ProcessOutcome
from juli_backend.services.tiktok.webhook_catalog import (
    COALESCE_68_SECONDS,
    MATERIAL_CATALOG_IDS,
    catalog_id_for_event,
    is_material_catalog_id,
)
from juli_backend.services.webhook.material_dispatch import (
    material_compute_env_ready,
    maybe_enqueue_material_analytics_compute,
)
from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate
from juli_backend.services.webhook.material_handoff import make_material_etl_handoff

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"

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

NON_MATERIAL_TYPES = (
    "RECIPIENT_ADDRESS_UPDATE",  # 3
    "PACKAGE_UPDATE",  # 4
    "CANCELLATION_STATUS_CHANGE",  # 11
    "FBT_INVENTORY_UPDATE",  # 24
)


def _event_payload(event_type: str, shop_id: str = "tiktok_shop_625") -> bytes:
    body: dict = {
        "type": event_type,
        "shop_id": shop_id,
        "timestamp": 1_700_000_000,
        "data": {},
    }
    if event_type == "ORDER_STATUS_CHANGE":
        body["data"] = {
            "order_id": "577000000000625",
            "order_status": "AWAITING_SHIPMENT",
            "update_time": 1_700_000_000,
        }
    elif event_type == "INVENTORY_CHANGED":
        body["data"] = {
            "seller_id": shop_id,
            "sku_id": "sku-625",
            "update_time": 1_700_000_000,
        }
    return json.dumps(body).encode()


@pytest.fixture
def material_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


class TestMaterialCatalogScope:
    def test_locked_material_catalog_ids(self):
        assert MATERIAL_CATALOG_IDS == frozenset({1, 2, 5, 12, 27, 39, 67, 68})

    @pytest.mark.parametrize("event_type", MATERIAL_TYPES)
    def test_material_types_in_scope(self, event_type: str):
        catalog_id = catalog_id_for_event(event_type)
        assert catalog_id is not None
        assert is_material_catalog_id(catalog_id)


class TestMaterialEnqueueAfterEtl:
    @pytest.mark.parametrize("event_type", MATERIAL_TYPES)
    @pytest.mark.asyncio
    async def test_ac1_each_material_type_enqueues_once_after_etl(
        self, event_type: str, material_env, monkeypatch
    ):
        consumer = MagicMock()
        consumer.ingest = AsyncMock(return_value=ProcessOutcome.PROCESSED)
        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = f"task-{event_type}"
        gate = InMemoryMaterialEnqueueGate()

        from juli_backend.services.webhook import material_dispatch

        monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)
        monkeypatch.setattr(material_dispatch, "_gate", gate)

        handoff = make_material_etl_handoff(consumer)
        await handoff(
            f"tiktok.{event_type.lower()}",
            "tiktok_shop_625",
            _event_payload(event_type),
        )

        dispatcher.enqueue.assert_called_once_with("tiktok_shop_625")

    @pytest.mark.parametrize("event_type", NON_MATERIAL_TYPES)
    @pytest.mark.asyncio
    async def test_ac1_non_material_types_do_not_enqueue(self, event_type: str, material_env):
        dispatcher = MagicMock()
        gate = InMemoryMaterialEnqueueGate()

        task_id = maybe_enqueue_material_analytics_compute(
            "tiktok_shop_625",
            event_type,
            dispatcher=dispatcher,
            gate=gate,
        )

        assert task_id is None
        dispatcher.enqueue.assert_not_called()


class TestCatalog68Coalesce:
    def test_ac2_coalesce_blocks_burst_within_15_minutes(self, material_env):
        base = 1_700_000_000.0
        clock = MagicMock(side_effect=[base, base + 30, base + COALESCE_68_SECONDS + 1])
        gate = InMemoryMaterialEnqueueGate(clock=clock)
        dispatcher = MagicMock()
        dispatcher.enqueue.return_value = "task-68"

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

        assert first == "task-68"
        assert second is None
        assert third == "task-68"
        assert dispatcher.enqueue.call_count == 2


class TestConcurrentMaterialMutex:
    def test_ac3_mutex_blocks_concurrent_enqueues(self, material_env):
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


class TestMissingEnvSkipsEnqueue:
    def test_ac5_missing_env_does_not_enqueue(self, monkeypatch, caplog):
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        monkeypatch.delenv("TIKTOK_REDIRECT_URI", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        assert material_compute_env_ready() is False

        dispatcher = MagicMock()
        gate = InMemoryMaterialEnqueueGate()

        with caplog.at_level(logging.INFO):
            task_id = maybe_enqueue_material_analytics_compute(
                "tiktok_shop_625",
                "ORDER_STATUS_CHANGE",
                dispatcher=dispatcher,
                gate=gate,
            )

        assert task_id is None
        dispatcher.enqueue.assert_not_called()
        assert any(
            rec.message == "material_enqueue_skipped"
            and getattr(rec, "enqueue_reason", None) == "missing_tiktok_or_redis_env"
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_ac5_handoff_skips_enqueue_when_env_missing(self, monkeypatch, caplog):
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        monkeypatch.delenv("TIKTOK_REDIRECT_URI", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        consumer = MagicMock()
        consumer.ingest = AsyncMock(return_value=ProcessOutcome.PROCESSED)
        dispatcher = MagicMock()

        from juli_backend.services.webhook import material_dispatch

        monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)

        handoff = make_material_etl_handoff(consumer)
        with caplog.at_level(logging.INFO):
            await handoff(
                "tiktok.order_status_change",
                "tiktok_shop_625",
                _event_payload("ORDER_STATUS_CHANGE"),
            )

        consumer.ingest.assert_awaited_once()
        dispatcher.enqueue.assert_not_called()


class TestForbiddenPollHelpersNotCalled:
    @pytest.mark.asyncio
    async def test_ac6_handoff_does_not_call_forbidden_poll_helpers(
        self, material_env, monkeypatch
    ):
        consumer = MagicMock()
        consumer.ingest = AsyncMock(return_value=ProcessOutcome.PROCESSED)

        from juli_backend.services.webhook import material_dispatch

        monkeypatch.setattr(
            material_dispatch,
            "_dispatcher",
            MagicMock(enqueue=MagicMock(return_value="task-safe")),
        )
        monkeypatch.setattr(
            material_dispatch,
            "_gate",
            InMemoryMaterialEnqueueGate(),
        )

        with (
            patch(
                "juli_backend.workers.services.polling.run_fujiwa_poll_cycle",
                create=True,
            ) as poll_cycle,
            patch(
                "juli_backend.workers.services.polling._FUJIWA_POLL_STEPS",
                create=True,
            ) as poll_steps,
            patch(
                "juli_backend.workers.services.polling.sync.sync_analytics",
                create=True,
            ) as sync_analytics,
        ):
            handoff = make_material_etl_handoff(consumer)
            await handoff(
                "tiktok.order_status_change",
                "tiktok_shop_625",
                _event_payload("ORDER_STATUS_CHANGE"),
            )

        poll_cycle.assert_not_called()
        poll_steps.assert_not_called()
        sync_analytics.assert_not_called()
