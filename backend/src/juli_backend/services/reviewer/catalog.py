"""The pinned shop's identities, for the reviewer mask (P32-A, D42).

Titles and TikTok ids of the shop's products, SKUs and LIVE sessions, so a title
or id that appears only inside free text (a card reason, a run narration) is
still found. Read under the shop's own tenant scope (the caller has entered it
through ``services/ops/view_as``); cached per shop for :data:`TTL_SECONDS`.
"""

from __future__ import annotations

import threading
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import SingleFlight
from juli_backend.models.models import InventoryItem, Livestream, Product, Shop
from juli_backend.services.reviewer.config import extra_mask_terms, shop_alias_id
from juli_backend.services.reviewer.masking import MaskDictionary

TTL_SECONDS = 600.0
_lock = threading.Lock()
_cache: dict[uuid.UUID, tuple[float, MaskDictionary]] = {}
_flight: SingleFlight[uuid.UUID, MaskDictionary] = SingleFlight()


def forget_cached() -> None:
    with _lock:
        _cache.clear()


async def load_dictionary(session: AsyncSession, shop: Shop) -> MaskDictionary:
    """The shop's mask dictionary (cached); the caller holds the shop's read scope.

    P69b: concurrent misses for the same shop share one read (single flight, keyed by
    the shop id; the dictionary describes only that shop).
    """
    with _lock:
        hit = _cache.get(shop.id)
    if hit is not None and time.monotonic() - hit[0] <= TTL_SECONDS:
        return hit[1]
    loaded = await _flight.run(shop.id, lambda: _read_dictionary(session, shop))
    return loaded if loaded.shop_id == shop.id else await _read_dictionary(session, shop)


async def _read_dictionary(session: AsyncSession, shop: Shop) -> MaskDictionary:
    dictionary = MaskDictionary(
        shop_id=shop.id,
        alias_id=shop_alias_id(shop.id),
        shop_name=shop.shop_name,
        tiktok_shop_id=shop.tiktok_shop_id,
        extra_terms=extra_mask_terms(),
    )
    for tiktok_id, title, name in (
        await session.execute(
            select(Product.tiktok_product_id, Product.title, Product.name).where(
                Product.shop_id == shop.id
            )
        )
    ).all():
        if tiktok_id:
            dictionary.ids[str(tiktok_id)] = "product"
        for text in (title, name):
            if text and text.strip():
                dictionary.titles[text.strip()] = "product"
    for sku_id, seller_sku in (
        await session.execute(
            select(InventoryItem.tiktok_sku_id, InventoryItem.seller_sku).where(
                InventoryItem.shop_id == shop.id
            )
        )
    ).all():
        for text in (sku_id, seller_sku):
            if text:
                dictionary.ids[str(text)] = "sku"
    for live_id, title in (
        await session.execute(
            select(Livestream.tiktok_livestream_id, Livestream.title).where(
                Livestream.shop_id == shop.id
            )
        )
    ).all():
        if live_id:
            dictionary.ids[str(live_id)] = "live"
        if title and title.strip():
            dictionary.titles[title.strip()] = "live"
    with _lock:
        _cache[shop.id] = (time.monotonic(), dictionary)
    return dictionary


__all__ = ["TTL_SECONDS", "forget_cached", "load_dictionary"]
