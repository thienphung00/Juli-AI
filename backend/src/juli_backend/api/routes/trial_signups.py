"""``POST /v1/trial-signups`` -- the public free-trial sign-up (fast track P33-F, D43).

NO AUTH, by nature: a visitor on app-juli.com/dang-ky asks to be contacted. The
landing's own server route (``apps/landing/src/app/dang-ky/gui/route.ts``) posts
here; with the shared ``TRIAL_SIGNUP_RELAY_KEY`` it also forwards the visitor's
IP (``X-Juli-Client-Ip``), otherwise the connection's address is used.

- JSON body: the form fields (name, contact number, e-mail, shop, role, optional
  note, consent, honeypot ``website``, optional ``source`` utm_* / referrer); at
  most 16 KB.
- 201 ``{"ok": true}`` -- stored and the team notified (after the response).
  A filled honeypot (``website``) gets the very same 201 and nothing is stored.
- 422 ``{"detail": "invalid", "errors": {field: Vietnamese message}}`` -- values
  are never echoed back.
- 429 ``{"detail": "<Vietnamese>"}`` -- per IP / e-mail / site-wide limit.
- 400 malformed JSON, 413 too large.

Logs carry the outcome and the row id only -- never the contact number, e-mail or name.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import get_session
from juli_backend.services import trial_signups as signups
from juli_backend.services.ops import OpsRoleMissing

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trial-signups"])

MAX_BODY_BYTES = 16 * 1024


def _json(code: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=code, content=body, headers={"Cache-Control": "no-store"})


@router.post("/trial-signups")
async def create_trial_signup(
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        return _json(status.HTTP_413_CONTENT_TOO_LARGE, {"detail": "too_large"})
    try:
        raw = json.loads(raw_body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return _json(status.HTTP_400_BAD_REQUEST, {"detail": "invalid_json"})
    if not isinstance(raw, dict):
        return _json(status.HTTP_400_BAD_REQUEST, {"detail": "invalid_json"})

    checked = signups.validate(raw)
    if checked.honeypot:
        logger.info("trial_signup_honeypot")
        return _json(status.HTTP_201_CREATED, {"ok": True})
    if checked.data is None:
        logger.info("trial_signup_invalid", extra={"fields": sorted(checked.errors)})
        return _json(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"detail": "invalid", "errors": checked.errors},
        )

    peer = request.client.host if request.client else None
    digest = signups.ip_hash(signups.client_ip(request.headers, peer))
    try:
        row = await signups.create_signup(session, checked.data, ip_digest=digest)
        snapshot = signups.to_json(row)
        await session.commit()
    except signups.RateLimited as exc:
        await session.rollback()
        logger.warning("trial_signup_rate_limited", extra={"scope": exc.scope})
        return _json(status.HTTP_429_TOO_MANY_REQUESTS, {"detail": signups.MSG_RATE_LIMITED})
    except OpsRoleMissing as exc:
        await session.rollback()
        logger.error("ops_role_missing", extra={"db_role": exc.role, "path": request.url.path})
        return _json(status.HTTP_503_SERVICE_UNAVAILABLE, {"detail": "unavailable"})
    logger.info(
        "trial_signup_created", extra={"signup_id": snapshot["id"], "role": snapshot["role"]}
    )
    background.add_task(signups.notify_team, snapshot)
    return _json(status.HTTP_201_CREATED, {"ok": True})
