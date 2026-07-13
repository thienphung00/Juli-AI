"""TikTok Shop Promotion resource — activity lifecycle (Layer 2 sandbox write).

Verified contracts: contract-collection.md §A-25 (Get Activity), §B-5–B-8.
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PROMOTION_CREATE_PATH,
    promotion_activity_path,
    promotion_activity_products_path,
    promotion_deactivate_path,
)


class PromotionResource:
    """Create, read, update, and deactivate promotion activities."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def get_activity(self, activity_id: str) -> dict:
        """Fetch activity details (contract-collection.md §A-25)."""
        return self._client.get(promotion_activity_path(activity_id))

    def create_activity(self, *, body: dict[str, Any]) -> dict:
        """Create a promotion activity (contract-collection.md §B-5)."""
        return self._client.post(PROMOTION_CREATE_PATH, body=body)

    def update_activity(self, *, activity_id: str, body: dict[str, Any]) -> dict:
        """Update activity metadata/schedule (contract-collection.md §B-6)."""
        return self._client.put(promotion_activity_path(activity_id), body=body)

    def update_activity_products(
        self,
        *,
        activity_id: str,
        body: dict[str, Any],
    ) -> dict:
        """Attach or update product/SKU prices (contract-collection.md §B-7)."""
        return self._client.put(promotion_activity_products_path(activity_id), body=body)

    def deactivate(self, *, activity_id: str) -> dict:
        """Deactivate an activity (contract-collection.md §B-8)."""
        return self._client.post(promotion_deactivate_path(activity_id), body={})
