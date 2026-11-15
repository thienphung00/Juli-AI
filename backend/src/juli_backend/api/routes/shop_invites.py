"""The seller's side of the shop invite (D25.7, P93): preview and accept.

Both need the seller signed in (``get_current_user``); the invite only works for
the e-mail it was sent to. Accepting adds the person to the shop team (P93); a shop
with no member yet is also handed to them (P9-B). Cards, runs, rules and history are
kept (``services/ops/invites.py``). P101 W1: the same two endpoints read a BUSINESS invite (sent
by a business owner, ``/v1/businesses/{id}/invites``) when the token is not a shop invite, so the
one ``/nhan-shop`` page serves both; accepting it makes the person a member of the business.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import User, get_session
from juli_backend.services import businesses
from juli_backend.services.ops import invites

router = APIRouter(prefix="/shop-invites", tags=["shop-invites"])

_STATUS = {
    "invalid_token": 404,
    "already_accepted": 409,
    "expired": 410,
    "wrong_account": 403,
    "invalid_email": 422,
}


def _error(exc: invites.InviteError | businesses.BusinessError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 400), detail=exc.code)


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


@router.post("/preview")
async def preview_shop_invite(
    body: PreviewBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Read-only: what the invite is for (the token travels in the body, never a URL)."""
    try:
        return {"data": await invites.preview_invite(session, body.token, user)}
    except invites.InviteError as exc:
        if exc.code != "invalid_token":
            raise _error(exc) from None
    business_invite = await businesses.find_invite(session, body.token)
    if business_invite is None:
        raise HTTPException(status_code=_STATUS["invalid_token"], detail="invalid_token")
    try:
        return {"data": await businesses.preview_invite(session, business_invite, user)}
    except businesses.BusinessError as exc:
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
        if exc.code != "invalid_token":
            await session.rollback()
            raise _error(exc) from None
        # Refused before anything was written: not a shop invite; maybe a business one.
        result = await _accept_business_invite(session, body.token, user)
    await session.commit()
    return {"data": result}


async def _accept_business_invite(session: AsyncSession, token: str, user: User) -> dict[str, Any]:
    business_invite = await businesses.find_invite(session, token)
    if business_invite is None:
        raise HTTPException(status_code=_STATUS["invalid_token"], detail="invalid_token")
    try:
        return await businesses.accept_invite(session, business_invite, user)
    except businesses.BusinessError as exc:
        raise _error(exc) from None  # refused before any write
