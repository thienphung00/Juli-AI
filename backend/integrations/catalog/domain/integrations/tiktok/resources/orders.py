"""TikTok Shop Orders resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Optional

from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
from backend.integrations.catalog.domain.integrations.tiktok.constants import (
    ORDER_DETAIL_PATH,
    ORDER_SEARCH_PATH,
)
from backend.integrations.catalog.domain.integrations.tiktok.resources import strip_nones
from backend.integrations.catalog.domain.integrations.tiktok.schemas import OrdersSearchData, coerce_model


class OrdersResource:
    """Search, paginate, and fetch order details from TikTok Shop."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({
            "order_status": status,
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        params = strip_nones({
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        parsed = coerce_model(
            OrdersSearchData,
            self._client.post(
                ORDER_SEARCH_PATH,
                body=body,
                params=params,
                response_model=OrdersSearchData,
            ),
        )
        return parsed.model_dump()

    def search_all(
        self,
        *,
        status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = strip_nones({
            "order_status": status,
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
        })
        return self._client.get_all_pages(
            path=ORDER_SEARCH_PATH,
            body=body,
            items_key="orders",
            page_size=page_size,
        )

    def get_details(self, order_ids: list[str]) -> dict:
        return self._client.get(
            ORDER_DETAIL_PATH,
            params={"ids": ",".join(order_ids)},
        )
