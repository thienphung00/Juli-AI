"""Kafka topic names consumed by the ETL pipeline."""

from __future__ import annotations

DLQ_TOPIC = "tiktok.events.dlq"

RAW_TOPICS: frozenset[str] = frozenset(
    {
        "tiktok.orders.raw",
        "tiktok.products.raw",
        "tiktok.inventory.raw",
        "tiktok.creators.raw",
        "tiktok.livestreams.raw",
        "tiktok.settlements.raw",
        "livestream-events",
        "creator-events",
        "settlement-events",
    }
)
