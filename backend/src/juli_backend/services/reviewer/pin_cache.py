"""The pinned shop's identity facts, cached for the reviewer identity TTL (fast track P69).

Every reviewer request used to re-enter the pinned shop the long way: switch to
``juli_ops``, find the shop and enter its seller scope, read the ``shops`` row, then
classify the pin (sandbox owners, the shop's credential capabilities, its
``production_write_shops`` row) -- seven round trips (~1.4 s from the VPS) before the
route read anything. Those facts change only when the team re-pins or (dis)connects
the shop, so they are cached here per pinned shop id for
``core.security.reviewer_identity_ttl_seconds()`` (30 s by default).

What a hit still does on every request (``api/reviewer.enter_reviewer_shop``): applies
the shop's tenant scope (``SET LOCAL`` of the shop and owner GUCs) to THIS request's
transaction, so RLS narrows every query exactly as before. The cache never bypasses it.

Tenant safety: the key is the configured pin (``REVIEWER_SHOP_ID``), the same for every
reviewer -- a reviewer can only ever be pinned to that one shop -- and the value is that
shop's own row and classification. Each hit hands out a FRESH detached ``Shop``; no ORM
instance is shared between requests. A pin that turns into a production shop (a
``production_read`` credential or a ``production_write_shops`` row added) disables
reviewer writes within the TTL; layer 2 of D73 Q6 (every reviewer request is marked, and
every production write path refuses it) stays per request and is not cached.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import make_transient_to_detached

from juli_backend.core.security import IdentityCache
from juli_backend.models.models import Shop
from juli_backend.services.reviewer.sandbox import PinMode


@dataclass(frozen=True)
class PinnedShop:
    """A plain snapshot of the pinned shop and what it is for the reviewer."""

    shop_values: dict[str, Any]
    pin: PinMode

    @property
    def shop_id(self) -> uuid.UUID:
        return uuid.UUID(str(self.shop_values["id"]))

    @property
    def owner_user_id(self) -> uuid.UUID:
        return uuid.UUID(str(self.shop_values["user_id"]))

    def shop(self) -> Shop:
        """A fresh detached ``Shop`` for this request (never a shared instance)."""
        shop = Shop(**self.shop_values)
        make_transient_to_detached(shop)
        return shop


_pinned: IdentityCache[uuid.UUID, PinnedShop] = IdentityCache()


def cached(shop_id: uuid.UUID) -> PinnedShop | None:
    hit = _pinned.get(shop_id)
    # Defence in depth: a value is only ever served under its own shop id.
    return hit if hit is not None and hit.shop_id == shop_id else None


def remember(shop: Shop, pin: PinMode) -> PinnedShop:
    values = {attr.key: getattr(shop, attr.key) for attr in sa_inspect(Shop).column_attrs}
    pinned = PinnedShop(shop_values=values, pin=pin)
    _pinned.put(shop.id, pinned)
    return pinned


def forget_cached() -> None:
    _pinned.clear()


__all__ = ["PinnedShop", "cached", "forget_cached", "remember"]
