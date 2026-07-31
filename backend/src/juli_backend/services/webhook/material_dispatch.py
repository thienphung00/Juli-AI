"""Enqueue material Analytics precompute to Celery."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from juli_backend.services.cdp_speed import webhook_catalog_enqueue_reason
from juli_backend.services.tiktok.webhook_catalog import (
    catalog_id_for_event,
    is_material_catalog_id,
)
from juli_backend.services.webhook.material_gate import MaterialEnqueueGate

logger = logging.getLogger(__name__)


class MaterialAnalyticsDispatcher(Protocol):
    def enqueue(
        self,
        shop_key: str,
        *,
        event_type: str,
        enqueue_reason: str,
    ) -> str: ...


@dataclass
class CeleryMaterialAnalyticsDispatcher:
    def enqueue(
        self,
        shop_key: str,
        *,
        event_type: str,
        enqueue_reason: str,
    ) -> str:
        from juli_backend.workers.tasks.material_analytics_precompute import (
            material_analytics_precompute,
        )

        async_result = material_analytics_precompute.delay(
            shop_key,
            event_type=event_type,
            enqueue_reason=enqueue_reason,
        )
        return async_result.id


@dataclass
class _DefaultMaterialAnalyticsDispatcher:
    def enqueue(
        self,
        shop_key: str,
        *,
        event_type: str,
        enqueue_reason: str,
    ) -> str:
        return CeleryMaterialAnalyticsDispatcher().enqueue(
            shop_key,
            event_type=event_type,
            enqueue_reason=enqueue_reason,
        )


_dispatcher: MaterialAnalyticsDispatcher | None = None
_gate: MaterialEnqueueGate | None = None


def get_material_analytics_dispatcher() -> MaterialAnalyticsDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _DefaultMaterialAnalyticsDispatcher()
    return _dispatcher


def set_material_analytics_dispatcher(
    dispatcher: MaterialAnalyticsDispatcher | None,
) -> None:
    global _dispatcher
    _dispatcher = dispatcher


def get_material_enqueue_gate() -> MaterialEnqueueGate:
    global _gate
    if _gate is None:
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            import redis

            from juli_backend.services.webhook.material_gate import RedisMaterialEnqueueGate

            _gate = RedisMaterialEnqueueGate(redis.from_url(redis_url))
        else:
            from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate

            _gate = InMemoryMaterialEnqueueGate()
    return _gate


def set_material_enqueue_gate(gate: MaterialEnqueueGate | None) -> None:
    global _gate
    _gate = gate


def material_compute_env_ready() -> bool:
    """Return True when TikTok + Redis env is configured for material compute."""
    return all(
        os.getenv(name, "").strip()
        for name in (
            "TIKTOK_APP_KEY",
            "TIKTOK_APP_SECRET",
            "TIKTOK_REDIRECT_URI",
            "REDIS_URL",
        )
    )


def maybe_enqueue_material_analytics_compute(
    shop_key: str,
    event_type: str,
    *,
    dispatcher: MaterialAnalyticsDispatcher | None = None,
    gate: MaterialEnqueueGate | None = None,
) -> str | None:
    """Enqueue shop Analytics compute when event type is material and gate allows."""
    catalog_id = catalog_id_for_event(event_type)
    if catalog_id is None or not is_material_catalog_id(catalog_id):
        return None

    if not material_compute_env_ready():
        logger.info(
            "material_enqueue_skipped",
            extra={
                "shop_key": shop_key,
                "event_type": event_type,
                "enqueue_reason": "missing_tiktok_or_redis_env",
            },
        )
        return None

    resolved_gate = gate if gate is not None else get_material_enqueue_gate()
    if not resolved_gate.try_acquire(shop_key, catalog_id):
        return None

    resolved_dispatcher = (
        dispatcher if dispatcher is not None else get_material_analytics_dispatcher()
    )
    return resolved_dispatcher.enqueue(
        shop_key,
        event_type=event_type,
        enqueue_reason=webhook_catalog_enqueue_reason(catalog_id),
    )
