"""The seller's side of the P9-B handover (D25.7): preview and accept an invite.

Both need the seller signed in (``get_current_user``); the invite only works for
the e-mail it was sent to. Accepting moves the shop to the seller's account and
keeps its cards, runs, rules and history (``services/ops/invites.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import User, get_session
from juli_backend.services.ops import invites

router = APIRouter(prefix="/shop-invites", tags=["shop-invites"])

_STATUS = {
    "invalid_token": 404,
    "already_accepted": 409,
    "expired": 410,
    "wrong_account": 403,
    "invalid_email": 422,
}


def _error(exc: invites.InviteError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 400), detail=exc.code)


@router.get("/preview")
async def preview_shop_invite(
    token: str = Query(..., min_length=20, max_length=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return {"data": await invites.preview_invite(session, token, user)}
    except invites.InviteError as exc:
        raise _error(exc) from None


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    keep_ops_access: bool = False


@router.post("/accept")
async def accept_shop_invite(
    body: AcceptBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await invites.accept_invite(
            session, body.token, user, keep_ops_access=body.keep_ops_access
        )
    except invites.InviteError as exc:
        await session.rollback()
        raise _error(exc) from None
    await session.commit()
    return {"data": result}
