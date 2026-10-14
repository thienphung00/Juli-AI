"""Enter one shop's read scope through the ops path -- "Xem như shop" (D25.3).

Moved out of ``api/routes/ops.py`` (P32-A) so the partner reviewer path (D42)
pins its session to the reference shop with exactly the machinery staff use to
view a shop: ``juli_ops`` finds the shop, and the seller's own tenant GUCs
(shop + owner) are set from the very row it returned, so every read after it
runs under the seller's RLS scope. Read-only by construction for both callers:
"Xem như shop" refuses every non-GET (D25.3 amended), the reviewer gate
allowlists reads only (``api/reviewer.py``).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import Shop
from juli_backend.database.tenant_context import _apply_tenant_context_to_session
from juli_backend.services.ops import overview
from juli_backend.services.ops.access import ops_role


async def enter_shop_read_scope(session: AsyncSession, shop_id: uuid.UUID) -> Shop | None:
    """Load the shop and set its seller's tenant scope; None when there is no such shop.

    P29: on Postgres the ops read, the switch back from ``juli_ops`` and the
    tenant GUCs are ONE statement (``overview.find_shop_entering_seller_scope``).
    """
    async with ops_role(session) as block:
        previous_role = block.hand_over()
        if previous_role is None:
            # SQLite, or already juli_ops: no switch to undo -- the plain path.
            listing = await overview.find_shop(session, shop_id)
        else:
            listing = await overview.find_shop_entering_seller_scope(
                session, shop_id, restore_role=previous_role
            )
            if listing is None:
                await overview.leave_ops_role(session, previous_role)
                return None
    if listing is None:
        return None
    if previous_role is None:
        await _apply_tenant_context_to_session(session, listing.shop_id, listing.owner_user_id)
    return await session.get(Shop, listing.shop_id)


__all__ = ["enter_shop_read_scope"]
