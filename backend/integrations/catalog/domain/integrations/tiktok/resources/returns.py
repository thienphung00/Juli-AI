"""TikTok Shop Return/Refund resource — returns and cancellations search."""

from __future__ import annotations

from typing import Optional

from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
from backend.integrations.catalog.domain.integrations.tiktok.constants import (
    CANCELLATION_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from backend.integrations.catalog.domain.integrations.tiktok.resources import strip_nones


class ReturnsResource:
    """Search returns and buyer cancellations from TikTok Shop."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search_returns(
        self,
        *,
        return_status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "return_status": return_status,
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        params = strip_nones({
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        return self._client.post(RETURN_SEARCH_PATH, body=body, params=params)

    def search_returns_all(
        self,
        *,
        return_status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = strip_nones({
            "return_status": return_status,
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        return self._client.get_all_pages(
            path=RETURN_SEARCH_PATH,
            body=body,
            items_key="return_orders",
            page_size=page_size,
        )

    def search_cancellations(
        self,
        *,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        params = strip_nones({
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        return self._client.post(CANCELLATION_SEARCH_PATH, body=body, params=params)

    def search_cancellations_all(
        self,
        *,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = strip_nones({
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        return self._client.get_all_pages(
            path=CANCELLATION_SEARCH_PATH,
            body=body,
            items_key="cancellations",
            page_size=page_size,
        )
