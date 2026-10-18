"""The seller's own account: privacy, consent, export, deletion (fast track P50-B, D60).

Contract ``fasttrack/contracts/p50-privacy.md``. Every route is scoped by the
verified ``users.id`` from ``get_current_user`` and nothing else -- there is no
user id in any path or body. The behaviour lives in ``services/privacy``; this
module validates bodies (unknown keys → 422), maps the two consent refusals to
409 / 422, and commits. A partner reviewer never reaches these routes: they are
not on ``api/reviewer.ALLOWED_ENDPOINTS``.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import get_current_user
from juli_backend.database import User, get_session
from juli_backend.services import privacy
from juli_backend.services.privacy.prefs import now_utc
from juli_backend.services.subscriptions import shop_today

router = APIRouter(prefix="/me", tags=["me"])


class PrivacyResponse(BaseModel):
    marketing_opt_out: bool
    ad_measurement_opt_out: bool
    case_study_opt_in: bool
    terms_date_accepted: str | None
    terms_accepted_at: str | None
    liability_clause_accepted_at: str | None
    current_terms_date: str
    needs_terms_acceptance: bool
    deletion_scheduled_for: str | None


class PrivacyPatch(BaseModel):
    """Any subset of the three switches; anything else is 422."""

    model_config = ConfigDict(extra="forbid")

    marketing_opt_out: StrictBool | None = None
    ad_measurement_opt_out: StrictBool | None = None
    case_study_opt_in: StrictBool | None = None


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms_date: date
    liability_clause: StrictBool


@router.get("/privacy", response_model=PrivacyResponse)
async def get_privacy(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    state = await privacy.get_privacy(session, user.id)
    await session.commit()
    return state.to_json()


@router.patch("/privacy", response_model=PrivacyResponse)
async def patch_privacy(
    body: PrivacyPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "privacy_value_required"},
        )
    state = await privacy.update_preferences(session, user.id, changes)
    await session.commit()
    return state.to_json()


@router.post("/consents", response_model=PrivacyResponse)
async def post_consent(
    body: ConsentRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """D60.4 / D60.8: accept the current legal text and Điều 11 (separately)."""
    try:
        state = await privacy.record_consent(
            session, user.id, terms_date=body.terms_date, liability_clause=body.liability_clause
        )
    except privacy.TermsDateMismatch:
        # Raised before any write: nothing to roll back.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "terms_date_mismatch",
                "current_terms_date": privacy.LEGAL_TERMS_DATE.isoformat(),
            },
        ) from None
    except privacy.LiabilityClauseRequired:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "liability_clause_required"},
        ) from None
    await session.commit()
    return state.to_json()


@router.get("/export")
async def get_export(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """D60.6: the seller's own data as a JSON download (allowed while deletion is pending)."""
    now = now_utc()
    payload = await privacy.build_export(session, user.id, now=now)
    await session.commit()
    filename = f"juli-du-lieu-{shop_today(now).isoformat()}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=privacy.export_json_default),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/deletion", response_model=PrivacyResponse)
async def request_deletion(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """D60.10: delete in 30 days; the shops go read-only and stop syncing. Idempotent."""
    state = await privacy.request_deletion(session, user.id)
    await session.commit()
    return state.to_json()


@router.delete("/deletion", response_model=PrivacyResponse)
async def cancel_deletion(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    state = await privacy.cancel_deletion(session, user.id)
    await session.commit()
    return state.to_json()
