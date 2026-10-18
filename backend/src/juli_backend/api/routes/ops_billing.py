"""Juli Ops tabs "Chi phí" and "Thời hạn" (fast track P20, DECISIONS D28.3 / D28.4).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth
dependencies (Cloudflare Access → Supabase → active staff row → role) and the
same PII-masking route class.

Chi phí (D28.3):

- ``GET  /v1/ops/costs`` (Xem+) -- the month's system OpenAI spend vs the
  system cap, and each shop's spend vs its own cap (``is_custom`` = "· riêng").
- ``GET  /v1/ops/costs/system`` (Xem+) -- the system figure alone: the one cheap
  call behind the ≥ 80 % banner on every Ops page.
- ``PUT  /v1/ops/costs/system-cap`` (Admin) ``{"usd": n}`` -- audited
  ``openai_system_cap_set``.
- ``PUT  /v1/ops/shops/{id}/openai-cap`` (Admin) ``{"usd": n | null}`` -- the
  shop's ``shop_rules`` row ``openai_monthly_cap_usd`` through the existing
  settings path (``ops_settings.update_settings``), so P15 / P16 read it;
  ``null`` = back to the default. Audited ``openai_shop_cap_set``.

Thời hạn (D28.4):

- ``GET  /v1/ops/terms`` (Xem+) -- every shop: stage, term state, expiry, days
  left, grace days left, latest period.
- ``GET  /v1/ops/shops/{id}/terms`` (Xem+) -- the shop's periods, newest first.
- ``POST /v1/ops/shops/{id}/terms`` (Admin) ``{"days": 30|365, "reference": "HĐ-…"}``
  -- ``subscriptions.grant_period(source="contract")`` under the shop's scope;
  audited ``subscription_period_added``. Idempotent on the reference: a repeat
  returns the existing period (``created: false``) and writes no audit row.
- ``GET  /v1/ops/shops/{id}/view/term`` (Xem+) -- "Xem như shop": exactly the
  seller's ``/v1/shops/me/term`` payload.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import (
    MaskedRoute,
    OpsContext,
    _refresh_summary_quietly,
    _shop,
    _shop_json,
    admin,
    shop_then_scope,
    viewer,
)
from juli_backend.database import get_session
from juli_backend.database.tenant_context import sequential_shop_scopes, with_shop_scope
from juli_backend.models.ops import STAGE_LABELS, STAGE_TRIAL, OpsShopSettings
from juli_backend.services import subscriptions
from juli_backend.services.ops import audit, ops_role, overview, system_cap
from juli_backend.services.ops import settings as ops_settings
from juli_backend.services.shop_rules import openai_cap

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_PERIOD_ADDED = "subscription_period_added"
SHOP_CAP_STATE_OK = "ok"
SHOP_CAP_STATE_SHOP = "shop_cap"
SHOP_CAP_STATE_SYSTEM = "system_cap"


async def _stages(session: AsyncSession) -> dict[uuid.UUID, str]:
    async with ops_role(session):
        rows = (await session.execute(select(OpsShopSettings))).scalars().all()
    return {r.shop_id: r.stage for r in rows}


# -- Chi phí (D28.3) -----------------------------------------------------------------


def _days_left_in_month(today: date) -> int:
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (first_next - today).days


async def _stages_and_shops(
    session: AsyncSession,
) -> tuple[dict[uuid.UUID, str], list[Any], str | None]:
    """Stages and the shop list in ONE ops block (P29); returns its handed-over restore."""
    async with ops_role(session) as block:
        stages = await _stages(session)
        listings = await overview.list_shops(session)
        previous_role = block.hand_over()
    return stages, listings, previous_role


async def costs_body(session: AsyncSession) -> dict[str, Any]:
    """Chi phí. P29: the banner figure first (it may roll back on a failed
    fused read, so nothing may precede it), one ops block, then each shop under
    its own scope with ONE fused read -- 2 round trips per shop, was 4."""
    status_now, alert_sent = await system_cap.system_banner(session)
    stages, listings, previous_role = await _stages_and_shops(session)
    shops: list[dict[str, Any]] = []
    async with sequential_shop_scopes(
        session, restore_role=previous_role, transaction_ends_after=True
    ) as scopes:
        numbers = []
        for listing in listings:
            await scopes.enter(listing.shop_id)
            numbers.append(await openai_cap.openai_spend_and_cap(session, listing.shop_id))
    for listing, (spent, cap) in zip(listings, numbers, strict=True):
        if status_now.reached:
            state = SHOP_CAP_STATE_SYSTEM
        elif spent >= cap.usd:
            state = SHOP_CAP_STATE_SHOP
        else:
            state = SHOP_CAP_STATE_OK
        stage = stages.get(listing.shop_id, STAGE_TRIAL)
        shops.append(
            {
                "shop_id": str(listing.shop_id),
                "shop_name": listing.shop_name,
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "used_usd": float(spent),
                "cap_usd": float(cap.usd),
                "is_custom": not cap.is_default,
                "state": state,
            }
        )
    shops.sort(key=lambda s: (-s["used_usd"], s["shop_name"]))
    today = subscriptions.shop_today()
    return {
        "system": {**status_now.to_json(), "alert_sent": alert_sent},
        "warn_pct": float(system_cap.WARN_PCT),
        "days_left_in_month": _days_left_in_month(today),
        "default_shop_cap_usd": float(openai_cap.default_cap_usd()),
        "seller_paused_text": system_cap.SELLER_PAUSED_VI,
        "shops": shops,
    }


@router.get("/costs")
async def ops_costs(
    ctx: OpsContext = Depends(viewer), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await costs_body(session)


@router.get("/costs/system")
async def ops_costs_system(
    ctx: OpsContext = Depends(viewer), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    # P29: cached for 30 s (the banner on every Ops page), else ONE statement.
    status_now, alert_sent = await system_cap.system_banner(session)
    return {"system": {**status_now.to_json(), "alert_sent": alert_sent}}


class CapWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usd: float


class ShopCapWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usd: float | None


@router.put("/costs/system-cap")
async def ops_put_system_cap(
    body: CapWrite,
    ctx: OpsContext = Depends(admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await system_cap.set_system_cap(session, ctx.staff.actor, body.usd)
    except system_cap.SystemCapError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    system_cap.forget_banner()
    return {"system": (await system_cap.system_status(session)).to_json()}


@router.put("/shops/{shop_id}/openai-cap")
async def ops_put_shop_cap(
    shop_id: uuid.UUID,
    body: ShopCapWrite,
    ctx: OpsContext = Depends(admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The shop's own cap via the existing settings path (``shop_rules``), audited."""
    await _shop(session, shop_id)
    try:
        view = await ops_settings.update_settings(
            session,
            ctx.staff.actor,
            shop_id,
            {ops_settings.CAP_FIELD: body.usd},
            action=system_cap.ACTION_SHOP_CAP,
        )
    except ops_settings.SettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    ops_settings.forget_cap_and_tunables(shop_id)
    await _refresh_summary_quietly(session, shop_id)
    override = view.overrides.get(ops_settings.CAP_FIELD)
    return {
        "shop_id": str(shop_id),
        "cap_usd": override if override is not None else view.defaults[ops_settings.CAP_FIELD],
        "is_custom": override is not None,
    }


# -- Thời hạn (D28.4) -----------------------------------------------------------------


def _term_row(
    term: subscriptions.ShopTerm, latest: Any, stage: str, listing: Any
) -> dict[str, Any]:
    return {
        "shop_id": str(listing.shop_id),
        "shop_name": listing.shop_name,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        **term.to_json(),
        "latest_period": subscriptions.period_json(latest) if latest is not None else None,
    }


def _sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    left = row["days_left"]
    return (1 if left is None else 0, left if left is not None else 0, row["shop_name"])


@router.get("/terms")
async def ops_terms(
    ctx: OpsContext = Depends(viewer), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    today = subscriptions.shop_today()
    stages, listings, previous_role = await _stages_and_shops(session)
    rows: list[dict[str, Any]] = []
    # P29: one scope moving shop to shop (ADR-089: one shop at a time), 2 round
    # trips per shop instead of 3, and no restore at the end of the request.
    async with sequential_shop_scopes(
        session, restore_role=previous_role, transaction_ends_after=True
    ) as scopes:
        per_shop = []
        for listing in listings:
            await scopes.enter(listing.shop_id)
            per_shop.append(await subscriptions.list_periods(session, listing.shop_id))
    for listing, periods in zip(listings, per_shop, strict=True):
        expires = max((p.ends_on for p in periods), default=None)
        latest = max(periods, key=lambda p: (p.ends_on, p.starts_on)) if periods else None
        rows.append(
            _term_row(
                subscriptions.term_for(expires, today),
                latest,
                stages.get(listing.shop_id, STAGE_TRIAL),
                listing,
            )
        )
    rows.sort(key=_sort_key)
    return {
        "today": today.isoformat(),
        "soon_days": subscriptions.SOON_DAYS,
        "grace_days": subscriptions.GRACE_DAYS,
        "shops": rows,
    }


async def _shop_terms_body(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    today = subscriptions.shop_today()
    # P29: the role switch back rides on the scope's statement; the request ends here.
    async with shop_then_scope(session, shop_id, transaction_ends_after=True) as listing:
        periods = await subscriptions.list_periods(session, shop_id)
        # == subscriptions.shop_term (max ends_on), from the rows just read.
        term = subscriptions.term_for(max((p.ends_on for p in periods), default=None), today)
    return {
        "shop": _shop_json(listing),
        "today": today.isoformat(),
        "term": term.to_json(),
        "periods": [subscriptions.period_json(p) for p in reversed(periods)],
    }


@router.get("/shops/{shop_id}/terms")
async def ops_shop_terms(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _shop_terms_body(session, shop_id)


class TermWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Literal[30, 365]
    reference: str


@router.post("/shops/{shop_id}/terms")
async def ops_add_term(
    shop_id: uuid.UUID,
    body: TermWrite,
    ctx: OpsContext = Depends(admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """ "Gói 30 / 365 ngày" (Admin): one contract period, one audit row."""
    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            grant = await subscriptions.grant_period(
                session,
                shop_id,
                days=body.days,
                source="contract",
                reference=body.reference,
                actor_email=ctx.staff.email,
            )
        if grant.created:
            await audit.record(
                session,
                ctx.staff.actor,
                ACTION_PERIOD_ADDED,
                shop_id=shop_id,
                before={"term": grant.before.to_json()},
                after={
                    "term": grant.after.to_json(),
                    "period": subscriptions.period_json(grant.period),
                },
            )
        await session.commit()
    except subscriptions.GrantError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "ops_subscription_period_added",
        extra={
            "shop_id": str(shop_id),
            "days": body.days,
            "period_created": grant.created,
            "staff_id": str(ctx.staff.id),
        },
    )
    payload = await _shop_terms_body(session, shop_id)
    payload["created"] = grant.created
    payload["period"] = subscriptions.period_json(grant.period)
    return payload


@router.get("/shops/{shop_id}/view/term")
async def ops_view_term(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """ "Xem như shop": the seller's ``/v1/shops/me/term`` payload for this shop."""
    async with shop_then_scope(session, shop_id, transaction_ends_after=True):
        term = await subscriptions.shop_term(session, shop_id)
    return {"data": term.to_json()}
