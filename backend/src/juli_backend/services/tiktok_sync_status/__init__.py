"""Per-shop TikTok sync status for the seller app (P101 W2 B-5).

One read: how far the 90-day backfill is, which day the data runs to, whether
yesterday is late, and the connection state derived from the credential and the
ingestion state -- no new table, no write. ``GET /v1/shops/me/sync-status``
serves it; the app header turns it into one status line.
"""

from juli_backend.services.tiktok_sync_status.status import (
    BACKFILL_TARGET_DAYS,
    DATA_DUE_HOUR_VN,
    ShopSyncStatus,
    build_sync_status,
    shop_sync_status,
)

__all__ = [
    "BACKFILL_TARGET_DAYS",
    "DATA_DUE_HOUR_VN",
    "ShopSyncStatus",
    "build_sync_status",
    "shop_sync_status",
]
