"""TikTok Shop Livestreams resource — thin wrapper over TikTokClient.

Returns post-stream summaries only (no realtime in-stream telemetry).
Requires Affiliate scope approval.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.integrations.tiktok.client import TikTokClient
from src.integrations.tiktok.resources import strip_nones


class LivestreamsResource:
    """Search and fetch livestream session summaries from TikTok Affiliate API."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list(
        self,
        *,
        creator_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "creator_id": creator_id,
            "start_time": start_time,
            "end_time": end_time,
            "page_size": page_size,
            "page_token": page_token,
        })
        return self._client.post("/api/affiliate/livestreams/search", body=body)

    def list_all(
        self,
        *,
        creator_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        body = strip_nones({
            "creator_id": creator_id,
            "start_time": start_time,
            "end_time": end_time,
        })
        return self._client.get_all_pages(
            path="/api/affiliate/livestreams/search",
            body=body,
            items_key="livestreams",
            page_size=page_size,
        )

    def get(self, livestream_id: str) -> dict:
        return self._client.get(
            "/api/affiliate/livestreams/details",
            params={"livestream_id": livestream_id},
        )
