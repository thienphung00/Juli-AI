"""Append-only writers for the bronze raw-payload tables (ADR-046, #605, #880).

Bronze rows are the vendor payload exactly as received, plus the identifiers
needed to find it again. There is no update path -- a redelivery is a new row,
and the silver layer's idempotent upsert is what de-duplicates.

All four tables share the same column core; each adds one or two vendor ids.
:class:`BronzeRawPayloadsRepo` holds the shared behaviour, and a subclass is
nothing more than *which model* and *which extra ids* -- adding a fifth bronze
table is a three-line class.

One-writer rule: ``append_batch`` may only be called from ``services.etl`` (and
``services.cdp_batch.partition_checkpoints`` for orders).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, TypeVar

from juli_backend.models.models import (
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
)
from juli_backend.repositories._base import SessionRepo

RowT = TypeVar("RowT")

# Present in every bronze record. ``received_at`` defaults to now when absent.
_REQUIRED_FIELDS = ("shop_id", "ingest_source", "payload")


class BronzeRawPayloadsRepo(SessionRepo, Generic[RowT]):
    """Batched append writer. Subclasses set ``_model`` and ``_vendor_id_fields``."""

    _model: ClassVar[type[Any]]
    _vendor_id_fields: ClassVar[tuple[str, ...]] = ()

    async def append_batch(self, records: Sequence[Mapping[str, Any]]) -> list[RowT]:
        """Insert one row per record and return the rows (ids populated after flush)."""
        if not records:
            return []
        rows = [self._row_from_record(record) for record in records]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    def _row_from_record(self, record: Mapping[str, Any]) -> RowT:
        columns: dict[str, Any] = {name: record[name] for name in _REQUIRED_FIELDS}
        columns["received_at"] = record.get("received_at") or datetime.now(UTC)
        columns["source_event_id"] = record.get("source_event_id")
        for name in self._vendor_id_fields:
            columns[name] = record.get(name)
        return self._model(**columns)


class BronzeOrderRawPayloadsRepo(BronzeRawPayloadsRepo[BronzeOrderRawPayload]):
    """``bronze.order_raw_payloads`` (#605)."""

    _model = BronzeOrderRawPayload
    _vendor_id_fields = ("tiktok_order_id",)


class BronzeReturnRawPayloadsRepo(BronzeRawPayloadsRepo[BronzeReturnRawPayload]):
    """``bronze.return_raw_payloads`` (#605)."""

    _model = BronzeReturnRawPayload
    _vendor_id_fields = ("tiktok_return_id", "tiktok_order_id")


class BronzeCtorPerformanceRawPayloadsRepo(BronzeRawPayloadsRepo[BronzeCtorPerformanceRawPayload]):
    """``bronze.ctor_performance_raw_payloads`` (#880)."""

    _model = BronzeCtorPerformanceRawPayload
    _vendor_id_fields = ("tiktok_product_id",)


class BronzeLiveHoursRawPayloadsRepo(BronzeRawPayloadsRepo[BronzeLiveHoursRawPayload]):
    """``bronze.live_hours_raw_payloads`` (#880)."""

    _model = BronzeLiveHoursRawPayload
    _vendor_id_fields = ("tiktok_live_id",)


__all__ = [
    "BronzeCtorPerformanceRawPayloadsRepo",
    "BronzeLiveHoursRawPayloadsRepo",
    "BronzeOrderRawPayloadsRepo",
    "BronzeRawPayloadsRepo",
    "BronzeReturnRawPayloadsRepo",
]
