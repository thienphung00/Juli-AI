"""Per-shop pseudonym keys ``shop_pseudonym_keys`` (ADR-116 §4, D76), migration 104.

One row per shop: a random 32-byte key, sealed at rest with
``database.token_crypto.encrypt_for_purpose`` (purpose ``shop_pseudonym_key``).
``buyer_id`` is stored as ``HMAC-SHA256(key, platform buyer id)`` in bronze and
silver alike, so joins within a shop still work and ids cannot be linked across
shops or back to the platform. Deleting the row makes that shop's stored ids
permanently anonymous (offboarding, later).

Tenant-direct: RLS by ``app_current_shop_id()``; ``juli_app`` may SELECT and
INSERT only. The only reader / writer is
:mod:`juli_backend.services.privacy.pseudonym`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from juli_backend.orm_base import Base


class ShopPseudonymKey(Base):
    """The sealed HMAC key one shop's buyer ids are pseudonymised with."""

    __tablename__ = "shop_pseudonym_keys"
    __table_args__ = (UniqueConstraint("shop_id", name="uq_shop_pseudonym_keys_shop"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), nullable=False)
    #: ``enc:p1:shop_pseudonym_key:<fernet token>`` of the base64 key.
    key_ciphertext: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
