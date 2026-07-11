"""ETL consumer — dedup, transform, persist, DLQ."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Order, OrderItem
from juli_backend.repositories.repos import (
    CreatorsRepo,
    InventoryRepo,
    LivestreamsRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProcessedEventsRepo,
    ProductsRepo,
    ReturnsRepo,
    SettlementsRepo,
    ShopsRepo,
)
from juli_backend.services.etl.channels import DLQ_CHANNEL
from juli_backend.services.etl.event_id import extract_event_id
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.etl.transform import TransformError, transform_for_channel

logger = logging.getLogger(__name__)

DlqHandoffFn = Callable[[str, str, bytes], Awaitable[None]]

LATENCY_BUDGET_SECONDS = 60.0


class _UpsertRepo(Protocol):
    async def upsert(self, *, shop_id: Any, **kwargs: Any) -> Any: ...


class ProcessOutcome(str, Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    DLQ = "dlq"


@dataclass
class _ShopState:
    lock: asyncio.Lock
    pending: int = 0


class EtlConsumer:
    """Ingests validated TikTok payloads and writes through ``data`` repos."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        dlq_handoff: DlqHandoffFn | None = None,
        publish_dlq: DlqHandoffFn | None = None,
        max_pending_per_shop: int = 100,
        latency_budget_seconds: float = LATENCY_BUDGET_SECONDS,
        clock: Callable[[], float] = time.time,
        before_persist: Callable[[IngestRecord], Awaitable[None]] | None = None,
    ) -> None:
        resolved_dlq = dlq_handoff or publish_dlq
        if resolved_dlq is None:
            raise TypeError("EtlConsumer requires dlq_handoff= or publish_dlq=")
        self._session = session
        self._dlq_handoff = resolved_dlq
        self._max_pending = max_pending_per_shop
        self._latency_budget = latency_budget_seconds
        self._clock = clock
        self._before_persist = before_persist
        self._shops = ShopsRepo(session)
        self._processed = ProcessedEventsRepo(session)
        self._orders = OrdersRepo(session)
        self._order_items = OrderItemsRepo(session)
        self._returns = ReturnsRepo(session)
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

    async def ingest(self, record: IngestRecord) -> ProcessOutcome:
        """Process one payload with per-shop ordering and backpressure."""
        state = self._shop_state(record.shop_key)
        if state.pending >= self._max_pending:
            logger.warning(
                "etl_backpressure",
                extra={"shop_key": record.shop_key, "pending": state.pending},
            )
            await asyncio.sleep(0.01)

        async with state.lock:
            state.pending += 1
            try:
                return await self._process_unlocked(record)
            finally:
                state.pending -= 1

    async def _process_unlocked(self, record: IngestRecord) -> ProcessOutcome:
        received_at = record.received_at if record.received_at is not None else self._clock()
        if self._clock() - received_at > self._latency_budget:
            logger.warning(
                "etl_latency_budget_exceeded",
                extra={
                    "channel": record.channel,
                    "shop_key": record.shop_key,
                    "age_seconds": self._clock() - received_at,
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
                channel=record.channel, shop_key=record.shop_key, payload=payload
            )
        except (TypeError, ValueError) as exc:
            await self._send_dlq(record, error=str(exc), payload=payload)
            return ProcessOutcome.DLQ

        shop = await self._shops.get_by_tiktok_id(record.shop_key)
        if shop is None:
            await self._send_dlq(
                record,
                error=f"unknown shop tiktok_shop_id={record.shop_key}",
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
            entity_kind, kwargs = transform_for_channel(record.channel, payload)
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
                "channel": record.channel,
                "shop_id": str(shop.id),
                "entity_kind": entity_kind,
            },
        )
        return ProcessOutcome.PROCESSED

    async def _upsert(
        self, entity_kind: str, *, shop_id: Any, kwargs: dict[str, Any]
    ) -> None:
        if entity_kind == "order_item":
            kwargs["order_id"] = await self._resolve_order_id(
                shop_id, kwargs["tiktok_order_id"]
            )
        elif entity_kind == "return" and kwargs.get("tiktok_order_id"):
            order_pk = await self._lookup_order_id(shop_id, kwargs["tiktok_order_id"])
            kwargs["order_id"] = order_pk
            if order_pk is not None:
                kwargs["return_type"] = await self._derive_return_type(
                    shop_id=shop_id,
                    order_id=order_pk,
                    kwargs=kwargs,
                )

        repos: dict[str, _UpsertRepo] = {
            "order": self._orders,
            "order_item": self._order_items,
            "return": self._returns,
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

    async def _lookup_order_id(
        self, shop_id: Any, tiktok_order_id: str
    ) -> Any | None:
        stmt = select(Order.id).where(
            Order.shop_id == shop_id,
            Order.tiktok_order_id == tiktok_order_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_order_id(self, shop_id: Any, tiktok_order_id: str) -> Any:
        order_pk = await self._lookup_order_id(shop_id, tiktok_order_id)
        if order_pk is None:
            raise TransformError(f"parent order not found: {tiktok_order_id}")
        return order_pk

    async def _derive_return_type(
        self, *, shop_id: Any, order_id: Any, kwargs: dict[str, Any]
    ) -> str:
        current = kwargs.get("return_type") or "other"
        if current != "other":
            return str(current)

        returned_sku = kwargs.get("tiktok_sku_id")
        if not returned_sku:
            return str(current)

        stmt = select(OrderItem.tiktok_sku_id).where(
            OrderItem.shop_id == shop_id,
            OrderItem.order_id == order_id,
        )
        if kwargs.get("tiktok_product_id"):
            stmt = stmt.where(OrderItem.tiktok_product_id == kwargs["tiktok_product_id"])

        result = await self._session.execute(stmt)
        ordered_skus = {sku for sku in result.scalars().all() if sku}
        if ordered_skus and str(returned_sku) not in ordered_skus:
            return "item_swap"
        return str(current)

    async def _send_dlq(
        self,
        record: IngestRecord,
        *,
        error: str,
        payload: dict[str, Any] | None,
    ) -> None:
        envelope = {
            "original_channel": record.channel,
            "shop_key": record.shop_key,
            "error": error,
            "payload": payload,
            "raw": record.value.decode(errors="replace"),
        }
        logger.error(
            "etl_dlq",
            extra={
                "channel": record.channel,
                "shop_key": record.shop_key,
                "error": error,
            },
        )
        await self._dlq_handoff(
            DLQ_CHANNEL,
            record.shop_key,
            json.dumps(envelope).encode(),
        )
