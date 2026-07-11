"""Sandbox-only fulfillment write resources — ship and package operations."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    fulfillment_batch_ship_path,
    fulfillment_package_detail_path,
    fulfillment_package_ship_path,
)


class FulfillmentWriteResource:
    """Ship packages and related sandbox write-validation operations."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def ship_package(
        self,
        package_id: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._client.post(
            fulfillment_package_ship_path(package_id),
            body=body or {},
        )

    def batch_ship_packages(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.post(fulfillment_batch_ship_path(), body=body)

    def get_package_detail(self, package_id: str) -> dict[str, Any]:
        """Supporting read used during sandbox fulfillment validation flows."""
        return self._client.get(fulfillment_package_detail_path(package_id))
