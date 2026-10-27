"""Per-shop data-use consent ``data_use_consents`` (ADR-116 §2, D76), migration 103.

One row per grant of one ``scope`` to one shop; a withdrawal sets ``revoked_at``
and a new grant is a new row. At most one open grant per (shop, scope).
Tenant-direct: RLS by ``app_current_shop_id()``; ``juli_app`` may SELECT,
INSERT, and UPDATE ``revoked_at`` on an open row only.

The per-shop reader is :func:`juli_backend.services.consent.require_consent`. The
cross-shop readers are ``ops_group_lift_draws()`` and ``ops_fleet_calibration_draws()``
(migration 107, SECURITY DEFINER, ``juli_ops`` only) and their SQLite mirrors in
``card_groups.lift_draws`` / ``lever_flows.measurement``: they return the draws of shops
with an open ``pooled_training`` grant, never the grants.

``pooled_contributor_sets`` (migration 107, D15) is the audit of who contributed to a
persisted pooled figure: ``ops_only`` (RLS on, the only policy ``FOR ALL TO juli_ops``,
``juli_ops`` SELECT / INSERT, nothing to ``juli_app``), append-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base

#: ``service``: analysis for the shop and its own client layer (from the contract /
#: terms). OpenAI, split by input because an approved list may name text only:
#: ``llm_processing`` listing text and aggregate metrics, ``llm_images`` product
#: images, ``llm_media`` video / LIVE frames and audio. ``pooled_training``: its
#: data may go into shared models (separate opt-in, off unless granted).
SCOPES: tuple[str, ...] = (
    "service",
    "llm_processing",
    "llm_images",
    "llm_media",
    "pooled_training",
)
#: The pooling opt-in by name: who may CONTRIBUTE to a figure pooled across shops -- the
#: Ops EB prior's draws, the D30.3 fleet factor (migration 107) -- D76 / D11 / D17.
POOLED_TRAINING = "pooled_training"
#: How the grant was given -- evidence, not a different kind of consent.
METHODS: tuple[str, ...] = ("contract_paper", "in_app_click", "email")

OPEN_WHERE = "revoked_at IS NULL"
CK_SCOPE = "scope IN (" + ", ".join(f"'{v}'" for v in SCOPES) + ")"
CK_METHOD = "method IN (" + ", ".join(f"'{v}'" for v in METHODS) + ")"


class DataUseConsent(Base):
    """One grant of one data-use scope to one shop."""

    __tablename__ = "data_use_consents"
    __table_args__ = (
        Index(
            "uq_data_use_consents_open",
            "shop_id",
            "scope",
            unique=True,
            postgresql_where=text(OPEN_WHERE),
            sqlite_where=text(OPEN_WHERE),
        ),
        Index("ix_data_use_consents_shop_scope_granted", "shop_id", "scope", "granted_at"),
        CheckConstraint(CK_SCOPE, name="ck_data_use_consents_scope"),
        CheckConstraint(CK_METHOD, name="ck_data_use_consents_method"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="ck_data_use_consents_revoked_after_granted",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The contract / terms / sub-processor list version the grant refers to.
    terms_version: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Where the evidence is (contract file name, email id, in-app event id).
    evidence_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    #: SHA-256 (lower-case hex) of a scanned document, when there is one.
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    #: Who granted it on the client's side: the signatory's name, or the user id for an
    #: in-app Terms acceptance (D10; never a contact detail).
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


#: ``pooled_contributor_sets.figure``: which pooled figure the row audits. Written out in
#: migration 107 too; ``tests/unit/test_pooled_cells.py`` pins the two equal.
POOLED_FIGURES: tuple[str, ...] = ("fleet_calibration", "ops_group_prior")
CK_POOLED_FIGURE = "figure IN (" + ", ".join(f"'{v}'" for v in POOLED_FIGURES) + ")"


class PooledContributorSet(Base):
    """D15: the shops behind one persisted pooled figure (``ops_only``, append-only).

    ``contributor_shop_ids`` are ``shops.id`` values (sorted), never names;
    ``contributors_sha256`` is the SHA-256 of that list joined by a newline; ``cells`` maps
    each pooled cell used to its number of contributing shops. ``applied_shop_id`` is the
    shop the figure was computed for (itself a consenting shop, D11 / D17).
    """

    __tablename__ = "pooled_contributor_sets"
    __table_args__ = (
        CheckConstraint(CK_POOLED_FIGURE, name="ck_pooled_contributor_sets_figure"),
        CheckConstraint(
            "length(contributors_sha256) = 64",
            name="ck_pooled_contributor_sets_sha256",
        ),
        Index("ix_pooled_contributor_sets_computed_at", "computed_at"),
        Index("ix_pooled_contributor_sets_applied_shop", "applied_shop_id", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    figure: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_shop_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contributor_shop_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    contributors_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cells: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
