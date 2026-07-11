"""Fulfillment and supply-chain write operations — thin wrapper over TikTokClient.

Layer 2 sandbox write paths per contract-collection.md §29-42 (write subset).
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    fulfillment_batch_ship_path,
    fulfillment_combine_packages_path,
    fulfillment_ship_package_path,
    fulfillment_split_order_path,
    fulfillment_uncombine_package_path,
    supply_chain_confirm_shipment_path,
)


class FulfillmentResource:
    """Combine, ship, split, uncombine packages and confirm shipment."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def combine_packages(self, *, body: dict[str, Any]) -> dict:
        return self._client.post(fulfillment_combine_packages_path(), body=body)

    def ship_package(
        self,
        *,
        package_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict:
        return self._client.post(
            fulfillment_ship_package_path(package_id),
            body=body or {},
        )

    def batch_ship_packages(self, *, body: dict[str, Any]) -> dict:
        return self._client.post(fulfillment_batch_ship_path(), body=body)

    def split_order(self, *, order_id: str, body: dict[str, Any]) -> dict:
        return self._client.post(fulfillment_split_order_path(order_id), body=body)

    def uncombine_package(
        self,
        *,
        package_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict:
        return self._client.post(
            fulfillment_uncombine_package_path(package_id),
            body=body or {},
        )

    def confirm_shipment(self, *, body: dict[str, Any]) -> dict:
        """Confirm package shipment via Supply Chain API (contract-collection.md §39)."""
        return self._client.post(supply_chain_confirm_shipment_path(), body=body)
