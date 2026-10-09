"""The shop's seller-set rules (fast track P8-C, AC-8.3, ADR-109 d.12).

- ``GET    /v1/demo/rules`` -- every rule with its value, ``set_by``,
  ``set_by_user_id`` and ``set_at``; defaults filled in where nothing is set
  (``set_by: null``).
- ``PUT    /v1/demo/rules/{rule_key}`` -- body ``{"scope_ref", "value",
  "set_by"}``; inserts or replaces one value. 422 with a plain message when the
  value is out of range for the rule.
- ``DELETE /v1/demo/rules/{rule_key}?scope_ref=`` -- unset one value; its
  default applies again. 404 when nothing was set.

``set_by`` is ``team`` (the Juli team filling values in on the seller's behalf,
the operator phase) or ``seller``. The codebase has no team/staff role yet, so
the value is taken from the request and only checked against that allowlist;
``set_by_user_id`` is always the authenticated caller (DEBT: P8-C set_by).

Auth and tenant scope as every ``/v1/demo`` route: ``get_current_user`` +
``get_active_shop``. Rules are read and written for the caller's shop only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shop_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/rules", tags=["demo"])


class RuleValueItem(BaseModel):
    value: Any
    set_by: str | None
    set_by_user_id: uuid.UUID | None
    set_at: datetime | None


class ShopRulesData(BaseModel):
    #: metric key -> ± % band (no entry: no day-7 question for that metric).
    stability_band: dict[str, RuleValueItem]
    #: TikTok product id -> cost per unit (VND).
    product_cost: dict[str, RuleValueItem]
    #: TikTok SKU id -> max discount %.
    max_discount_pct: dict[str, RuleValueItem]
    min_margin_pct: RuleValueItem | None
    max_open_cards: RuleValueItem
    auto_levers: RuleValueItem
    protected_terms: RuleValueItem
    band_metrics: list[str]
    listing_levers: list[str]


class ShopRulesResponse(BaseModel):
    success: bool = True
    data: ShopRulesData


class RuleWriteRequest(BaseModel):
    scope_ref: str | None = None
    value: Any
    set_by: Literal["team", "seller"]


class RuleWriteData(BaseModel):
    rule_key: str
    scope_ref: str
    value: Any
    set_by: str
    set_by_user_id: uuid.UUID | None
    set_at: datetime


class RuleWriteResponse(BaseModel):
    success: bool = True
    data: RuleWriteData


def _item(value: shop_rules.RuleValue) -> RuleValueItem:
    return RuleValueItem(
        value=value.value,
        set_by=value.set_by,
        set_by_user_id=value.set_by_user_id,
        set_at=value.set_at,
    )


@router.get("", response_model=ShopRulesResponse)
async def get_shop_rules(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ShopRulesResponse:
    rules = await shop_rules.get_rules(session, shop.id)
    return ShopRulesResponse(
        data=ShopRulesData(
            stability_band={k: _item(v) for k, v in rules.stability_band.items()},
            product_cost={k: _item(v) for k, v in rules.product_cost.items()},
            max_discount_pct={k: _item(v) for k, v in rules.max_discount_pct.items()},
            min_margin_pct=_item(rules.min_margin_pct) if rules.min_margin_pct else None,
            max_open_cards=_item(rules.max_open_cards),
            auto_levers=_item(rules.auto_levers),
            protected_terms=_item(rules.protected_terms),
            band_metrics=list(shop_rules.BAND_METRICS),
            listing_levers=list(shop_rules.LISTING_LEVERS),
        )
    )


@router.put("/{rule_key}", response_model=RuleWriteResponse)
async def put_shop_rule(
    rule_key: str,
    body: RuleWriteRequest,
    shop: Shop = Depends(get_active_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RuleWriteResponse:
    try:
        row = await shop_rules.set_rule(
            session,
            shop.id,
            rule_key=rule_key,
            scope_ref=body.scope_ref,
            value=body.value,
            set_by=body.set_by,
            set_by_user_id=user.id,
        )
        await session.commit()
    except shop_rules.RuleValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    logger.info(
        "shop_rule_set",
        extra={
            "shop_id": str(shop.id),
            "rule_key": rule_key,
            "set_by": body.set_by,
            "user_id": str(user.id),
        },
    )
    return RuleWriteResponse(
        data=RuleWriteData(
            rule_key=row.rule_key,
            scope_ref=row.scope_ref,
            value=row.value,
            set_by=row.set_by,
            set_by_user_id=row.set_by_user_id,
            set_at=row.set_at,
        )
    )


@router.delete("/{rule_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shop_rule(
    rule_key: str,
    scope_ref: str | None = Query(default=None),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        existed = await shop_rules.delete_rule(
            session, shop.id, rule_key=rule_key, scope_ref=scope_ref
        )
        await session.commit()
    except shop_rules.RuleValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    if not existed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not set")
    logger.info("shop_rule_unset", extra={"shop_id": str(shop.id), "rule_key": rule_key})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
