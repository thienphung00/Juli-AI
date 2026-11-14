"""Unsubscribe one member from one shop's stock e-mail (Part S). Idempotent; no commit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.stock_alert import ShopeeStockAlertUnsubscribe


async def unsubscribe(
    session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
) -> bool:
    """True when the member was subscribed until now."""
    if await session.get(ShopeeStockAlertUnsubscribe, (shop_id, user_id)) is not None:
        return False
    session.add(ShopeeStockAlertUnsubscribe(shop_id=shop_id, user_id=user_id, at=now))
    await session.flush()
    return True


__all__ = ["unsubscribe"]
