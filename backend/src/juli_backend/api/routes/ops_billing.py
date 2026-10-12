"""Juli Ops tab "Thời hạn" (fast track P20, DECISIONS D28.4).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth
dependencies (Cloudflare Access → Supabase → active staff row → role) and the
same PII-masking route class.

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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import (
    MaskedRoute,
    OpsContext,
    _shop,
    _shop_json,
    admin,
    viewer,
)
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ops import STAGE_LABELS, STAGE_TRIAL, OpsShopSettings
from juli_backend.services import subscriptions
from juli_backend.services.ops import audit, overview
from juli_backend.services.ops.access import ops_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_PERIOD_ADDED = "subscription_period_added"


async def _stages(session: AsyncSession) -> dict[uuid.UUID, str]:
    async with ops_role(session):
        rows = (await session.execute(select(OpsShopSettings))).scalars().all()
    return {r.shop_id: r.stage for r in rows}


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
    stages = await _stages(session)
    rows: list[dict[str, Any]] = []
    for listing in await overview.list_shops(session):
        async with with_shop_scope(session, listing.shop_id):
            periods = await subscriptions.list_periods(session, listing.shop_id)
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
    listing = await _shop(session, shop_id)
    today = subscriptions.shop_today()
    async with with_shop_scope(session, shop_id):
        periods = await subscriptions.list_periods(session, shop_id)
        term = await subscriptions.shop_term(session, shop_id, today)
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
    await _shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        term = await subscriptions.shop_term(session, shop_id)
    return {"data": term.to_json()}
