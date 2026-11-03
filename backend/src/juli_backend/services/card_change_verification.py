"""The daily read-back verification across the fleet (the beat's body; P90 assisted execution).

For each Shopee shop: :func:`~juli_backend.services.card_events.verification.verify_shop` under
the shop's scope, one session and transaction per shop. A failure is counted and logged and the
next run tries again; logs carry counts and shop ids only, never values.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.card_events.verification import verify_shop
from juli_backend.services.ops.overview import list_shops

logger = logging.getLogger(__name__)

SHOPEE = "shopee"
SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class VerificationRun:
    shops: int = 0
    checked: int = 0
    verified: int = 0
    mismatch: int = 0
    not_seen: int = 0
    failed_shops: int = 0


async def run_verification(factory: SessionFactory, now: datetime | None = None) -> VerificationRun:
    moment = now or datetime.now(UTC)
    async with factory() as session:
        shop_ids = sorted(
            {s.shop_id for s in await list_shops(session) if s.platform == SHOPEE}, key=str
        )
    totals = {"checked": 0, "verified": 0, "mismatch": 0, "not_seen": 0}
    failed = 0
    for shop_id in shop_ids:
        try:
            async with factory() as session:
                async with with_shop_scope(session, shop_id):
                    counts = await verify_shop(session, shop_id, moment)
                    await session.commit()
        except Exception as exc:
            failed += 1
            logger.error(
                "card_change_verification_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
            continue
        for name in totals:
            totals[name] += getattr(counts, name)
    logger.info(
        "card_change_verification", extra={"shops": len(shop_ids), "failed": failed, **totals}
    )
    return VerificationRun(len(shop_ids), failed_shops=failed, **totals)
