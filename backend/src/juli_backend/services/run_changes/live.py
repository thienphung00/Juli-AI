"""Read the live product a revert would restore (fast track P8-C, P61-F).

The live value is read through the SAME resources mode the run being reverted
wrote with, because "the live field" means the listing Juli wrote to:

- a ``live`` run (P61-F) wrote to the shop's own listing, so the three-way check
  reads that listing through the shop's own production read credential
  (``composition.build_read_resources`` -- never the sandbox, never another
  shop's);
- a ``simulated`` run, and a run from before ``write_mode`` existed (NULL, every
  one of which wrote to the sandbox), wrote to the sandbox merchant, so the
  check reads the sandbox listing (``composition.build_write_resources``, the
  guarded sandbox write resources, as before).

Called from the API process before a revert run is created; the worker repeats
the comparison right before the write.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WRITE_MODE_LIVE


async def read_live_product(
    session: AsyncSession,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    write_mode: str | None = None,
) -> Mapping[str, Any]:
    from juli_backend.services.agent import composition as composition_module

    if write_mode == WRITE_MODE_LIVE:
        read_resources = await composition_module.build_read_resources(session, shop_id)
        return read_resources.products.get_details(tiktok_product_id)
    resources = await composition_module.build_write_resources(session)
    return resources.products.get_details(tiktok_product_id)
