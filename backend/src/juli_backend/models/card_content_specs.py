"""The content specs of a card or shop: title candidates, banner set, style profile (P100 E.7).

Migration 127. Append-only (``juli_app`` SELECT + INSERT, no UPDATE/DELETE): the newest row for
(card, type) is the current title or banner spec, the newest for (shop, ``style_profile``) is the
shop's profile; every row stays for audit and learning. Shapes (``spec`` per ``spec_type``,
``schema_version`` 1): ``fasttrack/contracts/p100-s2-demo.md`` "E.7 card specs".

``inputs_hash`` is the sha256 of the canonical JSON inputs, so a cache hit is provable. The title
quota counts only ``source='llm'`` title rows per (shop, item) per GMT+7 day; ``seeded`` (the
sample shop) and ``seller`` (an edit or a choice) rows never count.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

SPEC_TITLE = "title"
SPEC_BANNER = "banner"
SPEC_STYLE_PROFILE = "style_profile"
SPEC_TYPES = (SPEC_TITLE, SPEC_BANNER, SPEC_STYLE_PROFILE)

SOURCE_LLM = "llm"
SOURCE_SELLER = "seller"
SOURCE_SEEDED = "seeded"
SOURCES = (SOURCE_LLM, SOURCE_SELLER, SOURCE_SEEDED)

SCHEMA_VERSION = 1


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class CardContentSpec(Base):
    __tablename__ = "card_content_specs"
    __table_args__ = (
        CheckConstraint(f"spec_type IN ({_in(SPEC_TYPES)})", name="ck_card_content_specs_type"),
        CheckConstraint(f"source IN ({_in(SOURCES)})", name="ck_card_content_specs_source"),
        CheckConstraint("length(inputs_hash) = 64", name="ck_card_content_specs_hash"),
        CheckConstraint(
            "spec_type <> 'style_profile' OR (proposal_id IS NULL AND item_id IS NULL)",
            name="ck_card_content_specs_profile_shop",
        ),
        Index("ix_card_content_specs_item", "shop_id", "spec_type", "item_id", "created_at"),
        Index("ix_card_content_specs_card", "shop_id", "spec_type", "proposal_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    spec_type: Mapped[str] = mapped_column(String(16))
    #: the card (``shop_proposals.id``); None for ``style_profile``
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_proposals.id"), nullable=True
    )
    #: the product; None for ``style_profile``
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int] = mapped_column(
        SmallInteger, default=SCHEMA_VERSION, server_default=str(SCHEMA_VERSION)
    )
    inputs_hash: Mapped[str] = mapped_column(String(64))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONBType)
    source: Mapped[str] = mapped_column(String(16))
    #: the ``llm_call_log`` row of a ``source='llm'`` spec
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


__all__ = [
    "SCHEMA_VERSION",
    "SOURCES",
    "SOURCE_LLM",
    "SOURCE_SEEDED",
    "SOURCE_SELLER",
    "SPEC_BANNER",
    "SPEC_STYLE_PROFILE",
    "SPEC_TITLE",
    "SPEC_TYPES",
    "CardContentSpec",
]
