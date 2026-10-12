"""Webhooks 15 / 16 / 18 / 63 / 39 → a product or activity re-read (D30.4).

``history_work_for`` turns one parsed webhook into :class:`HistoryWork` (which
product or activity to re-read, why, and the webhook's hint); ``enqueue_work``
hands it to the Celery tasks in ``workers/tasks/product_history.py``.

Idempotent by notification: the caller records the webhook signal first
(``workflow_webhook_signals``, unique ``event_id`` = ``ttsn:<tts_notification_id>``
when TikTok sends one) and enqueues only a signal it stored for the first time;
the re-read itself is idempotent too (no new snapshot when nothing changed, a
deduplicated change key). Rate-limited twice: a per (shop, subject) coalescing
gate drops a burst of notifications for the same product inside
``COALESCE_SECONDS``, and every TikTok read takes a token from the shared
per-shop window.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from juli_backend.models.history import (
    KIND_CATEGORY,
    KIND_CONTENT,
    KIND_CREATION,
    SOURCE_WEBHOOK_15,
    SOURCE_WEBHOOK_16,
    SOURCE_WEBHOOK_18,
    SOURCE_WEBHOOK_39,
    SOURCE_WEBHOOK_63,
)
from juli_backend.services.product_history.promotions import parse_activity_change

logger = logging.getLogger(__name__)

PRODUCT_CATALOG_IDS: dict[int, tuple[str, str]] = {
    15: (SOURCE_WEBHOOK_15, KIND_CONTENT),
    16: (SOURCE_WEBHOOK_16, KIND_CREATION),
    18: (SOURCE_WEBHOOK_18, KIND_CATEGORY),
}
ACTIVITY_CATALOG_IDS: dict[int, str] = {63: SOURCE_WEBHOOK_63, 39: SOURCE_WEBHOOK_39}
#: Raw ``webhook_raw_events.event_type`` values of the types above (TikTok sends
#: the numeric id; the names are accepted too).
RAW_EVENT_TYPES: tuple[str, ...] = (
    "15",
    "16",
    "18",
    "39",
    "63",
    "PRODUCT_INFORMATION_CHANGE",
    "PRODUCT_CREATION",
    "PRODUCT_CATEGORY_CHANGE",
    "ACTIVITY_STATUS_CHANGE",
    "ACTIVITY_CHANGE",
)
COALESCE_SECONDS = 60

#: TikTok's ``changed_fields`` names → the snapshot's content field names.
_FIELD_NAMES = {
    "title": "title",
    "product_name": "title",
    "description": "description",
    "main_images": "main_images",
    "main_image": "main_images",
    "images": "main_images",
    "attributes": "attributes",
    "product_attributes": "attributes",
}


@dataclass(frozen=True)
class HistoryWork:
    """What one webhook asks the history to re-read."""

    tiktok_shop_id: str
    source: str
    #: ``product`` or ``activity``.
    subject: str
    subject_id: str
    hint_kind: str | None = None
    hint_fields: list[str] = field(default_factory=list)
    #: ``ActivityChange.to_json()`` for an activity.
    change: dict[str, Any] | None = None


def _changed_fields(data: Mapping[str, Any]) -> list[str]:
    raw = data.get("changed_fields") or data.get("change_fields") or []
    names = raw if isinstance(raw, list) else [raw]
    out = []
    for name in names:
        key = str(name or "").strip().lower()
        if key:
            out.append(_FIELD_NAMES.get(key, key))
    return sorted(set(out))


def history_work_for(
    catalog_id: int, tiktok_shop_id: str, data: Mapping[str, Any] | None
) -> HistoryWork | None:
    """The re-read a history webhook asks for; ``None`` for other types or no subject id."""
    body = data or {}
    if catalog_id in PRODUCT_CATALOG_IDS:
        source, kind = PRODUCT_CATALOG_IDS[catalog_id]
        product_id = str(body.get("product_id") or body.get("id") or "")
        if not product_id:
            return None
        fields = _changed_fields(body)
        if catalog_id == 18:
            fields = ["category_id"]
        return HistoryWork(
            tiktok_shop_id=tiktok_shop_id,
            source=source,
            subject="product",
            subject_id=product_id,
            hint_kind=kind,
            hint_fields=fields,
        )
    if catalog_id in ACTIVITY_CATALOG_IDS:
        try:
            change = parse_activity_change(body, catalog_id=catalog_id)
        except ValueError:
            return None
        return HistoryWork(
            tiktok_shop_id=tiktok_shop_id,
            source=ACTIVITY_CATALOG_IDS[catalog_id],
            subject="activity",
            subject_id=change.activity_id,
            change=change.to_json(),
        )
    return None


def notification_event_id(raw: Mapping[str, Any]) -> str | None:
    """``ttsn:<tts_notification_id>`` -- the idempotency key TikTok gives every push."""
    value = raw.get("tts_notification_id") or raw.get("notification_id")
    return f"ttsn:{value}" if value else None


class HistoryEnqueuer(Protocol):
    def __call__(self, shop_id: str, work: HistoryWork) -> str | None: ...


class CoalesceGate(Protocol):
    def try_acquire(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryCoalesceGate:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._until: dict[str, float] = {}
        self._clock = clock

    def try_acquire(self, key: str, ttl_seconds: int) -> bool:
        now = self._clock()
        if self._until.get(key, 0.0) > now:
            return False
        self._until[key] = now + ttl_seconds
        return True


class RedisCoalesceGate:
    def __init__(self, client: Any) -> None:
        self._client = client

    def try_acquire(self, key: str, ttl_seconds: int) -> bool:
        return bool(self._client.set(f"history:coalesce:{key}", "1", nx=True, ex=ttl_seconds))


_enqueuer: HistoryEnqueuer | None = None
_gate: CoalesceGate | None = None


def set_history_enqueuer(enqueuer: HistoryEnqueuer | None) -> None:
    global _enqueuer
    _enqueuer = enqueuer


def get_history_enqueuer() -> HistoryEnqueuer | None:
    """The Celery adapter ``workers/dispatch_binding`` binds at API / worker startup."""
    return _enqueuer


def set_coalesce_gate(gate: CoalesceGate | None) -> None:
    global _gate
    _gate = gate


def get_coalesce_gate() -> CoalesceGate:
    global _gate
    if _gate is None:
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            import redis

            _gate = RedisCoalesceGate(redis.from_url(redis_url))
        else:
            _gate = InMemoryCoalesceGate()
    return _gate


def enqueue_work(
    shop_id: str,
    work: HistoryWork,
    *,
    enqueuer: HistoryEnqueuer | None = None,
    gate: CoalesceGate | None = None,
) -> str | None:
    """Enqueue one re-read; never raises. ``None`` when coalesced or the broker failed.

    Activity changes are never coalesced (each 63 carries its own product lists).
    """
    if work.subject == "product":
        key = f"{shop_id}:{work.subject}:{work.subject_id}:{work.source}"
        try:
            if not (gate or get_coalesce_gate()).try_acquire(key, COALESCE_SECONDS):
                logger.info("product_history_webhook_coalesced", extra={"key": key})
                return None
        except Exception:
            logger.warning("product_history_coalesce_gate_failed", exc_info=True)
    bound = enqueuer or get_history_enqueuer()
    if bound is None:
        logger.warning("product_history_enqueuer_not_bound", extra={"shop_id": shop_id})
        return None
    try:
        return bound(shop_id, work)
    except Exception:
        logger.error(
            "product_history_enqueue_failed",
            extra={"shop_id": shop_id, "subject": work.subject, "source": work.source},
            exc_info=True,
        )
        return None


__all__ = [
    "ACTIVITY_CATALOG_IDS",
    "COALESCE_SECONDS",
    "PRODUCT_CATALOG_IDS",
    "RAW_EVENT_TYPES",
    "HistoryWork",
    "InMemoryCoalesceGate",
    "enqueue_work",
    "history_work_for",
    "notification_event_id",
    "set_coalesce_gate",
    "set_history_enqueuer",
]
