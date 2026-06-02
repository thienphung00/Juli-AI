"""TikTok Shop Settlements resource — thin wrapper over TikTokClient.

Settlement values may be pending for 7–14 days before confirming;
update_time is the reconciliation key.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.modules.catalog.domain.integrations.tiktok.client import TikTokClient
from src.modules.catalog.domain.integrations.tiktok.resources import strip_nones


class SettlementsResource:
    """Search settlements with date-range filtering from TikTok Finance API."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list(
        self,
        *,
        settle_time_from: Optional[int] = None,
        settle_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "settle_time_from": settle_time_from,
            "settle_time_to": settle_time_to,
            "page_size": page_size,
            "page_token": page_token,
        })
        return self._client.post("/api/finance/settlements/search", body=body)

    def list_all(
        self,
        *,
        settle_time_from: Optional[int] = None,
        settle_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        body = strip_nones({
            "settle_time_from": settle_time_from,
            "settle_time_to": settle_time_to,
        })
        return self._client.get_all_pages(
            path="/api/finance/settlements/search",
            body=body,
            items_key="settlements",
            page_size=page_size,
        )
