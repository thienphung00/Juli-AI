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
from juli_backend.database.tenant_context import with_user_scope
from juli_backend.models.models import Shop, User
from juli_backend.repositories._base import SessionRepo


class UsersRepo(SessionRepo):
    async def get(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFound(f"User {user_id} not found")
        return user

    async def get_for_authentication(self, user_id: uuid.UUID) -> User:
        """Read one user during authentication, under a scope of its own (#1691).

        THE CIRCULARITY. `users` carries
        `users_select_public USING (id = app_current_user_id())`. Authentication
        must read `users` to learn who the caller is — but the policy wants that
        answer first. Under the owner-exempt runtime the policy did not apply and
        the plain `get` above worked; as `juli_app` it returned nothing, and every
        authenticated request 401'd with "User not found" for a row that exists.
        Measured on production 2026-09-07: 0 rows visible as `juli_app` with no
        GUC, 1 on the owner connection.

        WHY THIS LIVES HERE AND NOT IN THE AUTH DEPENDENCY. ADR-085 decision 2 is
        explicit that the tenant seam "is not `core/security/dependencies.py`" —
        W6 keeps sole ownership of that module. A repository, by contrast, is
        exactly the layer that should know what its own table's policy requires.
        The auth dependency calls this by name and stays free of tenant-context
        imports.

        WHY IT IS NOT A BYPASS. `user_id` is `sub` from a JWT the caller has
        already verified against `SUPABASE_JWT_SECRET`, so the application asserts
        an identity it has cryptographic grounds to assert. The policy still does
        the narrowing — measured with the GUC set from `sub`:

            own row visible: 1   another user's row: 0   total rows visible: 1

        A separate method rather than a flag on `get`, so that every caller of the
        scoped read is greppable and the exception cannot spread silently.
        """
        async with with_user_scope(self._session, user_id):
            return await self.get(user_id)

    async def get_or_create(self, user_id: uuid.UUID, phone: str) -> User:
        """Return the user with ``user_id``, creating it with ``phone`` when absent."""
        existing = await self._session.get(User, user_id)
        if existing is not None:
            return existing
        return await self._add(User(id=user_id, phone=phone))


class ShopsRepo(SessionRepo):
    async def list(self, user_id: uuid.UUID) -> list[Shop]:
        return await self._all(select(Shop).where(Shop.user_id == user_id))

    async def list_for_authorization(self, user_id: uuid.UUID) -> list[Shop]:
        """List a user's shops during the request bootstrap, under a user scope (#1697).

        THE SECOND AND LAST PRE-SCOPE READ. `shops` carries
        `shops_select_public USING (user_id = app_current_user_id())`, and
        `get_active_shop` runs this before any tenant context exists — #1691's
        scope is a loan and has already been handed back. With no GUC the read
        returns nothing, no shop matches the `X-Shop-Id` header, and every
        authenticated request ends in `403 Shop not accessible`.

        Measured on the deployed connection as `juli_app`:

            no GUC                     shops by user_id: 0
            app.current_user_id set    shops by user_id: 2

        WHY A USER SCOPE AND NOT A SHOP SCOPE. This read answers "which shops
        does this user own?", so that the header's shop id can be checked
        against the answer. Scoping it by that same shop id would assume the
        conclusion — the header is exactly what is not yet trusted.

        The chain ends here. `api/dependencies.py` calls
        `_apply_tenant_context_to_session` immediately after this read, and
        everything downstream runs scoped; `users` (#1691) and `shops` are the
        only two reads that precede it.

        A separate method rather than a flag on `list`, for the same reason as
        `UsersRepo.get_for_authentication`: the bootstrap exception stays
        greppable and cannot spread to ordinary callers, who already hold a scope.
        """
        async with with_user_scope(self._session, user_id):
            return await self.list(user_id)

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
