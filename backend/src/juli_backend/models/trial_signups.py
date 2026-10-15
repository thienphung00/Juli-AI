"""Free-trial sign-ups from app-juli.com/dang-ky (fast track P33-F, D43, migration 091).

Not a tenant table: a sign-up is a prospect who asked the Juli team to contact
them, before any account or shop exists. Like every ops table it is read and
written only through ``juli_ops`` (``services/ops/access.ops_role``): RLS on,
the only policy ``FOR ALL TO juli_ops``, nothing granted to ``juli_app``,
``anon`` or ``authenticated``. Classified ``ops_only``.

The visitor's IP is never stored: ``ip_hash`` is an HMAC of it, kept only so the
public endpoint can rate-limit per address. Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: Who the visitor says they are (form field "Vai trò").
ROLE_SELLER = "seller"
ROLE_AFFILIATE = "affiliate"
ROLE_SHOP_OPERATOR = "shop_operator"
ROLE_AGENCY = "agency"
SIGNUP_ROLES: tuple[str, ...] = (ROLE_SELLER, ROLE_AFFILIATE, ROLE_SHOP_OPERATOR, ROLE_AGENCY)
SIGNUP_ROLE_LABELS: dict[str, str] = {
    ROLE_SELLER: "Nhà bán",
    ROLE_AFFILIATE: "Affiliate",
    ROLE_SHOP_OPERATOR: "Đội vận hành sàn",
    ROLE_AGENCY: "Agency",
}

#: Where the team is with the sign-up (Ops "Đăng ký dùng thử").
STATUS_NEW = "new"
STATUS_CONTACTED = "contacted"
STATUS_CONVERTED = "converted"
STATUS_SPAM = "spam"
SIGNUP_STATUSES: tuple[str, ...] = (STATUS_NEW, STATUS_CONTACTED, STATUS_CONVERTED, STATUS_SPAM)
SIGNUP_STATUS_LABELS: dict[str, str] = {
    STATUS_NEW: "Mới",
    STATUS_CONTACTED: "Đã liên hệ",
    STATUS_CONVERTED: "Đã kết nối shop",
    STATUS_SPAM: "Spam",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class TrialSignup(Base):
    """One "Đăng ký dùng thử miễn phí 3 tháng" form submission."""

    __tablename__ = "trial_signups"
    __table_args__ = (
        CheckConstraint(f"role IN ({_in(SIGNUP_ROLES)})", name="ck_trial_signups_role"),
        CheckConstraint(f"status IN ({_in(SIGNUP_STATUSES)})", name="ck_trial_signups_status"),
        CheckConstraint("email = lower(email)", name="ck_trial_signups_email_lower"),
        Index("ix_trial_signups_created_at", "created_at"),
        Index("ix_trial_signups_email_created_at", "email", "created_at"),
        Index("ix_trial_signups_ip_hash_created_at", "ip_hash", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(120))
    #: Normalised to ``0xxxxxxxxx`` (10 digits).
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254))
    #: The shop name or its TikTok link, as typed.
    shop: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``{utm_source, utm_medium, utm_campaign, utm_term, utm_content, referrer}``,
    #: only the keys that were present.
    source: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    #: HMAC-SHA256 of the visitor's IP (hex); never the address itself.
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The consent box was ticked (the form refuses without it); kept as evidence.
    consent_at: Mapped[datetime] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default=STATUS_NEW, server_default=STATUS_NEW)
    #: The staff e-mail that last changed the status.
    handled_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
