"""The shop's keyword seeds (ADR-119), migration 111.

``shop_keyword_seeds`` -- client lane, tenant-direct (``shop_id``, RLS by
``app_current_shop_id()``): one keyword combination decomposed from the shop's own product
titles (``services/shop_keywords/decompose.py``), the pattern it follows and the platform
item ids it came from. The operator trims with ``enabled``; Ops writes it under the shop's
scope. The keyword's market numbers live in the public ``market_keyword_metrics``.
Timestamps naive UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.models.ingest import JSONBType
from juli_backend.orm_base import Base

PLATFORMS: tuple[str, ...] = ("tiktok", "shopee")
PATTERNS: tuple[str, ...] = (
    "brand_type",
    "brand_function",
    "brand_material",
    "type_function_material",
    "type_function",
    "type_material",
    "function_material",
    "function_size",
    "type_size",
    "common_phrase",
)


#: A keyword's role for the item it is scoped to (ADR-120): core (max 5 per item, enforced by
#: the service -- a CHECK cannot count rows), secondary, brand, or excluded. NULL = legacy
#: rows written before roles existed.
ROLES: tuple[str, ...] = ("chinh", "phu", "thuong_hieu", "loai_tru")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ShopKeywordSeed(Base):
    """One keyword combination and the shop items whose titles it came from."""

    __tablename__ = "shop_keyword_seeds"
    __table_args__ = (
        UniqueConstraint("shop_id", "platform", "keyword", name="uq_shop_keyword_seeds_key"),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="ck_shop_keyword_seeds_platform"),
        CheckConstraint(f"pattern IN ({_in(PATTERNS)})", name="ck_shop_keyword_seeds_pattern"),
        CheckConstraint(
            f"role IS NULL OR role IN ({_in(ROLES)})", name="ck_shop_keyword_seeds_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    platform: Mapped[str] = mapped_column(String(16))
    keyword: Mapped[str] = mapped_column(String(200))
    pattern: Mapped[str] = mapped_column(String(32))
    item_ids: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: The platform item id the role applies to; NULL = the keyword's role for the whole shop.
    item_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
