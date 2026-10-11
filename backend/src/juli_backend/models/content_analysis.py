"""Content analysis of seller-uploaded media (fast track P15, D24.20), migration 082.

``content_analyses`` -- one row per upload (tenant-direct). Holds the upload's
progress, the pipeline's status and ONLY DERIVED DATA (transcript segments,
cuts, on-screen text, product-on-screen timeline, the scoring result, OpenAI
usage and cost). The uploaded file lives on the VPS disk under
``CONTENT_ANALYSIS_UPLOAD_DIR`` until the analysis ends, never in the database;
``storage_key`` is the file's path relative to that directory and is cleared
(with ``file_deleted_at`` set) once the file is gone.

Timestamps naive UTC, like ``models/order_costs.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base


class ContentAnalysis(Base):
    """One uploaded video / LIVE recording and what Juli derived from it."""

    __tablename__ = "content_analyses"
    __table_args__ = (
        CheckConstraint("kind IN ('video', 'live')", name="ck_content_analyses_kind"),
        Index("ix_content_analyses_shop_product", "shop_id", "tiktok_product_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    #: ``video`` | ``live``.
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    #: The Phân tích row it was uploaded for: ``video:<tiktok video id>`` /
    #: ``live:<tiktok live id>``; ``None`` when uploaded from a content run
    #: without a specific row.
    content_ref: Mapped[str | None] = mapped_column(String(200))
    tiktok_product_id: Mapped[str | None] = mapped_column(String(100))
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    #: ``awaiting_upload`` → ``queued`` → ``processing`` → ``done`` | ``failed``
    #: | ``refused`` (over the monthly OpenAI cap) | ``expired`` (upload never finished).
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Declared by the client when the upload is created; the upload must match it.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    upload_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float)
    #: Derived signals (transcript segments, cuts, OCR, product timeline, windows).
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: The seller-facing result (``services.content_analysis.view``).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    #: Per stage: model, minutes / tokens, USD; plus stage timings.
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=6), nullable=False, default=Decimal(0)
    )
    error_code: Mapped[str | None] = mapped_column(String(50))
    #: Vietnamese, seller-facing.
    error_message: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    file_deleted_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["ContentAnalysis"]
