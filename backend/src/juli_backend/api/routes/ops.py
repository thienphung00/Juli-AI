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
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
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
    REVIEWER_DENIED_HEADER,
    Unauthorized,
    bearer_scheme,
    load_authenticated_user,
    verify_access_jwt,
    verify_bearer_token,
)
from juli_backend.database import Shop, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ops import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from juli_backend.services.ops import (
    OpsRoleMissing,
    ShopListing,
    audit,
    disconnect,
    invites,
    mask_pii,
    ops_role,
    overview,
    runs,
    scenarios,
    simulation,
    view_as,
)
from juli_backend.services.ops import settings as ops_settings
from juli_backend.services.ops import staff as ops_staff
from juli_backend.services.shop_diagnosis import Channel, Metric, Ranking

logger = logging.getLogger(__name__)


class MaskedRoute(APIRoute):
    """Re-serialises every JSON response with buyer PII masked (D25.6).

    Also turns :class:`OpsRoleMissing` (the runtime DB role lacks ``juli_ops``
    membership, so ``SET LOCAL ROLE juli_ops`` was refused) into a 503 naming
    the exact ``GRANT`` to run, logged once per request as ``ops_role_missing``.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except OpsRoleMissing as exc:
                logger.error(
                    "ops_role_missing", extra={"db_role": exc.role, "path": request.url.path}
                )
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": exc.detail}
                )
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
    user: ops_staff.OpsUser


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


async def get_ops_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> ops_staff.OpsUser:
    """Gate 2: the Supabase JWT, verified on EVERY request; the users row cached.

    P29: the token goes through ``verify_bearer_token`` -- the very code
    ``get_current_user`` runs -- every time. Only the ``users`` read behind it
    (four round trips, ~1.6 s from the VPS) is skipped when this verified
    ``sub`` resolved to an active staff member in the last 60 s
    (``ops_staff.cached_user``). On a miss it is ``get_current_user``'s own
    database half, commit included.
    """
    token = await verify_bearer_token(credentials)
    if token.is_reviewer:
        # P32-A (D42): a partner reviewer never reaches the staff console, whatever
        # its e-mail domain or staff table says.
        logger.warning("ops_reviewer_refused", extra={"user_id": str(token.user_id)})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
            headers={REVIEWER_DENIED_HEADER: "read_only"},
        )
    hit = ops_staff.cached_user(token.user_id)
    if hit is not None:
        return hit
    user = await load_authenticated_user(session, token)
    return ops_staff.OpsUser(id=user.id, email=user.email)


async def get_ops_context(
    access_email: str | None = Depends(require_cf_access),
    user: ops_staff.OpsUser = Depends(get_ops_user),
    session: AsyncSession = Depends(get_session),
) -> OpsContext:
    """Gates 2–3: a signed-in user with an active staff row matching Access.

    P22: the staff row is cached in-process for 60 s (``ops_staff.cached_staff``
    -- see there for the cross-worker trade-off), so the common request makes
    no database call here at all. On a miss the read stays in the request's
    transaction and is committed only when it wrote (a first-sight
    ``user_id`` binding); a read-only resolution costs no COMMIT.

    P29: with the users read cached too (``get_ops_user``), a warm Ops request
    reaches its route having made no round trip at all. The user is cached
    only here, once the request resolved to an active member.
    """
    # Plain values, read once: a rollback below would expire an ORM `User`
    # (tests pass one), and an expired attribute is a lazy load an async
    # session cannot do.
    user_id, user_email = user.id, user.email
    ops_user = ops_staff.OpsUser(
        id=user_id, email=user_email, cached=bool(getattr(user, "cached", False))
    )
    member = ops_staff.cached_staff(user_id, user_email)
    if member is None:
        member = await ops_staff.resolve_staff(session, user_id=user_id, email=user_email)
        if member is None:
            await session.rollback()
            logger.warning("ops_not_staff", extra={"user_id": str(user_id)})
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if access_email is not None and access_email != member.email:
            await session.rollback()
            logger.warning("ops_access_email_mismatch", extra={"staff_id": str(member.id)})
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if member.newly_bound:
            await session.commit()  # persists the first-sight user_id binding
        ops_staff.remember_staff(user_id, user_email, member)
    elif access_email is not None and access_email != member.email:
        logger.warning("ops_access_email_mismatch", extra={"staff_id": str(member.id)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if member.active:
        ops_staff.remember_user(ops_user)
    return OpsContext(staff=member, user=ops_user)


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


async def _shop_and_settings(session: AsyncSession, shop_id: uuid.UUID) -> tuple[ShopListing, Any]:
    """The listing and its ``ops_shop_settings`` row in one statement (P29); 404 if none."""
    listing, row = await overview.find_shop_and_settings(session, shop_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return listing, row


@asynccontextmanager
async def shop_then_scope(
    session: AsyncSession, shop_id: uuid.UUID, *, transaction_ends_after: bool = False
) -> AsyncIterator[ShopListing]:
    """``_shop`` (404), then the shop's own scope -- one round trip fewer (P29).

    The ops block hands its role restore to the scope's first statement, as
    ``_view_shop`` does. ``transaction_ends_after``: see ``with_shop_scope``;
    only when the block is the request's last database work.
    """
    async with ops_role(session) as block:
        listing = await _shop(session, shop_id)
        previous_role = block.hand_over()
    async with with_shop_scope(
        session,
        shop_id,
        restore_role=previous_role,
        transaction_ends_after=transaction_ends_after,
    ):
        yield listing


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
    """Tổng quan from the daily summaries (D27.1); a shop without one is computed once."""
    body = await overview.build_overview(session, transaction_ends_after=True)
    await session.commit()
    return body


@router.post("/overview/refresh")
async def ops_overview_refresh(
    ctx: OpsContext = Depends(operator), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """ "Làm mới" (D27.1): recompute every shop's summary now; same body as GET."""
    body = await overview.build_overview(session, refresh=True)
    await audit.record(
        session, ctx.staff.actor, audit.ACTION_DATA_REFRESH, after={"target": "overview"}
    )
    await session.commit()
    return body


@router.get("/runtime-env")
async def ops_runtime_env(ctx: OpsContext = Depends(viewer)) -> dict[str, Any]:
    """Which env a connected shop needs is missing / which flags are off (P61-D, D71.4).

    The API process's view (the worker logs the same report at its own boot as
    ``runtime_env_report``). Names and booleans only -- never a value.
    """
    from juli_backend.core.config import runtime_env_report

    return runtime_env_report("api").to_json()


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
    # P29: the request's last statement; the role dies with the transaction.
    async with ops_role(session, transaction_ends_after=True):
        members = await ops_staff.list_staff(session)
    return {"data": [_staff_json(m) for m in members]}


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
        "kind": audit.kind_of(row.action),
        "field": row.field,
        "merged_count": row.merged_count or 1,
        "before": row.before,
        "after": row.after,
    }


@router.get("/audit")
async def ops_audit(
    shop_id: uuid.UUID | None = Query(default=None),
    kind: Literal["config", "view", "system"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async with ops_role(session, transaction_ends_after=True):
        rows = await audit.list_entries(session, shop_id=shop_id, kind=kind, limit=limit)
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
    # One ops block for the ops reads (P22): ops_role is re-entrant, so each
    # service's own block is free in here. P29: the listing and the settings
    # row are one statement. Only the cap needs the shop's scope, after.
    async with ops_role(session) as block:
        listing, row = await _shop_and_settings(session, shop_id)
        shop_invites = await invites.list_invites(session, shop_id)
        log = await audit.list_entries(session, shop_id=shop_id, limit=20)
        previous_role = block.hand_over()
    # P29: the cap and tunables are cached for 30 s per shop. On a miss the
    # role switch back rides on the scope's first statement, and the scope is
    # not restored: the only statement that can follow is the card-cell read,
    # under its own scope for this same shop. On a hit no statement runs and
    # the role is still juli_ops -- harmless when the transaction ends here,
    # handed to the card-cell scope otherwise.
    cap, tunables, used_restore = await ops_settings.cap_and_tunables(
        session, shop_id, restore_role=previous_role, transaction_ends_after=True
    )
    view = ops_settings.view_from(shop_id, row, cap, tunables)
    body: dict[str, Any] = {
        "shop": _shop_json(listing),
        "settings": view.to_json(),
        "invites": [invites.invite_json(i) for i in shop_invites],
        "audit": [_audit_json(r) for r in log],
    }
    if view.overrides.get("card_quota_mode") is True:
        # D33: open cards per cell, read only for a shop in the quota mode.
        body["card_cells"] = await _card_cells_quietly(
            session, shop_id, restore_role=None if used_restore else previous_role
        )
    return body


async def _card_cells_quietly(
    session: AsyncSession, shop_id: uuid.UUID, *, restore_role: str | None = None
) -> dict[str, int] | None:
    """Cell (target metric × channel) -> open cards; ``None`` when the read fails.

    The request's last database work (P29: no scope restore on the way out).
    ``restore_role``: an ``ops_role`` restore nobody has run yet.
    """
    from juli_backend.services.action_cards import open_cell_counts

    try:
        async with with_shop_scope(
            session, shop_id, restore_role=restore_role, transaction_ends_after=True
        ):
            return await open_cell_counts(session, shop_id)
    except Exception:
        logger.warning("ops_card_cells_read_failed", extra={"shop_id": str(shop_id)})
        return None


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
    admin_only = sorted(set(body.changes) & ops_settings.ADMIN_ONLY_FIELDS)
    if admin_only and not ctx.staff.at_least(ROLE_ADMIN):
        # D29.11: the diagnosis / KPI tunables are an Admin's to change.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin only: {', '.join(admin_only)}",
        )
    try:
        view = await ops_settings.update_settings(session, ctx.staff.actor, shop_id, body.changes)
    except ops_settings.SettingsError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    ops_settings.forget_cap_and_tunables(shop_id)  # P29: after the COMMIT too
    await _refresh_summary_quietly(session, shop_id)
    return {"settings": view.to_json()}


async def _refresh_summary_quietly(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """A settings change (e.g. the OpenAI cap) shows in Tổng quan at once; never fails."""
    try:
        await overview.refresh_shop_summary(session, shop_id)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning("ops_summary_refresh_failed", extra={"shop_id": str(shop_id)})


@router.post("/shops/{shop_id}/settings/reset")
async def ops_reset_settings(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    view = await ops_settings.reset_overrides(
        session,
        ctx.staff.actor,
        shop_id,
        include_admin_fields=ctx.staff.at_least(ROLE_ADMIN),
    )
    await session.commit()
    ops_settings.forget_cap_and_tunables(shop_id)  # P29: after the COMMIT too
    await _refresh_summary_quietly(session, shop_id)
    return {"settings": view.to_json()}


# -- runs (read-only, D25.9) -----------------------------------------------------------


@router.get("/shops/{shop_id}/runs")
async def ops_list_runs(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async with shop_then_scope(session, shop_id, transaction_ends_after=True):
        data = await runs.list_runs(session, shop_id)
    return {"data": data}


@router.get("/shops/{shop_id}/runs/{run_id}")
async def ops_run_detail(
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        async with shop_then_scope(session, shop_id, transaction_ends_after=True):
            data = await runs.run_detail(session, shop_id, run_id)
    except runs.RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found") from None
    return {"data": data}


# -- card groups (P30, D34 / D39.3; P36, D45: Ops groups) ------------------------------


ACTION_CARD_GROUP_CREATE = "card_group_create"
ACTION_CARD_GROUP_REASON = "card_group_reason"


async def _groups_body(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    """The shop's groups; D52 (P45): every comparison's ``eb`` re-shrunk with the pooled prior.

    The cross-shop draws are read in the ``juli_ops`` block (``ops_group_lift_draws()``,
    migration 093) that ``_shop`` already opens -- one statement more -- then the shop's
    own groups under its tenant scope. Only aggregates of the other shops' groups (prior
    mean, spread, number of shops) reach the response.

    D76 / D11 / D17 (ADR-116 §3): the draws are only of shops holding an open
    ``pooled_training`` grant (migration 107), and a viewed shop without one borrows
    nothing -- its comparisons use its own data (prior ``own``; Ops says so). D14 picks
    the cell (``apply_pooled_eb``). D15: this is a query-time figure (nothing is stored),
    so the contributing set is logged (``pooled_contributor_set``, shop ids only).
    """
    from juli_backend.models.consent import POOLED_TRAINING
    from juli_backend.services.action_cards import card_groups, group_views
    from juli_backend.services.consent import (
        FIGURE_OPS_GROUP_PRIOR,
        CellCheck,
        contributing_set,
        has_consent,
        log_contributing_set,
    )
    from juli_backend.services.shop_rules import diag_tunables

    async with ops_role(session) as block:
        await _shop(session, shop_id)
        draws = await card_groups.lift_draws(session)
        previous_role = block.hand_over()
    async with with_shop_scope(
        session, shop_id, restore_role=previous_role, transaction_ends_after=True
    ):
        tunables = await diag_tunables(session, shop_id)
        groups = await group_views(session, shop_id, tunables=tunables)
        pooled = await has_consent(session, shop_id, POOLED_TRAINING)
    used: dict[str, CellCheck] = {}
    groups = card_groups.apply_pooled_eb(
        groups,
        draws,
        pooled=pooled,
        min_groups=tunables.group_eb_min_groups,
        default_sd=tunables.group_eb_prior_sd,
        used_cells=used,
    )
    if used:
        log_contributing_set(
            contributing_set(FIGURE_OPS_GROUP_PRIOR, list(used.values())),
            applied_shop_id=shop_id,
            persisted=False,
        )
    return {"enabled": tunables.groups_enabled, "groups": groups}


@router.get("/shops/{shop_id}/groups")
async def ops_card_groups(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The shop's card groups: key, arms, launch / release, seed and day-14 verdict.

    D45 (P36): plus each group's design (source, reason, CTR guard) and plan (the
    weekly-drift floor of the 90 % interval and the traffic needed).
    """
    return await _groups_body(session, shop_id)


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lever: str = "pack_option"
    metric: str = "aov"
    channel: str = "total"
    product_ids: list[str]
    reason: str | None = None
    #: The product-card CTR guard (D45.2); ``None`` = on unless the metric is CTR.
    guard: bool | None = None
    #: D45.8: draw within order-volume strata (high / low, 30-day orders).
    stratify: bool = False


@router.post("/shops/{shop_id}/groups")
async def ops_create_card_group(
    shop_id: uuid.UUID,
    body: GroupCreate,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """D45.1: create a D34 group in Ops (e.g. "Quy cách mới" on 4 + 2 products).

    The seeded ≈ 1/3 control draw as for card groups; no card is made and nothing is
    written to TikTok -- the owner changes the treated products himself. Audited.
    """
    from juli_backend.services.action_cards import GroupError, card_groups

    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            group = await card_groups.create_ops_group(
                session,
                shop_id,
                lever=body.lever,
                metric=body.metric,
                channel=body.channel,
                product_ids=body.product_ids,
                reason=body.reason,
                guard=body.guard,
                created_by=ctx.staff.email,
                now=datetime.now(UTC),
                stratify=body.stratify,
            )
            after = {
                "group_id": str(group.id),
                "key": group.group_key,
                "launched_on": group.launched_on.isoformat(),
                "seed": group.seed,
                "products": sorted(body.product_ids),
                "reason": (group.design or {}).get("reason"),
                "guard": (group.design or {}).get("guard"),
                "strata": (group.design or {}).get("strata"),
            }
        await audit.record(
            session, ctx.staff.actor, ACTION_CARD_GROUP_CREATE, shop_id=shop_id, after=after
        )
        await session.commit()
    except GroupError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        await session.rollback()
        raise
    payload = await _groups_body(session, shop_id)
    payload["created"] = after["group_id"]
    return payload


class GroupReasonWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None


@router.patch("/shops/{shop_id}/groups/{group_id}")
async def ops_set_card_group_reason(
    shop_id: uuid.UUID,
    group_id: uuid.UUID,
    body: GroupReasonWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """D45.3: the group's one-line "lý do chọn thử nghiệm" (manual entry). Audited."""
    from juli_backend.services.action_cards import GroupError, card_groups

    await _shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id):
            _group, before, after = await card_groups.set_group_reason(
                session, shop_id, group_id, body.reason
            )
        if before != after:
            await audit.record(
                session,
                ctx.staff.actor,
                ACTION_CARD_GROUP_REASON,
                shop_id=shop_id,
                field=f"group:{group_id}",
                before={"group_id": str(group_id), "reason": before},
                after={"group_id": str(group_id), "reason": after},
            )
        await session.commit()
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Group not found") from None
    except GroupError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        await session.rollback()
        raise
    return await _groups_body(session, shop_id)


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
    """Log opening / leaving "Xem như shop" (every session is logged).

    One transaction (P22): the listing, the stage and the audit row in one ops
    block, the audit row committed at the end. A failure anywhere rolls the
    audit row back with it -- and then no session was opened to log.
    """
    # P29: the COMMIT below ends the transaction -- no role restore before it.
    async with ops_role(session, transaction_ends_after=True):
        listing, row = await _shop_and_settings(session, shop_id)
        await audit.record(
            session,
            ctx.staff.actor,
            f"view_as_{body.mode}",
            shop_id=shop_id,
            after={"mode": body.mode},
        )
    await session.commit()
    stage = row.stage if row is not None else "trial"
    return {"shop": _shop_json(listing), "stage": stage, "read_only": True}


async def _view_shop(session: AsyncSession, shop_id: uuid.UUID) -> Shop:
    # P29: the ops read, the switch back from juli_ops AND the seller's tenant
    # GUCs are ONE statement; shared with the partner reviewer path (P32-A,
    # ``services/ops/view_as.py``).
    shop = await view_as.enter_shop_read_scope(session, shop_id)
    if shop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    return shop


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
    request: Request,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    shop = await _view_shop(session, shop_id)
    return await demo_decisions.list_demo_decisions(request=request, session=session, shop=shop)


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
    return await agent_runs.runs_list_response(shop=shop, session=session, limit=limit)


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


# -- "Quy tắc" in Cài đặt shop (D25.14): staff set the seller's rules up first -----------


async def _rule_snapshot(
    session: AsyncSession, shop_id: uuid.UUID, rule_key: str, scope_ref: str | None
) -> Any:
    from sqlalchemy import select

    from juli_backend.models.run_changes import ShopRule

    row = (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == rule_key,
                ShopRule.scope_ref == (scope_ref or "").strip(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {"value": row.value, "set_by": row.set_by}


@router.get("/shops/{shop_id}/rules")
async def ops_get_rules(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """The shop's rules exactly as the seller's Quy tắc page reads them."""
    shop = await _view_shop(session, shop_id)
    return await demo_rules.get_shop_rules(shop=shop, session=session)


@router.put("/shops/{shop_id}/rules/{rule_key}")
async def ops_put_rule(
    shop_id: uuid.UUID,
    rule_key: str,
    body: demo_rules.RuleWriteRequest,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Set one seller rule as the team (same storage and validation as the seller's).

    The rule row and its audit row are written in ONE transaction: a failure
    between them rolls both back, so no rule change is ever left unaudited.
    """
    from juli_backend.services import shop_rules

    shop = await _view_shop(session, shop_id)
    before = await _rule_snapshot(session, shop_id, rule_key, body.scope_ref)
    try:
        row = await shop_rules.set_rule(
            session,
            shop.id,
            rule_key=rule_key,
            scope_ref=body.scope_ref,
            value=body.value,
            set_by="team",
            set_by_user_id=ctx.user.id,
        )
        await audit.record(
            session,
            ctx.staff.actor,
            "rule_set",
            shop_id=shop_id,
            field=f"{rule_key}:{(body.scope_ref or '').strip()}",
            before={"rule_key": rule_key, "scope_ref": body.scope_ref, "rule": before},
            after={
                "rule_key": rule_key,
                "scope_ref": body.scope_ref,
                "rule": {"value": row.value, "set_by": "team"},
            },
        )
        await session.commit()
    except shop_rules.RuleValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "ops_shop_rule_set",
        extra={"shop_id": str(shop_id), "rule_key": rule_key, "staff_id": str(ctx.staff.id)},
    )
    return demo_rules.RuleWriteResponse(
        data=demo_rules.RuleWriteData(
            rule_key=row.rule_key,
            scope_ref=row.scope_ref,
            value=row.value,
            set_by=row.set_by,
            set_by_user_id=row.set_by_user_id,
            set_at=row.set_at,
        )
    )


@router.delete("/shops/{shop_id}/rules/{rule_key}", status_code=204)
async def ops_delete_rule(
    shop_id: uuid.UUID,
    rule_key: str,
    scope_ref: str | None = Query(default=None),
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Unset one seller rule; the delete and its audit row commit together."""
    from juli_backend.services import shop_rules

    shop = await _view_shop(session, shop_id)
    before = await _rule_snapshot(session, shop_id, rule_key, scope_ref)
    try:
        existed = await shop_rules.delete_rule(
            session, shop.id, rule_key=rule_key, scope_ref=scope_ref
        )
        if not existed:
            await session.rollback()
            raise HTTPException(status_code=404, detail="Rule not set")
        await audit.record(
            session,
            ctx.staff.actor,
            "rule_unset",
            shop_id=shop_id,
            before={"rule_key": rule_key, "scope_ref": scope_ref, "rule": before},
            after=None,
        )
        await session.commit()
    except shop_rules.RuleValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "ops_shop_rule_unset",
        extra={"shop_id": str(shop_id), "rule_key": rule_key, "staff_id": str(ctx.staff.id)},
    )
    return Response(status_code=204)


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


async def _fill_compact_from_reports(
    session: AsyncSession, shop_id: uuid.UUID, *, latest_only: bool
) -> int:
    """Re-derive the compact daily rows from the stored report JSON (D27.2)."""
    from datetime import date, timedelta

    from juli_backend.services.shop_diagnosis_daily import compact

    since = date.today() - timedelta(days=simulation.HISTORY_DAYS)
    async with with_shop_scope(session, shop_id):
        written = await compact.rebuild_from_stored_reports(
            session, shop_id, since=since, latest_only=latest_only
        )
    await session.commit()
    return written


async def _simulation_body(
    session: AsyncSession, shop_id: uuid.UUID, window: int
) -> dict[str, Any]:
    """The simulation page: one ops block, then one shop scope (P22).

    Was five role switches / scopes and a COMMIT in between; the ops reads
    (listing, stage, scenarios) now share one block and the tenant reads
    (history, the one-time fill, the cap) one scope. The fill commits only when
    it actually wrote rows.
    """
    from datetime import date, timedelta

    from juli_backend.services.shop_diagnosis_daily import compact

    async with ops_role(session) as block:
        listing, row = await _shop_and_settings(session, shop_id)  # P29: one statement
        saved = await scenarios.list_scenarios(session, shop_id)
        window = _window(window)  # after the 404, as before
        previous_role = block.hand_over()
    written = 0
    # The role switch back rides on the scope's first statement. P29: the
    # scope is the request's last database work (a fill commits right after),
    # so it is not restored.
    async with with_shop_scope(
        session, shop_id, restore_role=previous_role, transaction_ends_after=True
    ):
        payload = simulation.baseline(await simulation.load_history(session, shop_id), window)
        if payload["status"]["history_days"] == 0:
            # Reports stored before migration 085 are not in the compact table yet:
            # fill it once from them (no TikTok call), then read again.
            since = date.today() - timedelta(days=simulation.HISTORY_DAYS)
            written = await compact.rebuild_from_stored_reports(
                session, shop_id, since=since, latest_only=False
            )
            if written:
                history = await simulation.load_history(session, shop_id)
                payload = simulation.baseline(history, window)
        # P29: cached 30 s per shop (shared with the settings page), else one read.
        cap, _tunables = await ops_settings.cap_and_tunables_in_scope(session, shop_id)
    if written:
        await session.commit()
    settings_view = ops_settings.view_from(shop_id, row, cap)
    values = simulation.baseline_values(payload)
    scenario_rows = []
    for saved_row in saved:
        item = scenarios.to_json(saved_row)
        try:
            item["result"] = simulation.simulate(values, saved_row.deltas or {})
        except simulation.SimulationError:
            item["result"] = None
        scenario_rows.append(item)
    # Reports stored before P16 carry no per-day streams, and the latest day's report
    # already exists, so only a FORCED rebuild refills it (the task holds a lock and
    # allows one forced build per shop per 6 h).
    rebuilding = False
    if payload["status"]["history_days"] == 0:
        from juli_backend.workers.tasks import shop_diagnosis as diagnosis_tasks

        rebuilding = diagnosis_tasks.enqueue_shop_diagnosis(str(shop_id), force=True) is not None
    return {
        "shop": _shop_json(listing),
        "stage": settings_view.stage,
        **payload,
        "rebuilding": rebuilding,
        "scenarios": scenario_rows,
    }


@router.get("/shops/{shop_id}/simulation")
async def ops_simulation(
    shop_id: uuid.UUID,
    window: int = Query(default=simulation.DEFAULT_WINDOW),
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _simulation_body(session, shop_id, window)


@router.post("/shops/{shop_id}/simulation/refresh")
async def ops_simulation_refresh(
    shop_id: uuid.UUID,
    window: int = Query(default=simulation.DEFAULT_WINDOW),
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """ "Làm mới" (D27.1): this shop's compact rows from its latest stored report and
    its Tổng quan summary, recomputed now; same body as GET simulation."""
    listing = await _shop(session, shop_id)
    checked = _window(window)
    await _fill_compact_from_reports(session, shop_id, latest_only=True)
    await overview.refresh_shop_summary(session, shop_id)
    await audit.record(
        session,
        ctx.staff.actor,
        audit.ACTION_DATA_REFRESH,
        shop_id=shop_id,
        after={"target": "simulation", "window": checked},
    )
    await session.commit()
    return await _simulation_body(session, listing.shop_id, checked)


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
    return {
        "result": result,
        "actions": simulation.actions_for(body.deltas),
        # D28: per changed cell, low_data / in_noise / measurable on the window band.
        "verdicts": simulation.verdicts(payload, body.deltas),
    }


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
    # P29: one ops block for both reads, no restore -- the request ends here.
    async with ops_role(session, transaction_ends_after=True):
        await _shop(session, shop_id)
        rows = await invites.list_invites(session, shop_id)
    return {"data": [invites.invite_json(i) for i in rows]}
