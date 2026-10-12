"""A Shopee shop connected to a Juli user (D31.1), before Shopee OAuth exists.

A Shopee shop is an ordinary ``shops`` row with ``platform = 'shopee'`` and no
TikTok credential: it owns tenancy, RLS, Ops and the seller's views like any
shop, and is fed only by the ingest gateway until the Open Platform app is
approved (D31.2). TikTok polling never picks it up -- the pollers start from
``tiktok_credentials``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_user_scope
from juli_backend.models.ingest import PLATFORM_SHOPEE
from juli_backend.models.models import Shop

logger = logging.getLogger(__name__)


async def connect_shopee_shop(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    shop_name: str,
    shopee_shop_id: str | None = None,
) -> Shop:
    """Create the seller's Shopee shop (``shops`` inserts are user-scoped)."""
    name = shop_name.strip()
    if not name or len(name) > 200:
        raise ValueError("shop_name must be 1-200 characters")
    if shopee_shop_id is not None and not (shopee_shop_id.isdigit() and len(shopee_shop_id) <= 32):
        raise ValueError("shopee_shop_id must be the numeric Seller Centre shop id")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name=name,
        platform=PLATFORM_SHOPEE,
        shopee_shop_id=shopee_shop_id,
        tiktok_shop_id=None,
    )
    async with with_user_scope(session, user_id):
        session.add(shop)
        await session.flush()
    logger.info(
        "shopee_shop_connected",
        extra={
            "shop_id": str(shop.id),
            "user_id": str(user_id),
            "has_shopee_id": bool(shopee_shop_id),
        },
    )
    return shop
