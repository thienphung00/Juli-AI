"""HTTP middleware and dependency for automatic tenant context setup.

Issue #1327, ADR-085 decision 2: sets tenant context from X-Shop-Id header
and JWT token on every request, so that database sessions automatically
apply SET LOCAL GUCs.

This module does NOT edit core/security/dependencies.py — it composes the
existing dependency resolution downstream.
"""

import logging
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, ShopsRepo, User, get_session, set_tenant_context
from juli_backend.database.tenant_context import _apply_tenant_context_to_session

logger = logging.getLogger(__name__)


async def get_active_shop_and_set_context(
    x_shop_id: str = Header(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    """Dependency that resolves shop, validates ownership, and sets tenant context.

    Use this in place of (or alongside) get_active_shop to ensure tenant
    context is set for the route's database operations.

    This is the primary seam for setting tenant context in HTTP routes.
    Routes that need tenant-scoped database access should depend on this.
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
            "shop_access_denied", extra={"user_id": str(user.id), "shop_id": str(shop_id)}
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shop not accessible",
        )

    # Set tenant context for the request's transactions:
    # 1. Apply directly to the session for the HTTP path (issue #1327, ADR-085 decision 2)
    #    This ensures SET LOCAL GUCs are applied to the exact session/transaction
    #    the route's database operations will use.
    await _apply_tenant_context_to_session(session, shop.id, user.id)

    # 2. Also set contextvars for other paths (Celery tasks, internal calls) that may
    #    read them directly.
    set_tenant_context(shop.id, user.id)

    return shop
