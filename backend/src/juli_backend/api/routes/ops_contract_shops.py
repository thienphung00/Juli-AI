"""Juli Ops: contract-client shops (owner decisions 2026-11-02, ADR-118).

- ``POST /v1/ops/contract-shops`` (Vận hành) -- "Thêm shop hợp đồng": a Shopee shop
  with no seller login (name + the Seller Centre shop id). Audited
  ``contract_shop_create``.
- ``GET  /v1/ops/shops/{id}/consent`` (Xem+) -- which Terms scopes are open and whether
  the shop is a contract client (only those get the button).
- ``POST /v1/ops/shops/{id}/consent`` (Vận hành) -- "Bật": no body, no fields. Grants
  every Terms scope not yet open; a shop with a seller login is refused (409).
  Audited ``consent_enable``.
- ``POST /v1/ops/shops/{id}/pairing-codes`` (Vận hành) -- "Tạo mã kết nối": a
  10-minute, single-use code for the Juli Connector or ``load_shopee_exports.py
  --api-url``; 409 before "Bật". Audited ``pairing_code_create`` (never the code).
- ``GET /v1/ops/shops/{id}/ingest-tokens`` (Xem+) and ``DELETE
  /v1/ops/shops/{id}/ingest-tokens/{token_id}`` (Vận hành, "Thu hồi") -- the connected
  sources; never the token or its hash. Audited ``ingest_token_revoke``.

The service is ``services/ops/contract_shops.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _shop, operator, viewer
from juli_backend.database import get_session
from juli_backend.services import ingest as ingest_service
from juli_backend.services.ops import audit, contract_shops

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_CONTRACT_SHOP_CREATE = "contract_shop_create"
ACTION_CONSENT_ENABLE = "consent_enable"
ACTION_PAIRING_CODE_CREATE = "pairing_code_create"
ACTION_INGEST_TOKEN_REVOKE = "ingest_token_revoke"

NOT_A_CONTRACT_SHOP = HTTPException(
    status_code=409,
    detail={
        "code": "not_a_contract_shop",
        "message": "this shop has a seller login; its consent comes from the seller",
    },
)


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
        raise NOT_A_CONTRACT_SHOP from None
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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


@router.post("/shops/{shop_id}/pairing-codes", status_code=201)
async def ops_create_pairing_code(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    try:
        issued = await contract_shops.issue_pairing_code(
            session, shop_id, listing.owner_user_id, created_by=ctx.user.id, now=_now()
        )
    except contract_shops.NotAContractShop:
        await session.rollback()
        raise NOT_A_CONTRACT_SHOP from None
    except contract_shops.ConsentNotEnabled:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": "consent_required"}) from None
    except ingest_service.PairingError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
    await audit.record(
        session,
        ctx.staff.actor,
        ACTION_PAIRING_CODE_CREATE,
        shop_id=shop_id,
        after={"expires_at": _iso(issued.expires_at)},
    )
    await session.commit()
    return {
        "code": issued.code,
        "expires_at": _iso(issued.expires_at),
        "ttl_seconds": int(ingest_service.PAIRING_CODE_TTL.total_seconds()),
    }


@router.get("/shops/{shop_id}/ingest-tokens")
async def ops_list_ingest_tokens(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    try:
        tokens = await contract_shops.list_tokens(session, shop_id, listing.owner_user_id)
    except contract_shops.NotAContractShop:
        await session.rollback()
        raise NOT_A_CONTRACT_SHOP from None
    await session.commit()
    now = _now()
    grace = ingest_service.ROTATION_GRACE
    return {
        "data": [
            {
                "id": str(t.id),
                "client_label": t.client_label,
                "created_at": _iso(t.created_at),
                "expires_at": _iso(t.expires_at),
                "last_used_at": _iso(t.last_used_at),
                "revoked_at": _iso(t.revoked_at),
                "active": t.revoked_at is None
                and t.expires_at > now
                and (t.superseded_at is None or now < t.superseded_at + grace),
            }
            for t in tokens
        ]
    }


@router.delete("/shops/{shop_id}/ingest-tokens/{token_id}", status_code=204)
async def ops_revoke_ingest_token(
    shop_id: uuid.UUID,
    token_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> Response:
    listing = await _shop(session, shop_id)
    try:
        found = await contract_shops.revoke_token(
            session, shop_id, listing.owner_user_id, token_id, now=_now()
        )
    except contract_shops.NotAContractShop:
        await session.rollback()
        raise NOT_A_CONTRACT_SHOP from None
    if not found:
        await session.rollback()
        raise HTTPException(status_code=404, detail={"code": "token_not_found"})
    await audit.record(
        session,
        ctx.staff.actor,
        ACTION_INGEST_TOKEN_REVOKE,
        shop_id=shop_id,
        after={"token_id": str(token_id)},
    )
    await session.commit()
    return Response(status_code=204)
