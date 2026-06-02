"""Validated ingest payloads handed from webhook/polling to ETL."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestRecord:
    """One validated payload on its way to ``EtlConsumer.ingest``."""

    channel: str
    shop_key: str
    value: bytes
    received_at: float | None = None


# Backward-compatible alias (pre-architecture-evolution name).
KafkaRecord = IngestRecord
