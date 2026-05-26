"""TikTok Shop Creators resource — thin wrapper over TikTokClient.

Requires separate per-seller Affiliate scope approval.
"""

from __future__ import annotations

from typing import Optional

from src.integrations.tiktok.client import TikTokClient
from src.integrations.tiktok.resources import strip_nones


class CreatorsResource:
    """Search, paginate, and fetch creator details from TikTok Affiliate API."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list(
        self,
        *,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "page_size": page_size,
            "page_token": page_token,
        })
        return self._client.post("/api/affiliate/creators/search", body=body)

    def list_all(self, *, page_size: int = 50) -> list[dict]:
        return self._client.get_all_pages(
            path="/api/affiliate/creators/search",
            body={},
            items_key="creators",
            page_size=page_size,
        )

    def get(self, creator_id: str) -> dict:
        return self._client.get(
            "/api/affiliate/creators/details",
            params={"creator_id": creator_id},
        )
