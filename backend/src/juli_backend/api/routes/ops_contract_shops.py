"""Juli Ops: contract-client shops (owner decisions 2026-11-02, ADR-118).

- ``POST /v1/ops/contract-shops`` (Vận hành) -- "Thêm shop hợp đồng": a Shopee shop
  with no seller login (name + the Seller Centre shop id). Audited
  ``contract_shop_create``.
- ``GET  /v1/ops/shops/{id}/consent`` (Xem+) -- which Terms scopes are open and whether
  the shop is a contract client (only those get the button).
- ``POST /v1/ops/shops/{id}/consent`` (Vận hành) -- "Bật": no body, no fields. Grants
  every Terms scope not yet open; a shop with a seller login is refused (409).
  Audited ``consent_enable``.

The service is ``services/ops/contract_shops.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _shop, operator, viewer
from juli_backend.database import get_session
from juli_backend.services.ops import audit, contract_shops

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_CONTRACT_SHOP_CREATE = "contract_shop_create"
ACTION_CONSENT_ENABLE = "consent_enable"


class ContractShopWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_name: str = Field(min_length=1, max_length=200)
    shopee_shop_id: str | None = Field(default=None, max_length=32)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _state_json(state: contract_shops.ConsentState) -> dict[str, Any]:
    return {
        "scopes": state.scopes,
        "enabled": state.enabled,
        "contract_client": state.contract_client,
    }


@router.post("/contract-shops", status_code=201)
async def ops_create_contract_shop(
    body: ContractShopWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shopee_id = (body.shopee_shop_id or "").strip() or None
    try:
        shop = await contract_shops.create_contract_shop(
            session, shop_name=body.shop_name, shopee_shop_id=shopee_id, now=_now()
        )
        after = {"shop_name": shop.shop_name, "platform": shop.platform}
        await audit.record(
            session, ctx.staff.actor, ACTION_CONTRACT_SHOP_CREATE, shop_id=shop.id, after=after
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422, detail={"code": "invalid_shop", "message": str(exc)}
        ) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": "shopee_shop_taken"}) from None
    return {
        "shop": {
            "id": str(shop.id),
            "shop_name": shop.shop_name,
            "platform": shop.platform,
            "shopee_shop_id": shop.shopee_shop_id,
        }
    }


@router.get("/shops/{shop_id}/consent")
async def ops_get_consent(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    state = await contract_shops.consent_state(session, shop_id, listing.owner_user_id)
    await session.commit()
    return _state_json(state)


@router.post("/shops/{shop_id}/consent")
async def ops_enable_consent(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    try:
        granted = await contract_shops.enable_consent(
            session, shop_id, listing.owner_user_id, staff_id=ctx.staff.id, now=_now()
        )
    except contract_shops.NotAContractShop:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_a_contract_shop",
                "message": "this shop has a seller login; its consent comes from the seller",
            },
        ) from None
    if granted:
        await audit.record(
            session,
            ctx.staff.actor,
            ACTION_CONSENT_ENABLE,
            shop_id=shop_id,
            after={"scopes": granted},
        )
    await session.commit()
    state = await contract_shops.consent_state(session, shop_id, listing.owner_user_id)
    await session.commit()
    return {**_state_json(state), "granted": granted}
