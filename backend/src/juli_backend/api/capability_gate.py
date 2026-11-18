"""One capability gate for the Shopee seller routes and the Shopee Ops routes (W3a).

A route is open to a shop when BOTH hold:

1. the shop's platform is one of ``requires_data_on``, the platforms whose data the route
   reads today (default Shopee). Until the TikTok backfill lands, no route opens to TikTok,
   so the platform set is the switch: widen it for one route when its data exists;
2. ``can(platform, capability)`` is not ``Route.none``. A route with no registry id fits
   (``capability=None``) skips this check.

Otherwise the answer is the 409 ``not_a_shopee_shop`` the routes have always given. The
``can()`` check alone would open routes: today's TikTok rows say ``api`` for some reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.ops import _shop
from juli_backend.database import Shop, get_session
from juli_backend.services.capabilities.registry import Route, can

#: The platforms whose data the guarded routes read today.
DEFAULT_DATA_PLATFORMS: tuple[str, ...] = ("shopee",)

NOT_A_SHOPEE_SHOP: dict[str, str] = {
    "code": "not_a_shopee_shop",
    "message": "this shop is not on Shopee",
}


def check_open(
    platform: str,
    capability: str | None,
    requires_data_on: tuple[str, ...] = DEFAULT_DATA_PLATFORMS,
) -> None:
    """Raise the 409 unless the platform has this route's data and the capability exists."""
    if platform not in requires_data_on or (
        capability is not None and can(platform, capability).route is Route.none
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=dict(NOT_A_SHOPEE_SHOP))


def require_capability(
    capability: str | None,
    *,
    requires_data_on: tuple[str, ...] = DEFAULT_DATA_PLATFORMS,
    shop_dependency: Callable[..., Awaitable[Shop]] = get_active_shop,
) -> Callable[..., Awaitable[Shop]]:
    """Seller routes: the resolved shop (``shop_dependency`` runs first), or the 409."""

    async def gate(shop: Shop = Depends(shop_dependency)) -> Shop:
        check_open(shop.platform, capability, requires_data_on)
        return shop

    return gate


def require_ops_capability(
    capability: str | None,
    *,
    requires_data_on: tuple[str, ...] = DEFAULT_DATA_PLATFORMS,
) -> Callable[..., Awaitable[str]]:
    """Ops routes under ``/shops/{shop_id}``: 404 for an unknown shop, the 409, the shop name.

    The platform comes from the Ops listing, not from a read under ``shops.user_id``: since
    P93 that user may be a removed member, and ``shops`` RLS then hides the shop from them.
    """

    async def gate(shop_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> str:
        listing = await _shop(session, shop_id)
        await session.commit()
        check_open(listing.platform, capability, requires_data_on)
        return listing.shop_name

    return gate
