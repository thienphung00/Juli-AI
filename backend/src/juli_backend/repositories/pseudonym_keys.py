"""Per-shop sealed pseudonym keys (ADR-116 §4, D76, migration 104).

A key is written once and never edited; the service layer
(``services.privacy.pseudonym``) generates, seals and opens it. This repository
only finds a shop's row and records a new one.
"""

from __future__ import annotations

import uuid

from juli_backend.models.pseudonym_keys import ShopPseudonymKey
from juli_backend.repositories._base import ShopScopedRepo


class ShopPseudonymKeysRepo(ShopScopedRepo[ShopPseudonymKey]):
    _model = ShopPseudonymKey

    async def find(self, shop_id: uuid.UUID) -> ShopPseudonymKey | None:
        """The shop's key row, or ``None`` when it has none (yet, or any more)."""
        return await self._one_or_none(self._scoped(shop_id))

    async def record(self, shop_id: uuid.UUID, *, key_ciphertext: str) -> ShopPseudonymKey:
        """Persist a sealed key; the unique index refuses a second row for the shop."""
        return await self._add(ShopPseudonymKey(shop_id=shop_id, key_ciphertext=key_ciphertext))
