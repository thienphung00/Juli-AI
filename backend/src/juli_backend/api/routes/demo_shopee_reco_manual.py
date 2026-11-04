"""Seller scope: manual offers and the comparison of variants (p91 D-3), under the
recommendations prefix ``/v1/demo/shopee/recommendations``.

- ``POST /compare`` -- the seller's 2-4 variants side by side; records nothing. Cards are
  returned in the seller's view (no model internals).
- ``POST /manual`` -- saves the chosen variant as the seller's own card (``origin = "manual"``,
  ``created_by`` = the seller user), already sent so the seller approves it in the app; the
  frozen `proposed` event is its card event.

Only the seller of that shop (``get_active_shop`` / ``require_writable_shop``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.api.routes.shopee_reco_manual_common import CompareBody, ManualBody
from juli_backend.api.routes.shopee_recommendations_common import refused
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import manual, seller_view
from juli_backend.services.shopee_recommendations.loader import load_env

router = APIRouter(prefix="/demo/shopee/recommendations", tags=["demo-shopee"])

_SELLER_HIDDEN_VERSION = ("card",)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seller_versions(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for v in versions:
        row = {k: val for k, val in v.items() if k not in _SELLER_HIDDEN_VERSION}
        out.append(row)
    return out


@router.post("/compare")
async def compare_variants(
    body: CompareBody,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    now = _now()
    try:
        env = await load_env(session, shop_id, as_of=body.as_of, now=now)
        if env is None:
            raise ProposalError(manual.ERROR_NO_DATA, 409, "shop has no Shopee numbers")
        out = manual.compare(env, [v.as_dict() for v in body.variants], now=now)
    except ProposalError as exc:
        raise refused(exc) from None
    for row in out["variants"]:
        if row["card"] is not None:
            row["card"] = seller_view(row["card"])
    return out


@router.post("/manual", status_code=201)
async def create_manual_card(
    body: ManualBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        out = await manual.create_manual(
            session,
            shop_id,
            [v.as_dict() for v in body.variants],
            body.chosen,
            body.primary,
            manual.Actor("seller", user.id),
            now=_now(),
            as_of=body.as_of,
        )
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {**out, "card": seller_view(out["card"]), "versions": _seller_versions(out["versions"])}
