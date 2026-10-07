"""TikTok Shop Orders resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ORDER_DETAIL_PATH,
    ORDER_SEARCH_PATH,
)
from juli_backend.integrations.tiktok.resources import strip_nones
from juli_backend.integrations.tiktok.schemas import OrdersSearchData, coerce_model


def _search_body(
    status: str | None,
    update_time_from: int | None,
    update_time_to: int | None,
    create_time_from: int | None,
    create_time_to: int | None,
) -> dict:
    """Order search filters; ``create_time_*`` and ``update_time_*`` are independent (half-open)."""
    return strip_nones(
        {
            "order_status": status,
            "update_time_ge": update_time_from,
            "update_time_lt": update_time_to,
            "create_time_ge": create_time_from,
            "create_time_lt": create_time_to,
        }
    )


class OrdersResource:
    """Search, paginate, and fetch order details from TikTok Shop."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        body = _search_body(
            status, update_time_from, update_time_to, create_time_from, create_time_to
        )
        params = strip_nones(
            {
                "page_size": str(page_size) if page_size is not None else None,
                "page_token": page_token,
            }
        )
        parsed = coerce_model(
            OrdersSearchData,
            self._client.post(
                ORDER_SEARCH_PATH,
                body=body,
                params=params,
                response_model=OrdersSearchData,
                # A search is a read: transient Partner failures retry with backoff.
                retry_transient=True,
            ),
        )
        return parsed.model_dump()

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = _search_body(
            status, update_time_from, update_time_to, create_time_from, create_time_to
        )
        return self._client.get_all_pages(
            path=ORDER_SEARCH_PATH,
            body=body,
            items_key="orders",
            page_size=page_size,
            retry_transient=True,
        )

    def get_details(self, order_ids: list[str]) -> dict:
        parsed = coerce_model(
            OrdersSearchData,
            self._client.get(
                ORDER_DETAIL_PATH,
                params={"ids": ",".join(order_ids)},
                response_model=OrdersSearchData,
            ),
        )
        return parsed.model_dump()
