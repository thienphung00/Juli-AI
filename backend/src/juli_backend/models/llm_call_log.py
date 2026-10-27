"""One row per OpenAI call attempt ``llm_call_log`` (ADR-116 §5, D76), migration 105.

Written by the OpenAI gate (:mod:`juli_backend.services.llm_gate`) for every attempt
it sees -- a call that was sent, refused before any HTTP, or failed on the wire.
Metadata only: which shop, why (``purpose``), which model and endpoint, which OpenAI
project, the token counts and OpenAI's ``x-request-id``. Never the prompt, the
output, or any part of either.

Per-client usage comes from here (OpenAI splits usage by project / key / model
only); the monthly token total per project must reconcile with OpenAI's figure,
and a gap means a call bypassed the gate.

Tenant-direct: RLS by ``app_current_shop_id()``; ``juli_app`` may SELECT and INSERT
only -- the log is append-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

STATUS_SENT = "sent"
STATUS_REFUSED = "refused"
STATUS_ERROR = "error"
STATUSES: tuple[str, ...] = (STATUS_SENT, STATUS_REFUSED, STATUS_ERROR)

CK_STATUS = "status IN (" + ", ".join(f"'{v}'" for v in STATUSES) + ")"
#: A refusal names its reason; a sent or failed call has none.
CK_REFUSAL_REASON = "(status = 'refused') = (refusal_reason IS NOT NULL)"


class LLMCallLog(Base):
    """One OpenAI call attempt of one shop (metadata, no content)."""

    __tablename__ = "llm_call_log"
    __table_args__ = (
        Index("ix_llm_call_log_shop_created", "shop_id", "created_at"),
        CheckConstraint(CK_STATUS, name="ck_llm_call_log_status"),
        CheckConstraint(CK_REFUSAL_REASON, name="ck_llm_call_log_refusal_reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    #: Why the call was made (``services.llm_gate.PURPOSES``).
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The API path, e.g. ``/v1/responses``.
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The OpenAI project the key belongs to (``juli-client-data``).
    project: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: OpenAI's ``x-request-id`` response header; NULL when nothing was sent.
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    refusal_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
