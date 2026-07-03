"""Temporary TikTok connection verification for App Review debugging."""

from __future__ import annotations

import asyncio
import logging
import os

from backend.integrations.catalog.domain.integrations.tiktok.auth import (
    DEFAULT_OPEN_API_BASE_URL,
)
from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
from backend.integrations.catalog.domain.integrations.tiktok.exceptions import (
    TikTokAPIError,
)
from backend.integrations.catalog.domain.integrations.tiktok.resources.authorization import (
    AuthorizationResource,
)

logger = logging.getLogger(__name__)


class TikTokVerifyConnectionService:
    """Call TikTok authorized-shops using a stored or debug access token."""

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        base_url: str | None = None,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_url = (base_url or DEFAULT_OPEN_API_BASE_URL).rstrip("/")

    async def verify(self, access_token: str) -> dict:
        client = TikTokClient(
            app_key=self._app_key,
            app_secret=self._app_secret,
            access_token=access_token,
            base_url=self._base_url,
        )
        auth = AuthorizationResource(client)

        try:
            shops = await asyncio.to_thread(auth.list_all_shops)
        except TikTokAPIError as exc:
            logger.warning(
                "tiktok_verify_connection_failed",
                extra={
                    "tiktok_error_code": exc.code,
                    "request_id": exc.request_id,
                },
            )
            return {
                "connected": False,
                "error": "TikTok authorized shops request failed",
            }

        if not shops:
            return {
                "connected": False,
                "error": "No authorized shops returned for this token",
            }

        shop = shops[0]
        return {
            "connected": True,
            "shop_id": shop.get("id"),
            "shop_name": shop.get("name"),
            "market": shop.get("region"),
        }


def tiktok_debug_enabled() -> bool:
    return os.environ.get("ENABLE_TIKTOK_DEBUG", "").strip() == "1"
