"""Seller scope: the Shopee recommendation cards (P90 step 8), ``/v1/demo/shopee/recommendations``.

The client's manager reads the cards Ops published, moves the what-if inputs, approves,
asks for a change or dismisses (ADR-107 reasons), and marks "Đã làm" after saving the change
in Seller Centre. Authenticated like every seller route (``get_active_shop``).

- ``GET  /recommendations[?family=&section=&status=&xep_theo=]`` -- cards in ranking order.
- ``GET  /recommendations/{id}`` -- certain + predicted + five numbers before -> after, floor,
  spend, measurement plan, execution sheet, journey.
- ``POST /recommendations/{id}/whatif`` -- recompute with other inputs (records `whatif_adjusted`).
- ``POST /recommendations/{id}/approve`` | ``/request-change`` | ``/dismiss``
- ``POST /recommendations/{id}/executed`` -- "Đã làm": the `executed` event with `change`.

A shop that is not on Shopee answers 409 ``not_a_shopee_shop``. The logic is
``services/shopee_recommendations``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.api.routes.shopee_recommendations_common import (
    ApproveBody,
    DismissBody,
    ExecutedBody,
    RequestChangeBody,
    WhatIfBody,
    refused,
)
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shop_proposals import ProposalError

router = APIRouter(prefix="/demo/shopee/recommendations", tags=["demo-shopee"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("")
async def list_recommendations(
    family: Annotated[
        str | None, Query(pattern="^(ads|promotion|voucher|sale|combo|affiliate|mega_sale)$")
    ] = None,
    section: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
    xep_theo: Annotated[str, Query(max_length=24)] = "diem",
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        return await reco.list_cards(
            session,
            shop_id,
            audience="seller",
            family=family,
            section=section,
            status=status,
            xep_theo=xep_theo,
        )
    except ProposalError as exc:
        raise refused(exc) from None


@router.get("/{card_id}")
async def recommendation_detail(
    card_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        return await reco.card_detail(session, shop_id, card_id, audience="seller")
    except ProposalError as exc:
        raise refused(exc) from None


@router.post("/{card_id}/whatif")
async def recommendation_whatif(
    card_id: uuid.UUID,
    body: WhatIfBody,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        card = await reco.recompute(session, shop_id, card_id, body.inputs, now=_now())
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {"card": reco.seller_view(card)}


@router.post("/{card_id}/approve")
async def approve_recommendation(
    card_id: uuid.UUID,
    body: ApproveBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _decide(
        session, shop, card_id, user, "approve", inputs=body.inputs, note=body.note
    )


@router.post("/{card_id}/request-change")
async def request_change(
    card_id: uuid.UUID,
    body: RequestChangeBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _decide(session, shop, card_id, user, "request_change", note=body.note)


@router.post("/{card_id}/dismiss")
async def dismiss_recommendation(
    card_id: uuid.UUID,
    body: DismissBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _decide(
        session, shop, card_id, user, "dismiss", reason_code=body.reason_code, note=body.note
    )


async def _decide(
    session: AsyncSession, shop: Shop, card_id: uuid.UUID, user: User, decision: str, **kw: Any
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        out = await reco.decide(
            session, shop_id, card_id, decision=decision, user_id=user.id, now=_now(), **kw
        )
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out


@router.post("/{card_id}/executed", status_code=201)
async def recommendation_executed(
    card_id: uuid.UUID,
    body: ExecutedBody,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        out = await reco.mark_executed(
            session,
            shop_id,
            card_id,
            now=_now(),
            executed_at=body.executed_at,
            user_id=user.id,
            voucher_id=body.voucher_id,
            evidence_ref=body.evidence_ref,
        )
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out
