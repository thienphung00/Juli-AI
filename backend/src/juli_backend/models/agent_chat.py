"""The Juli tab's storage (batch-1120 T3, migration 137).

Four tenant-direct tables, each keyed by ``shop_id`` with RLS by ``app_current_shop_id()``.
A conversation belongs to the shop, not to one member: every member of the shop sees the same
history. Nothing expires.

- ``agent_conversations`` -- one thread of questions on one platform tab.
- ``agent_messages`` -- one row per turn side. A ``user`` row holds the question (free text, a
  template key or the answer to a ``needs_choice``); the ``assistant`` row that answers it holds
  the engine's events in order (``events``, the SSE replay source), the routing state of a
  ``needs_choice`` (``pending``), the stop reasons, cost and time, and ``status``. At most one
  ``running`` assistant row per conversation (a partial unique index).
- ``agent_routing_decisions`` -- every Jev answer of a run with its thresholds and the outcome.
  Never shown to the seller.
- ``agent_card_drafts`` -- a card the engine proposed (the full engine card JSON, the only source
  of its numbers) and what became of it: ``drafted`` -> ``sent`` (``card_code``, the JC code of
  the card made through the Tự tạo path) or ``dismissed``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

PLATFORMS = ("shopee", "tiktok")

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLES = (ROLE_USER, ROLE_ASSISTANT)

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"
MESSAGE_STATUSES = (STATUS_RUNNING, STATUS_DONE, STATUS_CANCELLED, STATUS_FAILED)
TERMINAL_MESSAGE_STATUSES = (STATUS_DONE, STATUS_CANCELLED, STATUS_FAILED)

DRAFT_DRAFTED = "drafted"
DRAFT_SENT = "sent"
DRAFT_DISMISSED = "dismissed"
DRAFT_STATUSES = (DRAFT_DRAFTED, DRAFT_SENT, DRAFT_DISMISSED)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_agent_conversations_platform"),
        Index("ix_agent_conversations_shop", "shop_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(f"role IN ({_in(ROLES)})", name="ck_agent_messages_role"),
        CheckConstraint(f"status IN ({_in(MESSAGE_STATUSES)})", name="ck_agent_messages_status"),
        Index("ix_agent_messages_conversation", "conversation_id", "created_at"),
        Index("ix_agent_messages_shop_created", "shop_id", "role", "created_at"),
        Index(
            "uq_agent_messages_one_running",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    #: the question: free text, or a template key, or the answer to a ``needs_choice``
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    choice: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    #: the assistant's events in order, ``[{seq, type, payload}]`` (the SSE replay source)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONBType, default=list)
    #: the routing state saved with a ``needs_choice`` answer (opaque; handed back to the engine)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    stop_reasons: Mapped[list[str] | None] = mapped_column(JSONBType, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DONE)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentRoutingDecision(Base):
    __tablename__ = "agent_routing_decisions"
    __table_args__ = (Index("ix_agent_routing_decisions_message", "message_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE")
    )
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: the Jev answers of this decision, as the engine reported them
    answers: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentCardDraft(Base):
    __tablename__ = "agent_card_drafts"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(DRAFT_STATUSES)})", name="ck_agent_card_drafts_status"),
        UniqueConstraint("shop_id", "draft_ref", name="uq_agent_card_drafts_ref"),
        Index("ix_agent_card_drafts_message", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE")
    )
    draft_ref: Mapped[str] = mapped_column(String(64))
    #: the full engine card JSON: the only source of the sent card's numbers
    card: Mapped[dict[str, Any]] = mapped_column(JSONBType)
    status: Mapped[str] = mapped_column(String(16), default=DRAFT_DRAFTED)
    version_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    card_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


__all__ = [
    "DRAFT_DISMISSED",
    "DRAFT_DRAFTED",
    "DRAFT_SENT",
    "DRAFT_STATUSES",
    "MESSAGE_STATUSES",
    "PLATFORMS",
    "ROLES",
    "ROLE_ASSISTANT",
    "ROLE_USER",
    "STATUS_CANCELLED",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "TERMINAL_MESSAGE_STATUSES",
    "AgentCardDraft",
    "AgentConversation",
    "AgentMessage",
    "AgentRoutingDecision",
]
