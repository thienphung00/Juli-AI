"""Juli Ops console tables (fast track P16, DECISIONS D25), migration 083.

None of these is a tenant table. They are read and written only through the
ops path (``/v1/ops/*``), which runs under the dedicated ``juli_ops`` role;
the seller-facing ``juli_app`` role has no grant on any of them (migration
``083_ops_console``).

- ``ops_staff`` -- who may use the console, with which role (D25.2).
- ``ops_audit_log`` -- every ops write and every "Xem như shop" session (D25.2,
  D25.6): who, which shop, what, before/after.
- ``ops_shop_settings`` -- per-shop overrides of the defaults (D25.4). A NULL
  column means "Mặc định"; a value means "Ghi đè".
- ``ops_sim_scenarios`` -- saved "Mô phỏng" scenarios (D25.10).
- ``ops_shop_invites`` -- "Mời seller" handover invites (D25.7, P9-B).

Timestamps naive UTC, like ``models/run_changes.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: D25.2 roles, least privilege first. Stored values are ASCII; the UI shows
#: Xem / Vận hành / Admin.
ROLE_VIEWER = "viewer"
ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"
ROLES: tuple[str, ...] = (ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)
ROLE_LABELS: dict[str, str] = {
    ROLE_VIEWER: "Xem",
    ROLE_OPERATOR: "Vận hành",
    ROLE_ADMIN: "Admin",
}

#: D25.4 shop stages.
STAGE_TRIAL = "trial"
STAGE_SELF = "self"
STAGE_PILOT = "pilot"
STAGES: tuple[str, ...] = (STAGE_TRIAL, STAGE_SELF, STAGE_PILOT)
STAGE_LABELS: dict[str, str] = {
    STAGE_TRIAL: "Thử nghiệm",
    STAGE_SELF: "Tự vận hành",
    STAGE_PILOT: "Pilot đặc biệt",
}


class OpsStaff(Base):
    __tablename__ = "ops_staff"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'operator', 'admin')", name="ck_ops_staff_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Supabase auth user id; NULL until the person first signs in (seeded by email).
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OpsAuditLog(Base):
    __tablename__ = "ops_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ops_staff.id"), nullable=True
    )
    #: denormalised so a row still reads after the staff row changes; "system" for jobs.
    actor_email: Mapped[str] = mapped_column(String(320))
    shop_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    #: True when the write was made "by staff X for seller" (act mode, D25.3).
    for_seller: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    before: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class OpsShopSettings(Base):
    __tablename__ = "ops_shop_settings"
    __table_args__ = (
        CheckConstraint("stage IN ('trial', 'self', 'pilot')", name="ck_ops_shop_settings_stage"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), default=STAGE_TRIAL, server_default="trial")
    card_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_weekly_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_open_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: list of stream ids (``product_card`` / ``shop_tab`` / ``video`` / ``live``)
    enabled_streams: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    #: list of action (lever) codes
    enabled_actions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    content_cards_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    promotion_api_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    openai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    openai_monthly_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OpsSimScenario(Base):
    __tablename__ = "ops_sim_scenarios"
    __table_args__ = (
        Index(
            "uq_ops_sim_scenarios_one_target",
            "shop_id",
            unique=True,
            postgresql_where=text("is_target"),
            sqlite_where=text("is_target"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(120))
    #: {stream: {kpi: percent}}
    deltas: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_target: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ops_staff.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OpsShopInvite(Base):
    __tablename__ = "ops_shop_invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    email: Mapped[str] = mapped_column(String(320))
    #: sha256 hex of the one-time token; the token itself is only in the e-mail.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column()
    keep_ops_access: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ops_staff.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    #: what the seller answered on accept (None until accepted).
    seller_kept_ops_access: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
