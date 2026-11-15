"""P101 W1 businesses (migration 130): one account -> many businesses -> many shops.

Written only as ``juli_ops`` (``services/businesses``, after the caller's right is checked from the
verified user id); ``juli_app`` may only SELECT its own member rows and the businesses it belongs
to (what the ``shops`` policies read). Same split as ``models/ops.py``. Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base


class Business(Base):
    """P101 W1 (migration 130): one seller business, holding its shops on every platform."""

    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class BusinessInvite(Base):
    """P101 W1 (migration 130): a business owner's invite by e-mail (only the token's sha256)."""

    __tablename__ = "business_invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class BusinessMember(Base):
    """P101 W1 (migration 130): a person of a business (``owner`` or ``member``), soft-deleted."""

    __tablename__ = "business_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The e-mail the person signed in with, lower-cased at the time they joined.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    added_via: Mapped[str] = mapped_column(String(16), nullable=False)
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("business_invites.id"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index(
            "uq_business_members_active",
            "business_id",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
            sqlite_where=text("removed_at IS NULL"),
        ),
        Index("ix_business_members_user", "user_id", "business_id"),
        CheckConstraint("role IN ('owner', 'member')", name="ck_business_members_role"),
        CheckConstraint(
            "added_via IN ('owner', 'invite', 'backfill')", name="ck_business_members_added_via"
        ),
    )
