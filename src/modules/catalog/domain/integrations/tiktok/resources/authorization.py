"""TikTok Shop Authorization resource — authorized shops and shop_cipher."""

from __future__ import annotations

from src.modules.catalog.domain.integrations.tiktok.client import TikTokClient
from src.modules.catalog.domain.integrations.tiktok.constants import AUTHORIZED_SHOPS_PATH
from src.modules.catalog.domain.integrations.tiktok.schemas import AuthorizedShopsData, coerce_model


class AuthorizationResource:
    """Fetch authorized shops for the current seller token."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list_shops(self) -> dict:
        """Return authorized shops (``shops[]`` with ``id`` and ``cipher``)."""
        parsed = coerce_model(
            AuthorizedShopsData,
            self._client.get(
                AUTHORIZED_SHOPS_PATH,
                response_model=AuthorizedShopsData,
            ),
        )
        return parsed.model_dump()

    def list_all_shops(self) -> list[dict]:
        parsed = coerce_model(
            AuthorizedShopsData,
            self._client.get(
                AUTHORIZED_SHOPS_PATH,
                response_model=AuthorizedShopsData,
            ),
        )
        return [shop.model_dump(exclude_none=True) for shop in parsed.shops]
