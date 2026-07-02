import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.infrastructure.auth import SupabaseAuth, Unauthorized
from src.shared.utils.data import get_session
from src.shared.utils.data.repos import UsersRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class OtpSendRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)


class OtpVerifyRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    token: str = Field(min_length=4, max_length=10)


class OtpSendResponse(BaseModel):
    message: str = "OTP sent"


class SessionUserResponse(BaseModel):
    id: str
    phone: str


class SessionResponse(BaseModel):
    access_token: str
    user: SessionUserResponse


def normalize_vn_phone(phone: str) -> str:
    """Normalize Vietnamese numbers to E.164 +84… for Supabase."""
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+84"):
        return cleaned
    if cleaned.startswith("84") and len(cleaned) >= 11:
        return f"+{cleaned}"
    if cleaned.startswith("0") and len(cleaned) >= 10:
        return f"+84{cleaned[1:]}"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Số điện thoại không hợp lệ. Dùng định dạng +84…",
    )


def _phone_otp_enabled() -> bool:
    """App Review sets PHONE_OTP_ENABLED=false; production defaults to enabled."""
    return os.environ.get("PHONE_OTP_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _require_phone_otp_enabled() -> None:
    if not _phone_otp_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone OTP login is disabled",
        )


def _supabase_auth() -> SupabaseAuth:
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not anon_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service not configured",
        )
    return SupabaseAuth(url, anon_key)


@router.post("/otp/send", response_model=OtpSendResponse)
async def send_otp(body: OtpSendRequest) -> OtpSendResponse:
    """Send phone OTP via Supabase Auth."""
    _require_phone_otp_enabled()
    phone = normalize_vn_phone(body.phone)
    auth = _supabase_auth()
    try:
        await auth.send_otp(phone)
    except Unauthorized as exc:
        logger.warning("otp_send_rejected", extra={"phone": phone[:6] + "***"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    finally:
        await auth.close()
    return OtpSendResponse()


@router.post("/otp/verify", response_model=SessionResponse)
async def verify_otp(
    body: OtpVerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Verify OTP and ensure a Juli user row exists for the Supabase subject."""
    _require_phone_otp_enabled()
    phone = normalize_vn_phone(body.phone)
    auth = _supabase_auth()
    try:
        data = await auth.verify_otp(phone, body.token)
    except Unauthorized as exc:
        logger.warning("otp_verify_rejected", extra={"phone": phone[:6] + "***"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    finally:
        await auth.close()

    supabase_user = data.get("user") or {}
    raw_id = supabase_user.get("id")
    if not raw_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid auth response: missing user id",
        )

    try:
        user_id = uuid.UUID(str(raw_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid auth response: user id is not a UUID",
        ) from exc

    user_phone = str(supabase_user.get("phone") or phone)
    user = await UsersRepo(session).get_or_create(user_id, user_phone)

    return SessionResponse(
        access_token=data["access_token"],
        user=SessionUserResponse(id=str(user.id), phone=user.phone),
    )
