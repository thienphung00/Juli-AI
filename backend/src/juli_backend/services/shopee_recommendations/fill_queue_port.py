"""P97 T4: the port to T3's fill queue (D85.6): approving a card queues one fill job per target.

T3 owns ``services/shopee_recommendations/fill_queue.py`` with

    enqueue_for_approval(session, *, shop_id, proposal_id, version, targets=None, group_code=None)

When that module is on this branch the call goes to it; until then this module is the stub with the
same signature, so the plan's confirm and the group approval call ONE name and integration only has
to delete the stub. ``targets`` None = the targets the card payload carries (``card["targets"]``);
``group_code`` is the ``JC-...-G<letter>`` of the group the version is approved in, if any.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_for_approval(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    version: int,
    targets: Sequence[dict[str, Any]] | None = None,
    group_code: str | None = None,
) -> Any:
    try:
        real = importlib.import_module("juli_backend.services.shopee_recommendations.fill_queue")
    except ModuleNotFoundError:
        return None  # T3's fill queue is not merged yet: nothing is queued
    return await real.enqueue_for_approval(
        session,
        shop_id=shop_id,
        proposal_id=proposal_id,
        version=version,
        targets=list(targets) if targets is not None else None,
        group_code=group_code,
    )


__all__ = ["enqueue_for_approval"]
