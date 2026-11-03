"""Juli Ops: the Shopee recommendation cards of one shop (P90 step 8, ADR-121).

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth (Cloudflare Access ->
Supabase -> active staff row -> role) and the PII-masking route class. Writes run under the
shop's own tenant scope and are audited in ``ops_audit_log``.

- ``GET  /shops/{id}/shopee/recommendations`` / ``/{card_id}`` (Xem+) -- every card, drafts too.
- ``POST .../recommendations/generate`` (Vận hành) -- generate, rank and persist as drafts
  (optionally a ``mega_sale`` window).
- ``POST .../recommendations/publish`` -- draft -> sent: the client sees them.
- ``POST .../recommendations/{card_id}/whatif`` (Xem+) -- recompute, nothing recorded.
- ``POST .../recommendations/{card_id}/executed`` -- "Đã làm" by staff.
- ``POST .../recommendations/{card_id}/withdraw``
- ``POST .../recommendations/rerun-stale`` -- recompute only the cards an import flagged.
- ``GET/POST .../recommendations/sim-priors`` -- the audited import of a ``juli-sim/priors/v1``
  run (the per change_kind gate may be overridden, recorded).
- ``GET  .../recommendations/learning`` -- calibration, coverage and acceptance statistics.
- ``POST .../recommendations/learning/run`` | ``/backfill`` -- the calibration job; the one-off
  natural-experiment backfill from the ads change log and voucher history.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, operator, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_recommendations_common import ExecutedBody, WhatIfBody, refused
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.ops import audit
from juli_backend.services.shop_proposals import ProposalError

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee/recommendations"

ACTION_GENERATE = "reco_generate"
ACTION_PUBLISH = "reco_publish"
ACTION_WITHDRAW = "reco_withdraw"
ACTION_EXECUTED = "reco_executed"
ACTION_SIM_IMPORT = "reco_sim_import"
ACTION_LEARNING = "reco_learning_run"
ACTION_BACKFILL = "reco_backfill"
ACTION_RERUN_STALE = "reco_rerun_stale"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MegaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime
    end: datetime
    budget_cap_per_day: Decimal | None = Field(default=None, ge=0)


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date | None = None
    top_n: int = Field(default=10, ge=1, le=100)
    explore_slot: bool = False
    persist: bool = True
    mega: MegaBody | None = None


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_ids: list[uuid.UUID] | None = None


class SimImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict[str, Any]
    gate_overrides: dict[str, float] = Field(default_factory=dict)


async def _audited(
    session: AsyncSession, ctx: OpsContext, shop_id: uuid.UUID, action: str, after: dict[str, Any]
) -> None:
    await audit.record(session, ctx.staff.actor, action, shop_id=shop_id, after=after)
    await session.commit()


@router.get(BASE)
async def ops_list_recommendations(
    shop_id: uuid.UUID,
    family: Annotated[str | None, Query(max_length=16)] = None,
    section: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
    xep_theo: Annotated[str, Query(max_length=24)] = "diem",
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            return await reco.list_cards(
                session,
                shop_id,
                audience="ops",
                family=family,
                section=section,
                status=status,
                xep_theo=xep_theo,
            )
    except ProposalError as exc:
        raise refused(exc) from None


@router.get(f"{BASE}/learning")
async def ops_learning(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await reco.learning_overview(session, shop_id)


@router.get(f"{BASE}/sim-priors")
async def ops_sim_priors(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await reco.sim_summary(session, shop_id)


@router.get(BASE + "/{card_id}")
async def ops_recommendation_detail(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            return await reco.card_detail(session, shop_id, card_id, audience="ops")
    except ProposalError as exc:
        raise refused(exc) from None


@router.post(f"{BASE}/generate", status_code=201)
async def ops_generate(
    shop_id: uuid.UUID,
    body: GenerateBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    mega = None if body.mega is None else reco.MegaWindow(body.mega.start, body.mega.end)
    try:
        async with with_shop_scope(session, shop_id):
            report = await reco.generate_cards(
                session,
                shop_id,
                now=_now(),
                as_of=body.as_of,
                top_n=body.top_n,
                explore_slot=body.explore_slot,
                persist=body.persist,
                mega_window=mega,
                mega_budget_cap=None if body.mega is None else body.mega.budget_cap_per_day,
                staff_id=ctx.staff.id,
            )
        out = report.json()
        await _audited(
            session,
            ctx,
            shop_id,
            ACTION_GENERATE,
            {"persisted": report.persisted, "generated": report.generated},
        )
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {**out, "card_ids": report.card_ids}


@router.post(f"{BASE}/publish")
async def ops_publish(
    shop_id: uuid.UUID,
    body: PublishBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            sent = await reco.publish(session, shop_id, body.card_ids, now=_now())
        await _audited(session, ctx, shop_id, ACTION_PUBLISH, {"sent": len(sent)})
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {"sent": sent}


@router.post(BASE + "/rerun-stale")
async def ops_rerun_stale(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        counts = await reco.rerun_stale(session, shop_id, now=_now())
    await _audited(session, ctx, shop_id, ACTION_RERUN_STALE, counts)
    return counts


@router.post(BASE + "/{card_id}/whatif")
async def ops_whatif(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    body: WhatIfBody,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            card = await reco.recompute(
                session, shop_id, card_id, body.inputs, now=_now(), record=False
            )
    except ProposalError as exc:
        raise refused(exc) from None
    return {"card": card}


@router.post(BASE + "/{card_id}/withdraw")
async def ops_withdraw(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            await reco.withdraw(session, shop_id, card_id, now=_now())
        await _audited(session, ctx, shop_id, ACTION_WITHDRAW, {"card_id": str(card_id)})
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return {"id": str(card_id), "status": "withdrawn"}


@router.post(BASE + "/{card_id}/executed", status_code=201)
async def ops_executed(
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    body: ExecutedBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            out = await reco.mark_executed(
                session,
                shop_id,
                card_id,
                now=_now(),
                executed_at=body.executed_at,
                staff_id=ctx.staff.id,
                voucher_id=body.voucher_id,
                evidence_ref=body.evidence_ref,
            )
        await _audited(
            session,
            ctx,
            shop_id,
            ACTION_EXECUTED,
            {"card_id": str(card_id), "events": out["events"]},
        )
    except ProposalError as exc:
        await session.rollback()
        raise refused(exc) from None
    return out


@router.post(f"{BASE}/sim-priors", status_code=201)
async def ops_import_sim(
    shop_id: uuid.UUID,
    body: SimImportBody,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        priors = reco.parse_priors(body.document, gate_overrides=body.gate_overrides)
    except reco.SimImportError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "sim_import_invalid", "message": str(exc)}
        ) from None
    sha = hashlib.sha256(json.dumps(body.document, sort_keys=True).encode()).hexdigest()
    async with with_shop_scope(session, shop_id):
        run = await reco.save_sim(
            session, shop_id, priors, sha256=sha, staff_id=ctx.staff.id, now=_now()
        )
    summary = priors.summary()
    await _audited(
        session,
        ctx,
        shop_id,
        ACTION_SIM_IMPORT,
        {
            "run_id": priors.run_id,
            "rows": len(priors.rows),
            "sha256": sha,
            "overrides": sorted(body.gate_overrides),
            "gate": {k: v.get("weight") for k, v in priors.gate.items()},
        },
    )
    return {
        "run": summary,
        "id": str(run.id),
        "gate_decisions": {
            k: {
                "weight": v.get("weight"),
                "status": v.get("status"),
                "override": bool(v.get("override")),
            }
            for k, v in priors.gate.items()
        },
    }


@router.post(f"{BASE}/learning/run")
async def ops_learning_run(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        report = await reco.run_learning(session, shop_id, now=_now())
    out = report.json()
    await _audited(session, ctx, shop_id, ACTION_LEARNING, out)
    return out


@router.post(f"{BASE}/learning/backfill")
async def ops_backfill(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        report = await reco.apply_backfill(session, shop_id, now=_now())
    out = report.json()
    await _audited(session, ctx, shop_id, ACTION_BACKFILL, out)
    return out
