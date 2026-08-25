import logging
import os
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, ShopsRepo, User, get_session

logger = logging.getLogger(__name__)


async def get_active_shop(
    x_shop_id: str | None = Header(None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    """Resolve X-Shop-Id header to a Shop owned by the authenticated user.

    For anonymous users (phone == "anonymous"), the shop is always the demo
    tenant (DEMO_SHOP_ID), regardless of the header. This enforces that
    anonymous sessions are scoped to the seeded demo shop and cannot access
    any other merchant's data (ADR-084 decision 1).
    """
    # Anonymous users are always scoped to the demo tenant (ADR-084 decision 1).
    # If they pass an X-Shop-Id header pointing to a different shop, return 404
    # (never 403 -- no existence oracle).
    if user.phone == "anonymous":
        demo_shop_id_str = os.getenv("DEMO_SHOP_ID", "").strip()
        if not demo_shop_id_str:
            logger.error("demo_shop_id_not_configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Demo shop configuration error",
            )

        try:
            demo_shop_id = uuid.UUID(demo_shop_id_str)
        except ValueError:
            logger.error("demo_shop_id_invalid", extra={"value": demo_shop_id_str})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Demo shop configuration error",
            )

        # If they passed an X-Shop-Id header for a different shop, reject it
        if x_shop_id:
            try:
                requested_shop_id = uuid.UUID(x_shop_id)
            except ValueError:
                logger.warning(
                    "anonymous_invalid_shop_id",
                    extra={"user_id": str(user.id), "raw_header": x_shop_id},
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Shop not found",
                )

            if requested_shop_id != demo_shop_id:
                logger.warning(
                    "anonymous_cross_tenant_access_attempt",
                    extra={
                        "user_id": str(user.id),
                        "requested_shop_id": str(requested_shop_id),
                        "demo_shop_id": str(demo_shop_id),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Shop not found",
                )

        # Fetch the demo shop directly (anonymous users access it
        # regardless of ownership, per ADR-084 decision 1).
        stmt = select(Shop).where(Shop.id == demo_shop_id)
        shop = await session.scalar(stmt)

        if not shop:
            logger.warning(
                "demo_shop_not_found",
                extra={"demo_shop_id": str(demo_shop_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shop not found",
            )

        return shop

    # Regular authenticated user: resolve from X-Shop-Id header
    if not x_shop_id:
        logger.warning("missing_shop_id", extra={"user_id": str(user.id)})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Shop-Id header is required",
        )

    try:
        shop_id = uuid.UUID(x_shop_id)
    except ValueError:
        logger.warning("invalid_shop_id", extra={"user_id": str(user.id), "raw_header": x_shop_id})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid shop ID",
        )

    shops = await ShopsRepo(session).list(user.id)
    for shop in shops:
        if shop.id == shop_id:
            return shop

    logger.warning("shop_access_denied", extra={"user_id": str(user.id), "shop_id": str(shop_id)})
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Shop not accessible",
    )
