"""Seller scope: the Shopee recommendation cards (P90 step 8), ``/v1/demo/shopee/recommendations``.

The client's manager reads the cards Ops published, moves the what-if inputs, approves,
asks for a change or dismisses (ADR-107 reasons), and marks "Đã làm" after saving the change
in Seller Centre. Authenticated like every seller route (``get_active_shop``).

- ``GET  /recommendations[?family=&section=&status=&xep_theo=&product_id=&queue=top|all]`` -- cards
  in ranking order; by default one card per product (``product_queue`` 1), ``queue=all`` or a
  ``product_id`` returns every card (the Sản phẩm page).
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

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.api.reviewer import SAMPLE_SHOP_CARD_KINDS, deny, reviewer_context
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
from juli_backend.services.ops import audit
from juli_backend.services.reviewer import simulation
from juli_backend.services.shop_proposals import ProposalError

router = APIRouter(prefix="/demo/shopee/recommendations", tags=["demo-shopee"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("")
async def list_recommendations(
    family: Annotated[
        str | None,
        Query(pattern="^(ads|promotion|voucher|sale|combo|affiliate|listing|mega_sale)$"),
    ] = None,
    section: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
    xep_theo: Annotated[str, Query(max_length=24)] = "diem",
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    queue: Annotated[str, Query(pattern="^(top|all)$")] = "top",
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
            product_id=product_id,
            queue=queue,
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
        card = await reco.recompute(
            session, shop_id, card_id, body.inputs, now=_now(), version=body.version
        )
        await session.commit()
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {"card": reco.seller_view(card)}


@router.post("/{card_id}/approve")
async def approve_recommendation(
    card_id: uuid.UUID,
    body: ApproveBody,
    request: Request,
    shop: Shop = Depends(require_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    context = reviewer_context(request)
    if context is not None:
        if context.pin is None or not context.pin.sample:
            # The gate admits a reviewer here only on the sample pin; any other pin keeps the
            # masked pin's simulation (fail closed: never a real approve).
            return await _simulated_approve(session, request, shop, card_id, body)
        # P100 S2-G (owner Option A): on the sample shop Duyệt is the REAL approve (Juli's rows
        # only; the fill queue is off in a reviewer session), for the three strategies' cards.
        await _require_sample_kind(session, shop, card_id)
    return await _decide(
        session,
        shop,
        card_id,
        user,
        "approve",
        inputs=body.inputs,
        note=body.note,
        chosen_version=body.chosen_version,
        chosen_versions=body.chosen_versions,
        acknowledge_breaches=body.acknowledge_breaches,
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


async def _require_sample_kind(session: AsyncSession, shop: Shop, card_id: uuid.UUID) -> None:
    """P100 S2-G: a sample-shop reviewer approves only Tiêu đề / Ảnh bìa / Voucher cards."""
    try:
        detail = await reco.card_detail(session, _shopee(shop), card_id, audience="seller")
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    if detail.get("change_kind") not in SAMPLE_SHOP_CARD_KINDS:
        await session.rollback()
        raise deny("read_only")


async def _simulated_approve(
    session: AsyncSession, request: Request, shop: Shop, card_id: uuid.UUID, body: ApproveBody
) -> dict[str, Any]:
    """The simulated Duyệt (P100 S2-F) for a reviewer on a masked pin: read the card, answer
    like an approve, write only the audit row -- nothing to Shopee, no approval, event, meta or
    fill job. The gate does not admit this route on a masked pin today (S2-G: the sample shop
    takes the real approve); kept so that a pin which is not the sample shop never approves."""
    context = reviewer_context(request)
    if context is None or context.pin is None or context.pin.sample or context.pin.sandbox:
        raise deny("read_only")  # fail closed
    shop_id = _shopee(shop)
    try:
        detail = await reco.card_detail(session, shop_id, card_id, audience="seller")
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    if detail.get("change_kind") not in SAMPLE_SHOP_CARD_KINDS:
        raise deny("read_only")  # only Tiêu đề / Ảnh bìa / Voucher on the sample shop
    result = simulation.simulate_shopee_approve(
        detail, chosen_version=body.chosen_version, chosen_versions=body.chosen_versions
    )
    # The read above ran in the shop's tenant scope; the audit row is the only write.
    await audit.record(
        session,
        context.account.actor,
        audit.ACTION_REVIEWER_SIMULATED_APPROVE,
        shop_id=shop_id,
        after={
            "platform": context.platform,
            "card_id": str(card_id),
            "change_kind": detail.get("change_kind"),
            "chosen_version": result["chosen_version"],
            "shopee": True,
        },
    )
    await session.commit()
    return result


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
