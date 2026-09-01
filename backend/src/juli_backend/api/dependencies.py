import logging
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import (
    Shop,
    ShopsRepo,
    User,
    get_session,
    set_tenant_context,
)
from juli_backend.database.tenant_context import _apply_tenant_context_to_session

logger = logging.getLogger(__name__)


async def get_active_shop(
    x_shop_id: str = Header(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    """Resolve X-Shop-Id header to a Shop owned by the authenticated user.

    Issue #1327, ADR-085 decision 2: Sets tenant context (GUC + contextvar)
    for the request's database operations. This ensures SET LOCAL
    app.current_shop_id is applied transparently to every route depending
    on this resolver, without requiring opt-in via a new dependency.
    """
    try:
        shop_id = uuid.UUID(x_shop_id)
    except ValueError:
        logger.warning("invalid_shop_id", extra={"user_id": str(user.id), "raw_header": x_shop_id})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid shop ID",
        )

    shops = await ShopsRepo(session).list(user.id)
    shop = None
    for s in shops:
        if s.id == shop_id:
            shop = s
            break

    if shop is None:
        logger.warning(
            "shop_access_denied",
            extra={"user_id": str(user.id), "shop_id": str(shop_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shop not accessible",
        )

    # Apply tenant context for the request's transactions:
    # 1. Direct apply to the session for the HTTP path — ensures SET LOCAL GUCs
    #    are applied to the exact session/transaction the route's operations will use.
    await _apply_tenant_context_to_session(session, shop.id, user.id)

    # 2. Also set contextvars for other paths (Celery tasks, internal calls) that may
    #    read them directly.
    set_tenant_context(shop.id, user.id)

    return shop
