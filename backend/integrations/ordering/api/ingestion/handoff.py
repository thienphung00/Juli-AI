"""Bridge webhook/polling producers to ``EtlConsumer`` (validation → ETL → Postgres)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.integrations.ordering.use_cases.etl.consumer import EtlConsumer

HandoffFn = Callable[[str, str, bytes], Awaitable[None]]
DlqHandoffFn = HandoffFn

# Deprecated alias.
PublishFn = HandoffFn


def make_etl_handoff(
    consumer: EtlConsumer,
    *,
    clock: Callable[[], float] = time.time,
) -> HandoffFn:
    """Return a handoff callable that ingests each validated payload through ETL."""
    from backend.integrations.ordering.use_cases.etl.record import IngestRecord

    async def handoff(channel: str, shop_key: str, payload: bytes) -> None:
        await consumer.ingest(
            IngestRecord(
                channel=channel,
                shop_key=shop_key,
                value=payload,
                received_at=clock(),
            )
        )

    return handoff
