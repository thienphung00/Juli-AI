"""Kafka ETL consumer — dedup, transform, persist, DLQ."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.repos import (
    CreatorsRepo,
    InventoryRepo,
    LivestreamsRepo,
    OrdersRepo,
    ProcessedEventsRepo,
    ProductsRepo,
    SettlementsRepo,
    ShopsRepo,
)
from src.etl.event_id import extract_event_id
from src.etl.topics import DLQ_TOPIC
from src.etl.transform import TransformError, transform_for_topic

logger = logging.getLogger(__name__)

PublishDlqFn = Callable[[str, str, bytes], Awaitable[None]]

LATENCY_BUDGET_SECONDS = 60.0


class ProcessOutcome(str, Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    DLQ = "dlq"


@dataclass(frozen=True)
class KafkaRecord:
    topic: str
    partition_key: str
    value: bytes
    published_at: float | None = None


@dataclass
class _ShopState:
    lock: asyncio.Lock
    pending: int = 0


class EtlConsumer:
    """Consumes raw TikTok Kafka events and writes through ``data`` repos."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        publish_dlq: PublishDlqFn,
        max_pending_per_shop: int = 100,
        latency_budget_seconds: float = LATENCY_BUDGET_SECONDS,
        clock: Callable[[], float] = time.time,
        before_persist: Callable[[KafkaRecord], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._publish_dlq = publish_dlq
        self._max_pending = max_pending_per_shop
        self._latency_budget = latency_budget_seconds
        self._clock = clock
        self._before_persist = before_persist
        self._shops = ShopsRepo(session)
        self._processed = ProcessedEventsRepo(session)
        self._orders = OrdersRepo(session)
        self._products = ProductsRepo(session)
        self._inventory = InventoryRepo(session)
        self._creators = CreatorsRepo(session)
        self._livestreams = LivestreamsRepo(session)
        self._settlements = SettlementsRepo(session)
        self._shop_states: dict[str, _ShopState] = {}

    def _shop_state(self, shop_key: str) -> _ShopState:
        if shop_key not in self._shop_states:
            self._shop_states[shop_key] = _ShopState(lock=asyncio.Lock())
        return self._shop_states[shop_key]

    async def ingest(self, record: KafkaRecord) -> ProcessOutcome:
        """Process one message with per-shop ordering and backpressure."""
        state = self._shop_state(record.partition_key)
        if state.pending >= self._max_pending:
            logger.warning(
                "etl_backpressure",
                extra={"shop_key": record.partition_key, "pending": state.pending},
            )
            await asyncio.sleep(0.01)

        async with state.lock:
            state.pending += 1
            try:
                return await self._process_unlocked(record)
            finally:
                state.pending -= 1

    async def _process_unlocked(self, record: KafkaRecord) -> ProcessOutcome:
        published_at = record.published_at if record.published_at is not None else self._clock()
        if self._clock() - published_at > self._latency_budget:
            logger.warning(
                "etl_latency_budget_exceeded",
                extra={
                    "topic": record.topic,
                    "shop_key": record.partition_key,
                    "age_seconds": self._clock() - published_at,
                },
            )

        try:
            payload = json.loads(record.value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            await self._send_dlq(record, error=str(exc), payload=None)
            return ProcessOutcome.DLQ

        if not isinstance(payload, dict):
            await self._send_dlq(record, error="payload must be a JSON object", payload=payload)
            return ProcessOutcome.DLQ

        try:
            event_id = extract_event_id(
                topic=record.topic, shop_key=record.partition_key, payload=payload
            )
        except (TypeError, ValueError) as exc:
            await self._send_dlq(record, error=str(exc), payload=payload)
            return ProcessOutcome.DLQ

        shop = await self._shops.get_by_tiktok_id(record.partition_key)
        if shop is None:
            await self._send_dlq(
                record,
                error=f"unknown shop tiktok_shop_id={record.partition_key}",
                payload=payload,
            )
            return ProcessOutcome.DLQ

        claimed = await self._processed.claim(event_id=event_id, shop_id=shop.id)
        if not claimed:
            logger.info(
                "etl_duplicate_skipped",
                extra={"event_id": event_id, "shop_id": str(shop.id)},
            )
            return ProcessOutcome.DUPLICATE

        if self._before_persist is not None:
            await self._before_persist(record)

        try:
            entity_kind, kwargs = transform_for_topic(record.topic, payload)
            await self._upsert(entity_kind, shop_id=shop.id, kwargs=kwargs)
        except (TransformError, TypeError, ValueError) as exc:
            await self._send_dlq(record, error=str(exc), payload=payload)
            await self._session.commit()
            return ProcessOutcome.DLQ

        await self._session.commit()
        logger.info(
            "etl_event_processed",
            extra={
                "event_id": event_id,
                "topic": record.topic,
                "shop_id": str(shop.id),
                "entity_kind": entity_kind,
            },
        )
        return ProcessOutcome.PROCESSED

    async def _upsert(
        self, entity_kind: str, *, shop_id: Any, kwargs: dict[str, Any]
    ) -> None:
        repos = {
            "order": self._orders,
            "product": self._products,
            "inventory": self._inventory,
            "creator": self._creators,
            "livestream": self._livestreams,
            "settlement": self._settlements,
        }
        repo = repos.get(entity_kind)
        if repo is None:
            raise TransformError(f"unknown entity kind {entity_kind}")
        await repo.upsert(shop_id=shop_id, **kwargs)

    async def _send_dlq(
        self,
        record: KafkaRecord,
        *,
        error: str,
        payload: dict[str, Any] | None,
    ) -> None:
        envelope = {
            "original_topic": record.topic,
            "partition_key": record.partition_key,
            "error": error,
            "payload": payload,
            "raw": record.value.decode(errors="replace"),
        }
        logger.error(
            "etl_dlq",
            extra={
                "topic": record.topic,
                "shop_key": record.partition_key,
                "error": error,
            },
        )
        await self._publish_dlq(
            DLQ_TOPIC,
            record.partition_key,
            json.dumps(envelope).encode(),
        )
