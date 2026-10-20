"""The card journey log ``card_events`` (ADR-107 amended 2026-10-20, D70.9), migration 095.

One append-only row per stage of a recommendation: proposed, shown, accepted,
dismissed, expired, executed / not_executed, reverted, impact readings,
superseded, and (card-less) seller changes and model shadow runs. Tenant-direct:
RLS by ``app_current_shop_id()``, ``juli_app`` may SELECT and INSERT only -- a
correction is a new event, never an edit.

Idempotency: every writer and the backfill derive a deterministic ``dedup_key``
(unique per shop) and insert with ``ON CONFLICT DO NOTHING``; single-occurrence
event types are also unique per card (partial unique index).

``feature_snapshot_id`` points at ``gold.ml_feature_snapshots`` in the database
(migration 095); the model leaves the foreign key out so the SQLite unit-test
schema (which folds ``gold`` into the default schema) needs no gold model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: JSONB on Postgres, plain JSON on the SQLite unit-test schema (as ``models/ingest.py``).
JSONBType = JSON().with_variant(JSONB(), "postgresql")

EVENT_PROPOSED = "proposed"
EVENT_SHOWN = "shown"
EVENT_ACCEPTED = "accepted"
EVENT_EDITED = "edited"
EVENT_DISMISSED = "dismissed"
EVENT_EXPIRED = "expired"
EVENT_SELLER_DONE = "seller_done"
EVENT_EXECUTED = "executed"
EVENT_NOT_EXECUTED = "not_executed"
EVENT_REVERTED = "reverted"
EVENT_IMPACT_PRELIMINARY = "impact_preliminary"
EVENT_IMPACT_FINAL = "impact_final"
EVENT_SELLER_CHANGE = "seller_change"
EVENT_SHADOW = "shadow"
EVENT_SUPERSEDED = "superseded"

#: ADR-107 amendment §1, in the table's order.
EVENT_TYPES: tuple[str, ...] = (
    EVENT_PROPOSED,
    EVENT_SHOWN,
    EVENT_ACCEPTED,
    EVENT_EDITED,
    EVENT_DISMISSED,
    EVENT_EXPIRED,
    EVENT_SELLER_DONE,
    EVENT_EXECUTED,
    EVENT_NOT_EXECUTED,
    EVENT_REVERTED,
    EVENT_IMPACT_PRELIMINARY,
    EVENT_IMPACT_FINAL,
    EVENT_SELLER_CHANGE,
    EVENT_SHADOW,
    EVENT_SUPERSEDED,
)

#: Once per card, whatever the run: unique on (card_id, event_type).
#: ``accepted``, ``executed`` / ``not_executed`` and the impact readings are
#: single per run instead (their ``dedup_key`` carries the approval / run id):
#: a failed run puts the card back on the desk (fast track D47.5), so one card
#: can be approved and run more than once. See LOG 2026-10-20 (P60-1a).
SINGLE_PER_CARD_EVENT_TYPES: tuple[str, ...] = (
    EVENT_PROPOSED,
    EVENT_SHOWN,
    EVENT_DISMISSED,
    EVENT_EXPIRED,
    EVENT_SELLER_DONE,
    EVENT_SUPERSEDED,
)

#: The only event types that may have no card (amendment §2).
CARDLESS_EVENT_TYPES: tuple[str, ...] = (EVENT_SELLER_CHANGE, EVENT_SHADOW)

ACTOR_SELLER = "seller"
ACTOR_JULI = "juli"
ACTOR_TIKTOK = "tiktok"
ACTOR_SYSTEM = "system"
ACTORS: tuple[str, ...] = (ACTOR_SELLER, ACTOR_JULI, ACTOR_TIKTOK, ACTOR_SYSTEM)

SOURCE_LIVE = "live"
SOURCE_BACKFILL = "backfill"
SOURCES: tuple[str, ...] = (SOURCE_LIVE, SOURCE_BACKFILL)

#: The dismiss sheet's five reasons in order (ADR-107 decision 5), then "no choice".
DISMISS_REASON_CODES: tuple[str, ...] = (
    "not_needed",
    "wrong_analysis",
    "not_understood",
    "already_done",
    "later",
    "unspecified",
)

SCHEMA_VERSION = 1


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


EVENT_TYPES_SQL = _sql_list(EVENT_TYPES)
SINGLE_PER_CARD_SQL = _sql_list(SINGLE_PER_CARD_EVENT_TYPES)
CARDLESS_SQL = _sql_list(CARDLESS_EVENT_TYPES)
ACTORS_SQL = _sql_list(ACTORS)
SOURCES_SQL = _sql_list(SOURCES)
DISMISS_REASONS_SQL = _sql_list(DISMISS_REASON_CODES)

#: CHECK expressions, shared verbatim with migration 095.
CK_EVENT_TYPE = f"event_type IN ({EVENT_TYPES_SQL})"
CK_ACTOR = f"actor IN ({ACTORS_SQL})"
CK_SOURCE = f"source IN ({SOURCES_SQL})"
CK_CARD_ID = f"card_id IS NOT NULL OR event_type IN ({CARDLESS_SQL})"
CK_REASON_CODE = f"reason_code IS NULL OR reason_code IN ({DISMISS_REASONS_SQL})"
CK_DISMISSED_HAS_REASON = "event_type <> 'dismissed' OR reason_code IS NOT NULL"
#: Amendment §3: a live proposal names its rule / model version. ``readiness_level``
#: and ``feature_snapshot_id`` are not enforced yet (no D3 levels and no
#: ``gold.ml_feature_snapshots`` writer exist; P60-1e) -- DEBT P60-1a.
CK_PROPOSED_FROZEN = "event_type <> 'proposed' OR source <> 'live' OR model_version IS NOT NULL"
SINGLE_PER_CARD_WHERE = f"event_type IN ({SINGLE_PER_CARD_SQL})"


class CardEvent(Base):
    """One stage of one recommendation (append-only)."""

    __tablename__ = "card_events"
    __table_args__ = (
        UniqueConstraint("shop_id", "dedup_key", name="uq_card_events_dedup"),
        Index(
            "uq_card_events_card_single",
            "card_id",
            "event_type",
            unique=True,
            postgresql_where=text(SINGLE_PER_CARD_WHERE),
            sqlite_where=text(SINGLE_PER_CARD_WHERE),
        ),
        Index("ix_card_events_shop_workflow_time", "shop_id", "workflow_key", "occurred_at"),
        Index("ix_card_events_card_time", "card_id", "occurred_at"),
        Index("ix_card_events_shop_subject_time", "shop_id", "subject_id", "occurred_at"),
        CheckConstraint(CK_EVENT_TYPE, name="ck_card_events_event_type"),
        CheckConstraint(CK_ACTOR, name="ck_card_events_actor"),
        CheckConstraint(CK_SOURCE, name="ck_card_events_source"),
        CheckConstraint(CK_CARD_ID, name="ck_card_events_card_id"),
        CheckConstraint(CK_REASON_CODE, name="ck_card_events_reason_code"),
        CheckConstraint(CK_DISMISSED_HAS_REASON, name="ck_card_events_dismissed_reason"),
        CheckConstraint(CK_PROPOSED_FROZEN, name="ck_card_events_proposed_frozen"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: NULL only for a card-less ``seller_change`` or a ``shadow`` row.
    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("action_cards.id"))
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The TikTok product id for a product card, else the card's own subject id.
    subject_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    model_version: Mapped[str | None] = mapped_column(String(128))
    readiness_level: Mapped[int | None] = mapped_column(SmallInteger)
    #: -> ``gold.ml_feature_snapshots(id)`` (FK in migration 095 only, see module doc).
    feature_snapshot_id: Mapped[uuid.UUID | None] = mapped_column()
    #: ``dismissed`` only: one of :data:`DISMISS_REASON_CODES`.
    reason_code: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=SCHEMA_VERSION)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
