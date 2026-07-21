"""Ingest channel names routed through the ETL pipeline."""

from __future__ import annotations

DLQ_CHANNEL = "tiktok.events.dlq"

ANALYTICS_CHANNELS: frozenset[str] = frozenset(
    {
        "tiktok.analytics.shop.raw",
        "tiktok.analytics.product.raw",
        "tiktok.analytics.sku.raw",
        "tiktok.analytics.live.raw",
    }
)

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
) | ANALYTICS_CHANNELS

# Deprecated aliases (channel names were historically called "topics").
DLQ_TOPIC = DLQ_CHANNEL
RAW_TOPICS = RAW_CHANNELS
