import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.reviewer import reviewer_context, reviewer_shop_options
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, ShopsRepo, User, get_session

router = APIRouter(prefix="/shops", tags=["shops"])

DEFAULT_PAGE_LIMIT = 50


class OnboardingStep(BaseModel):
    key: str
    label: str
    status: str
    percent: int | None = None
    eta_seconds: int | None = None
    detail: str | None = None


class OnboardingResponse(BaseModel):
    """Contract ``fasttrack/contracts/p17-onboarding-speed.md`` §2 (fast track P17)."""

    shop_id: str
    active: bool
    current_step: int | None = None
    total_steps: int
    label: str | None = None
    poll_interval_seconds: int | None = None
    steps: list[OnboardingStep]
    #: Read by P16's simulation: the 90-day window needs 2 × 90 days.
    history_days_available: int
    history_target_days: int
    history_days_remaining: int
    history_complete: bool
    window_90d_available: bool


class ShopResponse(BaseModel):
    id: uuid.UUID
    shop_name: str
    tiktok_shop_id: str | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ShopResponse])
async def list_shops(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Shop] | list[ShopResponse]:
    """Return all shops belonging to the authenticated user."""
    reviewer = reviewer_context(request)
    if reviewer is not None:
        # P32-A (D42): the reviewer's shops are the pinned ones -- P74-A (D77): every
        # pin, default first; a masked pin under its alias id and masked name only.
        # No pin (D42 amendment): no shop -- the UI shows the sample shop.
        return [
            ShopResponse(
                id=uuid.UUID(option.id),
                shop_name=option.name,
                tiktok_shop_id=option.tiktok_shop_id,
                is_active=option.is_active,
            )
            for option in await reviewer_shop_options(session, reviewer)
        ]
    shops = await ShopsRepo(session).list(user.id)
    return shops[offset : offset + limit]


class ShopeeShopRequest(BaseModel):
    """D31.1: a Shopee shop for the signed-in seller (no Shopee OAuth yet)."""

    shop_name: str = Field(min_length=1, max_length=200)
    shopee_shop_id: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")


class ShopeeShopResponse(BaseModel):
    id: uuid.UUID
    shop_name: str
    platform: str
    shopee_shop_id: str | None

    model_config = {"from_attributes": True}


@router.post("/shopee", response_model=ShopeeShopResponse, status_code=status.HTTP_201_CREATED)
async def create_shopee_shop(
    body: ShopeeShopRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    """Connect a Shopee shop: a ``platform='shopee'`` shop fed by the Juli Connector.

    The seller then creates a pairing code for it (``POST /v1/ingest/pairing-codes``
    with ``X-Shop-Id``) and types it into the extension.
    """
    from sqlalchemy.exc import IntegrityError

    from juli_backend.services.ingest import connect_shopee_shop

    try:
        shop = await connect_shopee_shop(
            session, user_id=user.id, shop_name=body.shop_name, shopee_shop_id=body.shopee_shop_id
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "shopee_shop_taken"},
        ) from None
    return shop


@router.get("/me", response_model=ShopResponse)
async def get_current_shop(
    shop: Shop = Depends(get_active_shop),
) -> Shop:
    """Return the shop identified by the X-Shop-Id header."""
    return shop


@router.get("/me/permissions")
async def get_current_shop_permissions(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """P16 (D25.15): whether the shop's TikTok grant carries every scope Juli uses.

    ``needs_reconnect`` drives the seller's "Kết nối lại TikTok Shop để cấp quyền
    mới" strip. Scope names only; no token is returned.
    """
    from juli_backend.services import ops

    return {"data": (await ops.shop_scope_status(session, shop.id)).to_json()}


@router.get("/me/onboarding", response_model=OnboardingResponse)
async def get_current_shop_onboarding(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The shop's onboarding progress: quick scan, 60-day backfill + diagnosis, history.

    Read-only, no TikTok call (fast track P17, D26 / D25.12). The client polls
    it at ``poll_interval_seconds`` while ``active``.
    """
    from juli_backend.services.onboarding import onboarding_status

    return await onboarding_status(session, shop.id)


@router.get("/me/term")
async def get_current_shop_term(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Fast track P20 (D28.4): the shop's Juli term as the seller's strip reads it.

    ``state`` is ``none`` | ``ok`` | ``soon`` | ``grace`` | ``read_only``; the
    seller app shows an amber reminder in ``grace`` and a grey "chỉ xem" strip in
    ``read_only`` (nothing otherwise). Dates are the shop's (UTC+7) calendar.
    """
    from juli_backend.services.subscriptions import shop_term

    return {"data": (await shop_term(session, shop.id)).to_json()}
