"""Users and the shops they own.

``User`` and ``Shop`` sit *above* the tenant boundary -- a shop *is* the tenant
-- so these two repositories are the only ones in the package that are not
:class:`~juli_backend.repositories._base.ShopScopedRepo` subclasses. They are
scoped by ``user_id`` instead.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import Shop, User
from juli_backend.repositories._base import SessionRepo


class UsersRepo(SessionRepo):
    async def get(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFound(f"User {user_id} not found")
        return user

    async def get_or_create(self, user_id: uuid.UUID, phone: str) -> User:
        """Return the user with ``user_id``, creating it with ``phone`` when absent."""
        existing = await self._session.get(User, user_id)
        if existing is not None:
            return existing
        return await self._add(User(id=user_id, phone=phone))


class ShopsRepo(SessionRepo):
    async def list(self, user_id: uuid.UUID) -> list[Shop]:
        return await self._all(select(Shop).where(Shop.user_id == user_id))

    async def get_by_tiktok_id(self, tiktok_shop_id: str) -> Shop | None:
        """Find the shop bound to a TikTok shop id, or ``None``."""
        return await self._one_or_none(select(Shop).where(Shop.tiktok_shop_id == tiktok_shop_id))

    async def create(
        self,
        user_id: uuid.UUID,
        shop_name: str,
        tiktok_shop_id: str | None = None,
    ) -> Shop:
        return await self._add(
            Shop(
                id=uuid.uuid4(),
                user_id=user_id,
                shop_name=shop_name,
                tiktok_shop_id=tiktok_shop_id,
            )
        )

    async def pause_automation(self, shop_id: uuid.UUID) -> None:
        """Deactivate a shop after the seller deauthorizes the app (#354).

        A missing shop is a no-op: the deauthorization webhook may arrive for a
        shop that was never fully onboarded, and there is nothing to pause.
        """
        shop = await self._session.get(Shop, shop_id)
        if shop is None:
            return
        shop.is_active = False
        await self._session.flush()


__all__ = ["ShopsRepo", "UsersRepo"]
