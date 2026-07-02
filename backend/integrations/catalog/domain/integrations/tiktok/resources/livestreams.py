"""TikTok Shop Livestreams resource — post-stream creator content summaries.

Uses Affiliate Seller ``creator_content_details`` (official Partner API).
Legacy ``/api/affiliate/livestreams/*`` paths are not production surfaces.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
from backend.integrations.catalog.domain.integrations.tiktok.constants import CREATOR_CONTENT_DETAILS_PATH
from backend.integrations.catalog.domain.integrations.tiktok.mapping import normalize_livestream
from backend.integrations.catalog.domain.integrations.tiktok.resources import strip_nones
from backend.integrations.catalog.domain.integrations.tiktok.schemas import (
    CreatorContentDetail,
    CreatorContentSearchData,
    coerce_model,
    validate_items,
)


class LivestreamsResource:
    """List post-stream creator content sessions (live/video) from Affiliate API."""

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
    ) -> dict[str, Any]:
        params = strip_nones({
            "creator_id": creator_id,
            "start_time": str(start_time) if start_time is not None else None,
            "end_time": str(end_time) if end_time is not None else None,
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        parsed = coerce_model(
            CreatorContentSearchData,
            self._client.get(
                CREATOR_CONTENT_DETAILS_PATH,
                params=params,
                response_model=CreatorContentSearchData,
            ),
        )
        return parsed.model_dump()

    def list_all(
        self,
        *,
        creator_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        params = strip_nones({
            "creator_id": creator_id,
            "start_time": str(start_time) if start_time is not None else None,
            "end_time": str(end_time) if end_time is not None else None,
        })
        raw_items = self._client.get_all_pages_get(
            CREATOR_CONTENT_DETAILS_PATH,
            params=params,
            items_key="creator_content_details",
            page_size=page_size,
        )
        contents = validate_items(CreatorContentDetail, raw_items)
        return [normalize_livestream(c.model_dump()) for c in contents]

    def get(self, livestream_id: str) -> dict[str, Any]:
        """Fetch a single content session by ``content_id`` / ``room_id`` filter."""
        params = strip_nones({
            "content_id": livestream_id,
            "room_id": livestream_id,
        })
        parsed = coerce_model(
            CreatorContentSearchData,
            self._client.get(
                CREATOR_CONTENT_DETAILS_PATH,
                params=params,
                response_model=CreatorContentSearchData,
            ),
        )
        for item in parsed.creator_content_details:
            dumped = item.model_dump()
            normalized = normalize_livestream(dumped)
            if normalized.get("livestream_id") == livestream_id:
                return normalized
        if parsed.creator_content_details:
            return normalize_livestream(parsed.creator_content_details[0].model_dump())
        return {"livestream_id": livestream_id}
