"""ProcessedEventsRepo — ETL ingest idempotency claims."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.etl.persistence.ingest.model import ProcessedEvent


class ProcessedEventsRepo:
    """Tracks consumed ingest event IDs for idempotent ETL (#32)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, *, event_id: str, shop_id: uuid.UUID) -> bool:
        """Insert *event_id* if unseen. Returns False when already processed."""
        stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        result = await self._session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return False
        self._session.add(ProcessedEvent(event_id=event_id, shop_id=shop_id))
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError:
            return False
        return True
