"""Ingest channel names routed through the ETL pipeline."""

from __future__ import annotations

DLQ_CHANNEL = "tiktok.events.dlq"

RAW_CHANNELS: frozenset[str] = frozenset(
    {
        "tiktok.orders.raw",
        "tiktok.order_items.raw",
        "tiktok.returns.raw",
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

# Deprecated aliases (channel names were historically called "topics").
DLQ_TOPIC = DLQ_CHANNEL
RAW_TOPICS = RAW_CHANNELS
