"""TikTok Shop Promotion resource — activity lifecycle (Layer 2 sandbox write).

Verified contracts: contract-collection.md §A-25 (Get Activity), §B-5–B-8. The two
search reads (activities, coupons) are read-only and allowlisted for production.
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PROMOTION_ACTIVITIES_SEARCH_PATH,
    PROMOTION_COUPONS_SEARCH_PATH,
    PROMOTION_CREATE_PATH,
    promotion_activity_path,
    promotion_activity_products_path,
    promotion_deactivate_path,
)
from juli_backend.integrations.tiktok.resources import strip_nones

#: Both searches accept at most 100 rows per page.
SEARCH_MAX_PAGE_SIZE = 100


class PromotionResource:
    """Create, read, update, and deactivate promotion activities."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def get_activity(self, activity_id: str) -> dict:
        """Fetch activity details (contract-collection.md §A-25)."""
        return self._client.get(promotion_activity_path(activity_id))

    def search_activities(
        self,
        *,
        status: str | None = None,
        activity_type: str | None = None,
        activity_title: str | None = None,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict:
        """Search Activities, one page (read-only POST; ``page_size`` is in ``[1, 100]``).

        Unverified live as of ADR-090 d.2; ADR-106 amendment 4 is the attempt.
        The response lists activities without their products: fetch those with
        :meth:`get_activity`.
        """
        if not 1 <= page_size <= SEARCH_MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be 1..{SEARCH_MAX_PAGE_SIZE}")
        body = strip_nones(
            {
                "status": status,
                "activity_type": activity_type,
                "activity_title": activity_title,
                "page_size": page_size,
                "page_token": page_token,
            }
        )
        return self._client.post(PROMOTION_ACTIVITIES_SEARCH_PATH, body=body, retry_transient=True)

    def search_activities_all(
        self,
        *,
        status: str | None = None,
        activity_type: str | None = None,
        page_size: int = SEARCH_MAX_PAGE_SIZE,
        max_pages: int = 20,
    ) -> list[dict]:
        """Every activity matching the filters, following ``next_page_token`` in the body."""
        activities: list[dict] = []
        token: str | None = None
        for _ in range(max_pages):
            page = self.search_activities(
                status=status, activity_type=activity_type, page_size=page_size, page_token=token
            )
            activities.extend(a for a in page.get("activities") or [] if isinstance(a, dict))
            token = str(page.get("next_page_token") or "") or None
            if token is None:
                break
        return activities

    def search_coupons(
        self,
        *,
        status: list[str] | None = None,
        display_type: list[str] | None = None,
        title_keyword: str | None = None,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict:
        """Search Coupons, one page (read-only POST; paging is in the query string)."""
        if not 1 <= page_size <= SEARCH_MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be 1..{SEARCH_MAX_PAGE_SIZE}")
        params = strip_nones({"page_size": str(page_size), "page_token": page_token})
        body = strip_nones(
            {"status": status, "display_type": display_type, "title_keyword": title_keyword}
        )
        return self._client.post(
            PROMOTION_COUPONS_SEARCH_PATH, body=body, params=params, retry_transient=True
        )

    def search_coupons_all(
        self,
        *,
        status: list[str] | None = None,
        display_type: list[str] | None = None,
        page_size: int = SEARCH_MAX_PAGE_SIZE,
    ) -> list[dict]:
        """Every coupon matching the filters, via the client's budgeted paginator."""
        body = strip_nones({"status": status, "display_type": display_type})
        return self._client.get_all_pages(
            PROMOTION_COUPONS_SEARCH_PATH,
            body=body,
            items_key="coupons",
            page_size=page_size,
            retry_transient=True,
        )

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
