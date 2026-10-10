"""What the analysis needs to know about the product (fast track P15).

The product's name from Juli's own ``products`` row; its brand, listing images
(the reference for "product on screen") and TikTok SEO words from the shop's
read-only TikTok resources (``get_details`` / ``get_seo_words``). Every TikTok
read is best-effort: a failure leaves the field empty and the analysis goes on
(without images, product-on-screen is judged from the name only).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import InventoryItem, Product
from juli_backend.services.content_analysis.pipeline import ProductInfo

logger = logging.getLogger(__name__)

MAX_IMAGES = 2


def _data(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        return payload["data"]
    return payload if isinstance(payload, Mapping) else {}


def images_of(detail: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for image in detail.get("main_images") or []:
        if not isinstance(image, Mapping):
            continue
        urls = image.get("urls") or image.get("thumb_urls") or []
        url = next((u for u in urls if isinstance(u, str) and u.startswith("https://")), None)
        if url:
            out.append(url)
        if len(out) >= MAX_IMAGES:
            break
    return out


def brand_of(detail: Mapping[str, Any]) -> str | None:
    brand = detail.get("brand")
    if isinstance(brand, Mapping):
        name = str(brand.get("name") or "").strip()
        return name or None
    return None


def seo_words_of(payload: Any, product_id: str) -> list[str]:
    for product in _data(payload).get("products") or []:
        if isinstance(product, Mapping) and str(product.get("id")) == product_id:
            words = product.get("seo_words") or []
            return [
                (w if isinstance(w, str) else str(w.get("word") or "")).strip()
                for w in words
                if isinstance(w, str | Mapping)
            ][:10]
    return []


class TikTokProductReader:
    """Production ``ProductReader``: DB row + the shop's guarded read resources."""

    def __init__(self, resources_for: Callable[..., Any] | None = None) -> None:
        self._resources_for = resources_for

    async def _resources(self, session: AsyncSession, shop_id: uuid.UUID) -> Any:
        if self._resources_for is not None:
            return await self._resources_for(session, shop_id)
        from juli_backend.services.agent import composition

        return await composition.build_read_resources(session, shop_id=shop_id)

    async def read(
        self, session: AsyncSession, shop_id: uuid.UUID, product_id: str | None
    ) -> ProductInfo:
        info = ProductInfo()
        if not product_id:
            return info
        row = (
            await session.execute(
                select(Product).where(
                    Product.shop_id == shop_id, Product.tiktok_product_id == product_id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            info.name = (row.title or row.name or "").strip() or None
        sku = (
            await session.execute(
                select(InventoryItem.seller_sku)
                .where(
                    InventoryItem.shop_id == shop_id,
                    InventoryItem.tiktok_product_id == product_id,
                    InventoryItem.seller_sku.isnot(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        info.label = str(sku).strip() if sku else None
        try:
            resources = await self._resources(session, shop_id)
        except Exception as exc:  # no credential, sandbox shop, …: analyse without
            logger.info(
                "content_analysis_product_read_skipped",
                extra={"shop_id": str(shop_id), "error": type(exc).__name__},
            )
            return info
        try:
            detail = _data(await asyncio.to_thread(resources.products.get_details, product_id))
            info.name = info.name or (str(detail.get("title") or "").strip() or None)
            info.brand = brand_of(detail)
            info.images = images_of(detail)
        except Exception as exc:
            logger.info(
                "content_analysis_product_detail_failed",
                extra={"shop_id": str(shop_id), "error": type(exc).__name__},
            )
        try:
            seo = await asyncio.to_thread(
                resources.products.get_seo_words, product_ids=[product_id]
            )
            info.seo_words = seo_words_of(seo, product_id)
        except Exception as exc:
            logger.info(
                "content_analysis_seo_words_failed",
                extra={"shop_id": str(shop_id), "error": type(exc).__name__},
            )
        return info


__all__ = ["TikTokProductReader", "brand_of", "images_of", "seo_words_of"]
