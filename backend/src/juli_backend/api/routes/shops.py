import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Shop]:
    """Return all shops belonging to the authenticated user."""
    shops = await ShopsRepo(session).list(user.id)
    return shops[offset : offset + limit]


@router.get("/me", response_model=ShopResponse)
async def get_current_shop(
    shop: Shop = Depends(get_active_shop),
) -> Shop:
    """Return the shop identified by the X-Shop-Id header."""
    return shop


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
