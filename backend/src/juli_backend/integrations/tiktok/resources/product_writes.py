"""Sandbox-only product write resources — create and partial edit."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import PRODUCT_CREATE_PATH, product_detail_path
from juli_backend.integrations.tiktok.schemas import CreateProductData, coerce_model


class ProductWriteResource:
    """Publish and edit products via verified Layer 2 sandbox write paths."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        parsed = coerce_model(
            CreateProductData,
            self._client.post(
                PRODUCT_CREATE_PATH,
                body=body,
                response_model=CreateProductData,
            ),
        )
        return parsed.model_dump()

    def edit(self, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.put(product_detail_path(product_id), body=body)
