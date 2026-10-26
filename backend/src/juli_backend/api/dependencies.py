import logging
import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.reviewer import enter_reviewer_shop, reviewer_context
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

#: P50-B (D68.10): the 403 reason while the seller's account deletion is pending.
DELETION_PENDING_DETAIL = (
    "Tài khoản đang chờ xoá — chỉ xem và tải dữ liệu. Huỷ yêu cầu xoá trong "
    "Cài đặt → Quyền riêng tư để tiếp tục."
)


async def get_active_shop(
    request: Request,
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
    # P32-A (D42): a partner reviewer owns no shop; the session is pinned to the
    # reference shop and only its alias id is accepted (``api/reviewer.py``).
    reviewer = reviewer_context(request)
    if reviewer is not None:
        return await enter_reviewer_shop(session, reviewer, x_shop_id)

    try:
        shop_id = uuid.UUID(x_shop_id)
    except ValueError:
        logger.warning("invalid_shop_id", extra={"user_id": str(user.id), "raw_header": x_shop_id})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid shop ID",
        )

    # The bootstrap read (#1697): `shops` is policy-gated on a GUC no one has
    # set yet — #1691's scope was a loan and is already handed back. The
    # repository owns knowing that, as it does for `users`.
    # P69: the tenant scope applied below replaces this read's user scope, so the
    # read does not restore the prior pair first (one round trip less).
    shops = await ShopsRepo(session).list_for_authorization(user.id, scope_replaced_after=True)
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


async def require_writable_shop(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Shop:
    """Fast track P20 (D28.4): refuse a seller action on a read-only shop.

    A shop whose term ended more than 7 days ago (past the grace) is "chỉ xem":
    no new agent runs, no approval or confirmation that would write to TikTok,
    no revert, no OpenAI drafting or content analysis. 403 with the Vietnamese
    reason. Reads and data sync are not affected; a shop with no term set
    (``none``) and a shop in its grace days are not restricted.
    """
    from juli_backend.services.privacy import deletion_pending
    from juli_backend.services.subscriptions import READ_ONLY_DETAIL, is_read_only

    # P50-B (D68.10): an account with a pending deletion is read-only for its
    # 30-day export window -- no write, no TikTok change, no OpenAI work.
    if deletion_pending(user):
        logger.info("shop_deletion_pending_write_refused", extra={"shop_id": str(shop.id)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DELETION_PENDING_DETAIL)

    # The check must not leave behind a transaction the route did not start: a
    # route that later rolls back would then expire every object the caller holds.
    # (On the request path ``get_active_shop`` has already opened the transaction
    # and set the tenant GUCs in it, so this only applies when none is open.)
    started_here = not session.in_transaction()
    read_only = await is_read_only(session, shop.id)
    if started_here:
        await session.commit()
    if read_only:
        logger.info("shop_read_only_write_refused", extra={"shop_id": str(shop.id)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=READ_ONLY_DETAIL)
    return shop
