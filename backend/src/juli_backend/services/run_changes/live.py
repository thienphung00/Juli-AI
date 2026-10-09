"""Read the live product a revert would restore (fast track P8-C).

The live value is read through the same guarded write resources the agent's
writes go through (``composition.build_write_resources``), because "the live
field" means the listing Juli wrote to. Called from the API process before a
revert run is created; the worker repeats the comparison right before the
write.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def read_live_product(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_product_id: str
) -> Mapping[str, Any]:
    del shop_id  # the write resources are bound to the shop Juli writes to
    from juli_backend.services.agent import composition as composition_module

    resources = await composition_module.build_write_resources(session)
    return resources.products.get_details(tiktok_product_id)
