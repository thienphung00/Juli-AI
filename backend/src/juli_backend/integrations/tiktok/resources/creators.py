"""TikTok Shop Creators resource — Affiliate Seller marketplace API."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    MARKETPLACE_CREATORS_SEARCH_PATH,
    marketplace_creator_path,
)
from juli_backend.integrations.tiktok.mapping import normalize_creator
from juli_backend.integrations.tiktok.resources import strip_nones
from juli_backend.integrations.tiktok.schemas import (
    MarketplaceCreator,
    MarketplaceCreatorsSearchData,
    coerce_model,
    validate_items,
)


class CreatorsResource:
    """Search and fetch marketplace creators from TikTok Affiliate Seller API."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        params = strip_nones({
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        parsed = coerce_model(
            MarketplaceCreatorsSearchData,
            self._client.post(
                MARKETPLACE_CREATORS_SEARCH_PATH,
                body={},
                params=params,
                response_model=MarketplaceCreatorsSearchData,
            ),
        )
        return parsed.model_dump()

    def list_all(self, *, page_size: int = 50) -> list[dict[str, Any]]:
        raw_items = self._client.get_all_pages(
            path=MARKETPLACE_CREATORS_SEARCH_PATH,
            body={},
            items_key="marketplace_creators",
            page_size=page_size,
        )
        creators = validate_items(MarketplaceCreator, raw_items)
        return [normalize_creator(c.model_dump()) for c in creators]

    def get(self, creator_id: str) -> dict[str, Any]:
        data = self._client.get(marketplace_creator_path(creator_id))
        assert isinstance(data, dict)
        creator = MarketplaceCreator.model_validate(data)
        return normalize_creator(creator.model_dump())
