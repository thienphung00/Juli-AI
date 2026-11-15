"""The seller's businesses (P101 W1, contract §2.1): list, self-serve invites, remove a member.

``GET /v1/businesses`` feeds the header switcher (Business ▾ → Shop ▾). Invites and removal are the
business owner's (checked in ``services/businesses``, not only here). The invite link opens the
same ``/nhan-shop`` page as the shop invite; ``/v1/shop-invites/preview|accept`` read both kinds.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import User, get_session
from juli_backend.services import businesses

router = APIRouter(prefix="/businesses", tags=["businesses"])

_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "not_owner": status.HTTP_403_FORBIDDEN,
    "already_member": status.HTTP_409_CONFLICT,
    "cannot_remove_self": status.HTTP_409_CONFLICT,
    "not_a_member": status.HTTP_404_NOT_FOUND,
    "invalid_email": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _error(exc: businesses.BusinessError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 400), detail=exc.code)


@router.get("")
async def list_businesses(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The caller's businesses, each with the shops they may open (id, name, platform, kind)."""
    return {"data": await businesses.list_for_user(session, user)}


class InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str


@router.post("/{business_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_business_invite(
    business_id: uuid.UUID,
    body: InviteBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Owner only: invite a person by e-mail (7 days; one pending per e-mail)."""
    try:
        created = await businesses.create_invite(session, business_id, user, email=body.email)
    except businesses.BusinessError as exc:
        # Every refusal happens before a write: nothing to roll back.
        raise _error(exc) from None
    await session.commit()
    row = created.invite
    return {
        "data": {
            "id": str(row.id),
            "business_id": str(row.business_id),
            "email": row.email,
            "expires_at": row.expires_at.isoformat(),
            "email_sent": created.email_sent,
            "accept_url": created.accept_url,
        }
    }


@router.delete("/{business_id}/members/{user_id}")
async def remove_business_member(
    business_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Owner only: soft-delete a member; their access to the business's shops ends at once."""
    try:
        removed = await businesses.remove_member(session, business_id, user, user_id)
    except businesses.BusinessError as exc:
        # Every refusal happens before a write: nothing to roll back.
        raise _error(exc) from None
    await session.commit()
    return {"data": removed}
