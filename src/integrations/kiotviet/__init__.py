"""KiotViet API integration — public surface.

Usage::

    from src.integrations.kiotviet import KiotViet

    kv = KiotViet()                       # reads env vars for credentials
    products = kv.products.list_all()
    order    = kv.orders.get_by_id(1001)
"""

from __future__ import annotations

import os

from .auth import TokenManager
from .client import KiotVietClient
from .exceptions import (
    AuthenticationError,
    ForbiddenError,
    KiotVietError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .resources.customers import CustomersResource
from .resources.inventory import InventoryResource
from .resources.orders import OrdersResource
from .resources.products import ProductsResource


class KiotViet:
    """Facade that wires auth, client, and resource modules together.

    Parameters can be supplied directly or via environment variables:
      KIOTVIET_CLIENT_ID, KIOTVIET_CLIENT_SECRET, KIOTVIET_RETAILER
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        retailer: str | None = None,
        base_url: str = "https://public.kiotapi.com",
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self._token_manager = TokenManager(
            client_id=client_id,
            client_secret=client_secret,
        )
        self._client = KiotVietClient(
            token_manager=self._token_manager,
            retailer=retailer,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

        self.products = ProductsResource(self._client)
        self.orders = OrdersResource(self._client)
        self.customers = CustomersResource(self._client)
        self.inventory = InventoryResource(self._client)

    @property
    def client(self) -> KiotVietClient:
        """Escape hatch for custom / low-level requests."""
        return self._client


__all__ = [
    "KiotViet",
    "KiotVietClient",
    "TokenManager",
    "KiotVietError",
    "AuthenticationError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
    "ProductsResource",
    "OrdersResource",
    "CustomersResource",
    "InventoryResource",
]
