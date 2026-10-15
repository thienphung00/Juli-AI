"""Free-trial sign-ups (fast track P33-F, D43): validate, rate-limit, store, notify.

The public form on app-juli.com/dang-ky posts (server-side, through the landing's
own route) to ``POST /v1/trial-signups``. This module holds everything behind it
and the Ops console's list / status change:

- :func:`validate` turns the raw body into a :class:`SignupInput` or a dict of
  Vietnamese, per-field messages. The phone must be a Vietnamese mobile number
  (it is also the Zalo contact); it is stored as ``0xxxxxxxxx``.
- The honeypot field (``website``) is invisible to people. A filled one is
  answered exactly like a success and nothing is stored.
- Rate limits are counted from the table itself (no Redis, works across
  workers): per IP hash, per e-mail and site-wide. A refused attempt stores
  nothing.
- The visitor's IP is never stored, only ``HMAC-SHA256(TRIAL_SIGNUP_IP_SALT, ip)``.
- **Never log the phone, the e-mail or the name.** Log lines carry the row id
  and the outcome only.

The table is ``ops_only`` (migration 091): every read and write runs inside
``ops_role`` (``SET LOCAL ROLE juli_ops``), the public endpoint included.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.trial_signups import (
    SIGNUP_ROLE_LABELS,
    SIGNUP_ROLES,
    SIGNUP_STATUS_LABELS,
    SIGNUP_STATUSES,
    STATUS_NEW,
    TrialSignup,
)
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import ops_role
from juli_backend.services.ops.mailer import get_mailer

logger = logging.getLogger(__name__)

#: Env: who gets the "new sign-up" e-mail (comma-separated). Unset → logged, not sent.
NOTIFY_ENV = "TRIAL_SIGNUP_NOTIFY_TO"
#: Env: the HMAC key for ``ip_hash``.
IP_SALT_ENV = "TRIAL_SIGNUP_IP_SALT"
#: Env: shared with the landing server; proves ``X-Juli-Client-Ip`` came from it.
RELAY_KEY_ENV = "TRIAL_SIGNUP_RELAY_KEY"
RELAY_KEY_HEADER = "x-juli-relay-key"
CLIENT_IP_HEADER = "x-juli-client-ip"
#: Used only when ``TRIAL_SIGNUP_IP_SALT`` is unset (DEBT: set it in production).
_FALLBACK_IP_SALT = "juli-trial-signup-ip-v1"

#: Rate limits (attempts that were STORED, inside the window).
PER_IP_LIMIT = 5
PER_IP_WINDOW = timedelta(hours=1)
PER_EMAIL_LIMIT = 3
PER_EMAIL_WINDOW = timedelta(days=1)
GLOBAL_LIMIT = 120
GLOBAL_WINDOW = timedelta(hours=1)

HONEYPOT_FIELD = "website"
SOURCE_KEYS: tuple[str, ...] = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "referrer",
)
SOURCE_MAX = 300

NAME_MIN, NAME_MAX = 2, 120
SHOP_MIN, SHOP_MAX = 2, 300
NOTE_MAX = 1000
EMAIL_MAX = 254

#: Vietnamese mobile prefixes (10 digits after normalising to a leading 0).
_PHONE_RE = re.compile(r"^0[35789]\d{8}$")
_PHONE_STRIP = re.compile(r"[\s.\-()]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

MSG_NAME = "Vui lòng nhập họ tên (2–120 ký tự)."
MSG_PHONE = "Số điện thoại chưa đúng — nhập số di động Việt Nam, ví dụ 0912 345 678."
MSG_EMAIL = "Email chưa đúng, ví dụ ten@congty.vn."
MSG_SHOP = "Vui lòng nhập tên hoặc link shop TikTok (2–300 ký tự)."
MSG_ROLE = "Vui lòng chọn vai trò."
MSG_NOTE = "Ghi chú tối đa 1.000 ký tự."
MSG_CONSENT = "Vui lòng đồng ý với Điều khoản dịch vụ và Chính sách bảo mật."
MSG_RATE_LIMITED = (
    "Bạn đã gửi đăng ký nhiều lần. Đội ngũ Juli đã nhận thông tin và sẽ liên hệ — "
    "hoặc email lienhe@app-juli.com."
)


@dataclass(frozen=True)
class SignupInput:
    full_name: str
    phone: str
    email: str
    shop: str
    role: str
    note: str | None
    source: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Validated:
    """Either ``data`` (valid), ``honeypot`` (a bot), or per-field ``errors``."""

    data: SignupInput | None = None
    errors: dict[str, str] = field(default_factory=dict)
    honeypot: bool = False


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.split())


def normalize_phone(value: str) -> str | None:
    """``+84 912-345-678`` / ``84912345678`` / ``0912.345.678`` → ``0912345678``; else None."""
    digits = _PHONE_STRIP.sub("", value or "")
    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if _PHONE_RE.match(digits) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def _source(raw: dict[str, Any]) -> dict[str, str]:
    nested = raw.get("source")
    merged: dict[str, Any] = dict(nested) if isinstance(nested, dict) else {}
    for key in SOURCE_KEYS:
        if key in raw and key not in merged:
            merged[key] = raw[key]
    out: dict[str, str] = {}
    for key in SOURCE_KEYS:
        value = merged.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:SOURCE_MAX]
    return out


def validate(raw: dict[str, Any]) -> Validated:
    """The form body → a :class:`Validated`. Never echoes a value back."""
    if _text(raw, HONEYPOT_FIELD):
        return Validated(honeypot=True)
    errors: dict[str, str] = {}
    name = _text(raw, "full_name")
    if not NAME_MIN <= len(name) <= NAME_MAX:
        errors["full_name"] = MSG_NAME
    phone = normalize_phone(_text(raw, "phone"))
    if phone is None:
        errors["phone"] = MSG_PHONE
    email = _text(raw, "email").lower()
    if len(email) > EMAIL_MAX or not _EMAIL_RE.match(email):
        errors["email"] = MSG_EMAIL
    shop = _text(raw, "shop")
    if not SHOP_MIN <= len(shop) <= SHOP_MAX:
        errors["shop"] = MSG_SHOP
    role = _text(raw, "role")
    if role not in SIGNUP_ROLES:
        errors["role"] = MSG_ROLE
    note_raw = raw.get("note")
    note = note_raw.strip() if isinstance(note_raw, str) else ""
    if len(note) > NOTE_MAX:
        errors["note"] = MSG_NOTE
    if not _truthy(raw.get("consent", False)):
        errors["consent"] = MSG_CONSENT
    if errors or phone is None:
        return Validated(errors=errors)
    return Validated(
        data=SignupInput(
            full_name=name,
            phone=phone,
            email=email,
            shop=shop,
            role=role,
            note=note or None,
            source=_source(raw),
        )
    )


# -- client IP -----------------------------------------------------------------------


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(headers: Any, peer: str | None) -> str | None:
    """The visitor's IP: the landing's ``X-Juli-Client-Ip`` when the relay key proves
    it came from the landing server, else the connection's own (already the real
    client behind nginx + ``--proxy-headers``)."""
    key = os.environ.get(RELAY_KEY_ENV, "").strip()
    offered = headers.get(RELAY_KEY_HEADER) or ""
    if key and offered and hmac.compare_digest(key.encode(), offered.encode()):
        forwarded = _valid_ip(headers.get(CLIENT_IP_HEADER))
        if forwarded:
            return forwarded
    return _valid_ip(peer)


def ip_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = os.environ.get(IP_SALT_ENV, "").strip() or _FALLBACK_IP_SALT
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()


# -- store -------------------------------------------------------------------------


class RateLimited(Exception):
    """Too many sign-ups from this address / e-mail / overall."""

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(scope)


async def _count_since(session: AsyncSession, since: datetime, *where: Any) -> int:
    stmt = select(func.count()).select_from(TrialSignup).where(TrialSignup.created_at >= since)
    for clause in where:
        stmt = stmt.where(clause)
    return int((await session.execute(stmt)).scalar_one())


async def create_signup(
    session: AsyncSession,
    data: SignupInput,
    *,
    ip_digest: str | None,
    now: datetime | None = None,
) -> TrialSignup:
    """Rate-limit, then add the row (no commit). Raises :class:`RateLimited`."""
    moment = now or utc_now_naive()
    async with ops_role(session):
        if ip_digest is not None and (
            await _count_since(session, moment - PER_IP_WINDOW, TrialSignup.ip_hash == ip_digest)
            >= PER_IP_LIMIT
        ):
            raise RateLimited("ip")
        if (
            await _count_since(session, moment - PER_EMAIL_WINDOW, TrialSignup.email == data.email)
            >= PER_EMAIL_LIMIT
        ):
            raise RateLimited("email")
        if await _count_since(session, moment - GLOBAL_WINDOW) >= GLOBAL_LIMIT:
            raise RateLimited("global")
        row = TrialSignup(
            id=uuid.uuid4(),
            full_name=data.full_name,
            phone=data.phone,
            email=data.email,
            shop=data.shop,
            role=data.role,
            note=data.note,
            source=data.source or None,
            ip_hash=ip_digest,
            consent_at=moment,
            status=STATUS_NEW,
            created_at=moment,
        )
        session.add(row)
    return row


# -- notify ------------------------------------------------------------------------


def notify_recipients() -> list[str]:
    raw = os.environ.get(NOTIFY_ENV, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def notification_body(signup: dict[str, Any]) -> str:
    """The team e-mail for one sign-up (``to_json`` shape)."""
    source = ", ".join(f"{k}={v}" for k, v in (signup.get("source") or {}).items()) or "—"
    return (
        "Có đăng ký dùng thử mới trên app-juli.com/dang-ky.\n\n"
        f"Họ tên: {signup['full_name']}\n"
        f"Số điện thoại / Zalo: {signup['phone']}\n"
        f"Email: {signup['email']}\n"
        f"Shop TikTok: {signup['shop']}\n"
        f"Vai trò: {signup['role_label']}\n"
        f"Ghi chú: {signup.get('note') or '—'}\n"
        f"Nguồn: {source}\n\n"
        "Xem và cập nhật trạng thái: https://ops.app-juli.com/ops/dang-ky-dung-thu\n\n— Juli"
    )


async def notify_team(signup: dict[str, Any]) -> bool:
    """E-mail the team (``TRIAL_SIGNUP_NOTIFY_TO``) through the ops mailer.

    Takes the ``to_json`` snapshot taken before the commit (it runs after the
    response, when the ORM row may be expired). Without recipients or SMTP
    nothing is sent and the sign-up still stands; the log names only the row id.
    """
    signup_id = str(signup["id"])
    recipients = notify_recipients()
    if not recipients:
        logger.info("trial_signup_notify_unset", extra={"signup_id": signup_id})
        return False
    mailer = get_mailer()
    subject = f"Đăng ký dùng thử mới · {signup['role_label']}"
    body = notification_body(signup)
    sent_all = True
    for to in recipients:
        sent = await mailer.send_notice(to=to, subject=subject, body=body)
        sent_all = sent_all and sent
    logger.info(
        "trial_signup_notified" if sent_all else "trial_signup_notify_unsent",
        extra={"signup_id": signup_id},
    )
    return sent_all


# -- ops ---------------------------------------------------------------------------

ACTION_STATUS = "trial_signup_status"


def to_json(row: TrialSignup) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "full_name": row.full_name,
        "phone": row.phone,
        "email": row.email,
        "shop": row.shop,
        "role": row.role,
        "role_label": SIGNUP_ROLE_LABELS.get(row.role, row.role),
        "note": row.note,
        "source": row.source or {},
        "status": row.status,
        "status_label": SIGNUP_STATUS_LABELS.get(row.status, row.status),
        "handled_by": row.handled_by,
        "handled_at": row.handled_at.isoformat() if row.handled_at else None,
    }


async def list_signups(
    session: AsyncSession, *, status: str | None = None, limit: int = 200
) -> tuple[list[TrialSignup], dict[str, int]]:
    """Newest first, optionally one status; plus the count per status."""
    stmt = select(TrialSignup).order_by(TrialSignup.created_at.desc(), TrialSignup.id).limit(limit)
    if status is not None:
        stmt = stmt.where(TrialSignup.status == status)
    counts_stmt = select(TrialSignup.status, func.count()).group_by(TrialSignup.status)
    async with ops_role(session):
        rows = list((await session.execute(stmt)).scalars().all())
        counts = {str(s): int(n) for s, n in (await session.execute(counts_stmt)).all()}
    return rows, {s: counts.get(s, 0) for s in SIGNUP_STATUSES}


class SignupNotFound(LookupError):
    pass


async def set_status(
    session: AsyncSession,
    signup_id: uuid.UUID,
    status: str,
    actor: audit.Actor,
    *,
    now: datetime | None = None,
) -> TrialSignup:
    """Change the status, stamp ``handled_by``, audit it (no commit).

    A no-op (same status) writes nothing. The audit row names the sign-up in
    ``field`` (``trial_signup:<id>``) so D27.6 merging stays per sign-up; its
    before/after hold only the status, never contact details.
    """
    if status not in SIGNUP_STATUSES:
        raise ValueError(status)
    moment = now or utc_now_naive()
    async with ops_role(session):
        row = await session.get(TrialSignup, signup_id)
        if row is None:
            raise SignupNotFound(str(signup_id))
        before = row.status
        if before == status:
            return row
        row.status = status
        row.handled_by = actor.email
        row.handled_at = moment
        await audit.record(
            session,
            actor,
            ACTION_STATUS,
            before={"status": before},
            after={"status": status},
            field=f"trial_signup:{signup_id}",
            at=moment,
        )
    return row
