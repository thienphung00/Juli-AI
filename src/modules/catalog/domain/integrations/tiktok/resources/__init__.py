"""TikTok Shop resource modules — thin wrappers over TikTokClient."""

from __future__ import annotations

from typing import Any


def strip_nones(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values from a dict before sending to the API."""
    return {k: v for k, v in d.items() if v is not None}


from src.modules.catalog.domain.integrations.tiktok.resources.authorization import (  # noqa: E402
    AuthorizationResource,
)
from src.modules.catalog.domain.integrations.tiktok.resources.orders import OrdersResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.products import ProductsResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.returns import ReturnsResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.inventory import InventoryResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.creators import CreatorsResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.livestreams import LivestreamsResource  # noqa: E402
from src.modules.catalog.domain.integrations.tiktok.resources.settlements import SettlementsResource  # noqa: E402

__all__ = [
    "strip_nones",
    "AuthorizationResource",
    "OrdersResource",
    "ProductsResource",
    "ReturnsResource",
    "InventoryResource",
    "CreatorsResource",
    "LivestreamsResource",
    "SettlementsResource",
]
