import logging
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.identity.infrastructure.auth import get_current_user
from backend.database import Shop, ShopsRepo, User, get_session

logger = logging.getLogger(__name__)


async def get_active_shop(
    x_shop_id: str = Header(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    """Resolve X-Shop-Id header to a Shop owned by the authenticated user."""
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
