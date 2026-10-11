"""Per-shop ingestion bootstrap state (``shop_ingestion_state``).

Thin by the package contract: it reads and writes one row per shop and never
commits. What a transition *means* (and the log event announcing it) lives in
``workers/services/polling/ingestion.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from juli_backend.models.ingestion import BOOTSTRAP_NOT_STARTED, ShopIngestionState
from juli_backend.repositories._base import SessionRepo, utc_now_naive

#: ``shop_ingestion_state.last_error`` is VARCHAR(500).
_LAST_ERROR_LIMIT = 500

#: Columns that record the FIRST time a transition happened. ``stamp_once``
#: refuses to overwrite them, so a re-run never moves a latency measurement.
ONCE_COLUMNS: frozenset[str] = frozenset(
    {
        "connect_committed_at",
        "bootstrap_enqueued_at",
        "fast_started_at",
        "fast_done_at",
        "first_card_at",
        "history_started_at",
        "history_done_at",
        "quick_scan_started_at",
        "quick_scan_done_at",
    }
)


class ShopIngestionStateRepo(SessionRepo):
    """One ``shop_ingestion_state`` row per shop, created on first touch by ``ensure``."""

    async def find(self, shop_id: uuid.UUID) -> ShopIngestionState | None:
        return await self._one_or_none(
            select(ShopIngestionState).where(ShopIngestionState.shop_id == shop_id)
        )

    async def ensure(self, shop_id: uuid.UUID) -> ShopIngestionState:
        state = await self.find(shop_id)
        if state is not None:
            return state
        state = ShopIngestionState(
            shop_id=shop_id,
            status=BOOTSTRAP_NOT_STARTED,
            history_chunks_done=0,
            history_empty_chunks=0,
        )
        return await self._add(state)

    async def update(self, shop_id: uuid.UUID, **values: Any) -> ShopIngestionState:
        """Set columns on the shop's row (creating it), then flush."""
        state = await self.ensure(shop_id)
        for name, value in values.items():
            if name == "last_error" and value is not None:
                value = str(value)[:_LAST_ERROR_LIMIT]
            setattr(state, name, value)
        await self._session.flush()
        return state

    async def stamp_once(
        self,
        shop_id: uuid.UUID,
        column: str,
        at: datetime | None = None,
        **values: Any,
    ) -> tuple[ShopIngestionState, bool]:
        """Write ``column`` only if it is still NULL; always apply ``values``.

        Returns the row and whether ``column`` was written by this call.
        """
        if column not in ONCE_COLUMNS:
            raise ValueError(f"{column!r} is not a once-only timestamp column")
        state = await self.ensure(shop_id)
        written = False
        if getattr(state, column) is None:
            setattr(state, column, at or utc_now_naive())
            written = True
        for name, value in values.items():
            if name == "last_error" and value is not None:
                value = str(value)[:_LAST_ERROR_LIMIT]
            setattr(state, name, value)
        await self._session.flush()
        return state, written

    async def record_history_chunk(
        self,
        shop_id: uuid.UUID,
        *,
        earliest_date: date,
        had_data: bool,
    ) -> ShopIngestionState:
        """Advance the history cursor past one completed chunk."""
        state = await self.ensure(shop_id)
        state.history_earliest_date = earliest_date
        state.history_chunks_done = (state.history_chunks_done or 0) + 1
        state.history_empty_chunks = 0 if had_data else (state.history_empty_chunks or 0) + 1
        await self._session.flush()
        return state


__all__ = ["ONCE_COLUMNS", "ShopIngestionStateRepo"]
