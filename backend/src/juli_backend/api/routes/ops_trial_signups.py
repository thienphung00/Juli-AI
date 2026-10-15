"""Juli Ops tab "Đăng ký dùng thử" (fast track P33-F, D43): the app-juli.com sign-ups.

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same gates, in
the same order, fail closed: Cloudflare Access → Supabase JWT → active
``ops_staff`` row matching Access → role. Both routes need **Vận hành**
(operator) or Admin: the list carries the prospect's phone and e-mail, which the
team needs to call them back.

- ``GET   /v1/ops/trial-signups?status=&limit=`` -- newest first + count per status.
- ``PATCH /v1/ops/trial-signups/{id}`` ``{"status": new|contacted|converted|spam}`` --
  stamps ``handled_by`` / ``handled_at``; audited ``trial_signup_status``
  (``field = "trial_signup:<id>"``, before/after = the status only).

PRIVACY. These responses are NOT passed through ``mask_pii``: D25.6 masks
*buyer* data of connected shops; a sign-up is a prospect who gave Juli these
details to be contacted (privacy policy, "Đăng ký dùng thử"). The route class
still turns a missing ``juli_ops`` grant into the 503 every Ops route gives.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import OpsContext, operator
from juli_backend.database import get_session
from juli_backend.models.trial_signups import SIGNUP_STATUS_LABELS, SIGNUP_STATUSES
from juli_backend.services import trial_signups as signups
from juli_backend.services.ops.access import OpsRoleMissing

logger = logging.getLogger(__name__)


class OpsUnmaskedRoute(APIRoute):
    """``MaskedRoute``'s 503 on a missing ``juli_ops`` grant, without the masking."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except OpsRoleMissing as exc:
                logger.error(
                    "ops_role_missing", extra={"db_role": exc.role, "path": request.url.path}
                )
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": exc.detail}
                )

        return handler


router = APIRouter(prefix="/ops", tags=["ops"], route_class=OpsUnmaskedRoute)

StatusName = Literal["new", "contacted", "converted", "spam"]


def _options() -> list[dict[str, str]]:
    return [{"value": s, "label": SIGNUP_STATUS_LABELS[s]} for s in SIGNUP_STATUSES]


@router.get("/trial-signups")
async def ops_list_trial_signups(
    status_filter: StatusName | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows, counts = await signups.list_signups(session, status=status_filter, limit=limit)
    body = {"data": [signups.to_json(r) for r in rows], "counts": counts, "statuses": _options()}
    await session.commit()
    return body


class StatusWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: StatusName


@router.patch("/trial-signups/{signup_id}")
async def ops_set_trial_signup_status(
    signup_id: uuid.UUID,
    payload: StatusWrite,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        row = await signups.set_status(session, signup_id, payload.status, ctx.staff.actor)
    except signups.SignupNotFound:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None
    body = {"data": signups.to_json(row)}
    await session.commit()
    logger.info(
        "trial_signup_status_set", extra={"signup_id": str(signup_id), "status": payload.status}
    )
    return body
