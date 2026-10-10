"""Juli Ops console API, ``/v1/ops/*`` (fast track P16, DECISIONS D25).

AUTH -- every route, fail closed, in this order:
1. Cloudflare Access: the ``Cf-Access-Jwt-Assertion`` header is verified
   (``core/security/cf_access.py``: team certs, AUD, issuer, expiry,
   ``@app-juli.com``). Missing / invalid / unconfigured → 403. The only bypass
   is ``OPS_CF_ACCESS_BYPASS=1`` outside production (tests, local dev).
2. The Supabase JWT (``get_current_user``) → 401 when missing or invalid.
3. An active ``ops_staff`` row for that user (bound by verified e-mail on first
   sign-in) whose e-mail equals the Access e-mail → 403 otherwise.
4. The route's minimum role: Xem (viewer) < Vận hành (operator) < Admin.

PRIVACY. Every response is passed through ``services/ops/masking.mask_pii``
(the ``MaskedRoute`` route class): no buyer data reaches a staff screen.

WRITES (settings, scenarios, invites, staff, disconnect) are audited in
``ops_audit_log``. "Xem như shop" (D25.3, amended 2026-10-10) is ALWAYS
read-only: its GETs call the very handlers the seller's own routes use, under
that shop's tenant scope, so staff see exactly the seller's payloads; every
non-GET under ``/view/`` is refused with 403 and nothing acts for a seller.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import (
    agent_runs,
    demo_analysis,
    demo_decisions,
    demo_rules,
    demo_run_changes,
    demo_run_flows,
)
from juli_backend.core.security import (
    CF_ACCESS_HEADER,
    Unauthorized,
    get_current_user,
    verify_access_jwt,
)
from juli_backend.database import Shop, User, get_session
from juli_backend.database.tenant_context import (
    _apply_tenant_context_to_session,
    with_shop_scope,
)
from juli_backend.models.ops import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from juli_backend.services.ops import (
    ShopListing,
    audit,
    disconnect,
    invites,
    mask_pii,
    overview,
    runs,
    scenarios,
    simulation,
)
from juli_backend.services.ops import settings as ops_settings
from juli_backend.services.ops import staff as ops_staff
from juli_backend.services.shop_diagnosis import Channel, Metric, Ranking

logger = logging.getLogger(__name__)


class MaskedRoute(APIRoute):
    """Re-serialises every JSON response with buyer PII masked (D25.6)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            if response.media_type != "application/json" or not response.body:
                return response
            try:
                payload = json.loads(bytes(response.body))
            except ValueError:
                return response
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return JSONResponse(
                content=mask_pii(payload), status_code=response.status_code, headers=headers
            )

        return handler


router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)


# -- auth ------------------------------------------------------------------------


@dataclass(frozen=True)
class OpsContext:
    staff: ops_staff.StaffMember
    user: User


async def require_cf_access(
    assertion: str | None = Header(default=None, alias=CF_ACCESS_HEADER),
) -> str | None:
    """Gate 1. Returns the Access e-mail (None when bypassed in dev/tests)."""
    try:
        identity = await verify_access_jwt(assertion)
    except Unauthorized as exc:
        logger.warning("ops_cf_access_denied", extra={"reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from None
    return identity.email


async def get_ops_context(
    access_email: str | None = Depends(require_cf_access),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OpsContext:
    """Gates 2–3: a signed-in user with an active staff row matching Access."""
    member = await ops_staff.resolve_staff(session, user_id=user.id, email=user.email)
    if member is None:
        await session.rollback()
        logger.warning("ops_not_staff", extra={"user_id": str(user.id)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if access_email is not None and access_email != member.email:
        await session.rollback()
        logger.warning("ops_access_email_mismatch", extra={"staff_id": str(member.id)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    await session.commit()  # persists a first-sight user_id binding
    return OpsContext(staff=member, user=user)


def require_role(role: str) -> Callable[..., Awaitable[OpsContext]]:
    async def dependency(ctx: OpsContext = Depends(get_ops_context)) -> OpsContext:
        if not ctx.staff.at_least(role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role too low")
        return ctx

    return dependency


viewer = require_role(ROLE_VIEWER)
operator = require_role(ROLE_OPERATOR)
admin = require_role(ROLE_ADMIN)


async def _shop(session: AsyncSession, shop_id: uuid.UUID) -> ShopListing:
    listing = await overview.find_shop(session, shop_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return listing


# -- me, overview, staff, audit ----------------------------------------------------


@router.get("/me")
async def ops_me(ctx: OpsContext = Depends(viewer)) -> dict[str, Any]:
    return {
        "email": ctx.staff.email,
        "role": ctx.staff.role,
        "role_label": ctx.staff.role_label,
    }


@router.get("/overview")
async def ops_overview(
    ctx: OpsContext = Depends(viewer), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await overview.build_overview(session)


class StaffWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    role: Literal["viewer", "operator", "admin"]
    active: bool = True


def _staff_json(member: ops_staff.StaffMember) -> dict[str, Any]:
    return {
        "id": str(member.id),
        "email": member.email,
        "role": member.role,
        "role_label": member.role_label,
        "active": member.active,
        "signed_in": member.user_id is not None,
    }


@router.get("/staff")
async def ops_list_staff(
    ctx: OpsContext = Depends(admin), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return {"data": [_staff_json(m) for m in await ops_staff.list_staff(session)]}


@router.put("/staff")
async def ops_put_staff(
    body: StaffWrite,
    ctx: OpsContext = Depends(admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        member = await ops_staff.upsert_staff(
            session, ctx.staff, email=body.email, role=body.role, active=body.active
        )
    except ops_staff.StaffError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"data": _staff_json(member)}


def _audit_json(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "at": row.at.isoformat() if row.at else None,
        "actor_email": row.actor_email,
        "shop_id": str(row.shop_id) if row.shop_id else None,
        "action": row.action,
        "before": row.before,
        "after": row.after,
    }


@router.get("/audit")
async def ops_audit(
    shop_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await audit.list_entries(session, shop_id=shop_id, limit=limit)
    return {"data": [_audit_json(r) for r in rows]}


# -- shop settings -------------------------------------------------------------------


def _shop_json(listing: ShopListing) -> dict[str, Any]:
    return {
        "shop_id": str(listing.shop_id),
        "shop_name": listing.shop_name,
        "owner_email": listing.owner_email,
        "owned_by_team": (listing.owner_email or "").lower().endswith("@app-juli.com"),
        "staff_access_consent_at": listing.owner_consent_at.isoformat()
        if listing.owner_consent_at
        else None,
    }


@router.get("/shops/{shop_id}/settings")
async def ops_get_settings(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    view = await ops_settings.get_settings(session, shop_id)
    shop_invites = await invites.list_invites(session, shop_id)
    log = await audit.list_entries(session, shop_id=shop_id, limit=20)
    return {
        "shop": _shop_json(listing),
        "settings": view.to_json(),
        "invites": [invites.invite_json(i) for i in shop_invites],
        "audit": [_audit_json(r) for r in log],
    }


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: dict[str, Any]


@router.put("/shops/{shop_id}/settings")
async def ops_put_settings(
    shop_id: uuid.UUID,
    body: SettingsWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    try:
        view = await ops_settings.update_settings(session, ctx.staff.actor, shop_id, body.changes)
    except ops_settings.SettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"settings": view.to_json()}


@router.post("/shops/{shop_id}/settings/reset")
async def ops_reset_settings(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    view = await ops_settings.reset_overrides(session, ctx.staff.actor, shop_id)
    await session.commit()
    return {"settings": view.to_json()}


# -- runs (read-only, D25.9) -----------------------------------------------------------


@router.get("/shops/{shop_id}/runs")
async def ops_list_runs(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        data = await runs.list_runs(session, shop_id)
    return {"data": data}


@router.get("/shops/{shop_id}/runs/{run_id}")
async def ops_run_detail(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            data = await runs.run_detail(session, shop_id, run_id)
    except runs.RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found") from None
    return {"data": data}


# -- "Xem như shop" (D25.3, amended 2026-10-10: ALWAYS read-only) ------------------------


class ViewSessionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["view", "exit"] = "view"


@router.post("/shops/{shop_id}/view-session")
async def ops_view_session(
    shop_id: uuid.UUID,
    body: ViewSessionWrite,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Log opening / leaving "Xem như shop" (every session is logged)."""
    listing = await _shop(session, shop_id)
    await audit.record(
        session, ctx.staff.actor, f"view_as_{body.mode}", shop_id=shop_id, after={"mode": body.mode}
    )
    await session.commit()
    settings_view = await ops_settings.get_settings(session, shop_id)
    return {"shop": _shop_json(listing), "stage": settings_view.stage, "read_only": True}


async def _seller_scope(session: AsyncSession, listing: ShopListing) -> Shop:
    """Apply the shop's own tenant scope (shop + owner) and load the shop row."""
    await _apply_tenant_context_to_session(session, listing.shop_id, listing.owner_user_id)
    shop = await session.get(Shop, listing.shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


async def _view_shop(session: AsyncSession, shop_id: uuid.UUID) -> Shop:
    return await _seller_scope(session, await _shop(session, shop_id))


@router.get("/shops/{shop_id}/view/analysis")
async def ops_view_analysis(
    shop_id: uuid.UUID,
    ranking: Ranking = Query(Ranking.COMBINED_60D),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_analysis.get_demo_analysis(ranking=ranking, session=session, shop=shop)


@router.get("/shops/{shop_id}/view/analysis/rankings")
async def ops_view_ranking(
    shop_id: uuid.UUID,
    stream: Channel = Query(...),
    metric: Metric = Query(...),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_analysis.get_demo_metric_ranking(
        stream=stream, metric=metric, session=session, shop=shop
    )


@router.get("/shops/{shop_id}/view/decisions")
async def ops_view_decisions(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_decisions.list_demo_decisions(session=session, shop=shop)


@router.get("/shops/{shop_id}/view/rules")
async def ops_view_rules(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_rules.get_shop_rules(shop=shop, session=session)


@router.get("/shops/{shop_id}/view/runs")
async def ops_view_runs(
    shop_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await agent_runs.list_demo_runs(shop=shop, session=session, limit=limit)


@router.get("/shops/{shop_id}/view/runs/{run_id}")
async def ops_view_run(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_run_flows.get_demo_run(run_id=run_id, shop=shop, session=session)


@router.get("/shops/{shop_id}/view/runs/{run_id}/changes")
async def ops_view_run_changes(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_run_changes.get_run_changes(run_id=run_id, shop=shop, session=session)


@router.get("/shops/{shop_id}/view/runs/{run_id}/instructions")
async def ops_view_run_instructions(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_run_flows.get_run_instructions(run_id=run_id, shop=shop, session=session)


@router.get("/shops/{shop_id}/view/runs/{run_id}/measurement")
async def ops_view_run_measurement(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_run_flows.get_run_measurement(run_id=run_id, shop=shop, session=session)


@router.get("/shops/{shop_id}/view/revert-questions")
async def ops_view_revert_questions(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_run_changes.list_revert_questions(shop=shop, session=session)


@router.api_route(
    "/shops/{shop_id}/view/{rest:path}",
    methods=["POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def ops_view_refuses_writes(
    shop_id: uuid.UUID, rest: str, ctx: OpsContext = Depends(viewer)
) -> Response:
    """D25.3 (amended): "Xem như shop" never writes. Every non-GET is a 403."""
    logger.warning("ops_view_write_refused", extra={"staff_id": str(ctx.staff.id), "path": rest})
    raise HTTPException(status_code=403, detail="Xem như shop chỉ xem, không ghi được")


# -- "Huỷ kết nối" (D25.13, Admin only) ------------------------------------------------------


class DisconnectWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    confirm_name: str


@router.post("/shops/{shop_id}/disconnect")
async def ops_disconnect_shop(
    shop_id: uuid.UUID,
    body: DisconnectWrite,
    ctx: OpsContext = Depends(admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Revoke Juli's stored authorization, stop polling / cards, cancel pending runs.

    Idempotent: a second call changes nothing and says ``already_disconnected``.
    Audited with the reason. History, rules and measurements are kept.
    """
    listing = await _shop(session, shop_id)
    try:
        result = await disconnect.disconnect_shop(
            session, ctx.staff.actor, listing, reason=body.reason, confirm_name=body.confirm_name
        )
    except disconnect.DisconnectError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"data": result.to_json()}


# -- "Mô phỏng" (D25.10, D25.11) ------------------------------------------------------------


def _window(value: int) -> int:
    if value not in simulation.WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"window must be one of {', '.join(map(str, simulation.WINDOWS))}",
        )
    return value


async def _baseline(session: AsyncSession, shop_id: uuid.UUID, window: int) -> dict[str, Any]:
    async with with_shop_scope(session, shop_id):
        history = await simulation.load_history(session, shop_id)
    return simulation.baseline(history, window)


@router.get("/shops/{shop_id}/simulation")
async def ops_simulation(
    shop_id: uuid.UUID,
    window: int = Query(default=simulation.DEFAULT_WINDOW),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    payload = await _baseline(session, shop_id, _window(window))
    settings_view = await ops_settings.get_settings(session, shop_id)
    saved = await scenarios.list_scenarios(session, shop_id)
    values = simulation.baseline_values(payload)
    scenario_rows = []
    for row in saved:
        item = scenarios.to_json(row)
        try:
            item["result"] = simulation.simulate(values, row.deltas or {})
        except simulation.SimulationError:
            item["result"] = None
        scenario_rows.append(item)
    return {
        "shop": _shop_json(listing),
        "stage": settings_view.stage,
        **payload,
        "scenarios": scenario_rows,
    }


class SimulateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: int = simulation.DEFAULT_WINDOW
    deltas: dict[str, dict[str, int]] = {}


@router.post("/shops/{shop_id}/simulation/compute")
async def ops_simulate(
    shop_id: uuid.UUID,
    body: SimulateBody,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    payload = await _baseline(session, shop_id, _window(body.window))
    try:
        result = simulation.simulate(simulation.baseline_values(payload), body.deltas)
    except simulation.SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"result": result, "actions": simulation.actions_for(body.deltas)}


class ScenarioWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    deltas: dict[str, dict[str, int]] | None = None
    is_target: bool | None = None


@router.post("/shops/{shop_id}/scenarios", status_code=201)
async def ops_create_scenario(
    shop_id: uuid.UUID,
    body: ScenarioWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    try:
        row = await scenarios.create_scenario(
            session,
            ctx.staff.actor,
            shop_id,
            name=body.name,
            deltas=body.deltas or {},
            is_target=bool(body.is_target),
        )
    except simulation.SimulationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"data": scenarios.to_json(row)}


@router.patch("/shops/{shop_id}/scenarios/{scenario_id}")
async def ops_update_scenario(
    shop_id: uuid.UUID,
    scenario_id: uuid.UUID,
    body: ScenarioWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        row = await scenarios.update_scenario(
            session,
            ctx.staff.actor,
            shop_id,
            scenario_id,
            name=body.name,
            deltas=body.deltas,
            is_target=body.is_target,
        )
    except scenarios.ScenarioNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Scenario not found") from None
    except simulation.SimulationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {"data": scenarios.to_json(row)}


@router.delete("/shops/{shop_id}/scenarios/{scenario_id}", status_code=204)
async def ops_delete_scenario(
    shop_id: uuid.UUID,
    scenario_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await scenarios.delete_scenario(session, ctx.staff.actor, shop_id, scenario_id)
    except scenarios.ScenarioNotFound:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Scenario not found") from None
    await session.commit()
    return Response(status_code=204)


# -- "Mời seller" (D25.7, P9-B) ---------------------------------------------------------------


class InviteWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    keep_ops_access: bool = True


@router.post("/shops/{shop_id}/invites", status_code=201)
async def ops_create_invite(
    shop_id: uuid.UUID,
    body: InviteWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    listing = await _shop(session, shop_id)
    try:
        created = await invites.create_invite(
            session,
            ctx.staff.actor,
            listing,
            email=body.email,
            keep_ops_access=body.keep_ops_access,
        )
    except invites.InviteError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    return {
        "data": invites.invite_json(created.invite),
        "email_sent": created.email_sent,
        # Staff forward this themselves when no mail was sent. Not masked: it
        # carries no buyer data, and only the invited e-mail can redeem it.
        "accept_url": created.accept_url,
    }


@router.get("/shops/{shop_id}/invites")
async def ops_list_invites(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    return {"data": [invites.invite_json(i) for i in await invites.list_invites(session, shop_id)]}
