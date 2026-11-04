"""The daily learning / calibration run of the Shopee recommendations (P91 D-14; the body of the
step the daily KPI beat runs right after the KPI run and the proposal measurement).

For each PILOT Shopee shop: ``shopee_recommendations.measure.run_learning`` under the shop's
scope -- score the finished plans and change sets, pool them with the stored natural
experiments, refresh the shop's calibration and requeue its cards. DB only (no Seller Centre,
no LLM), idempotent: a second run on the same day recomputes the same rows.

Pilot shops = Shopee shops whose Ops stage is "Pilot đặc biệt" (``ops_shop_settings.stage``), plus
any id listed in ``RECO_LEARNING_SHOP_IDS`` (comma separated; empty by default). Every other shop
is left alone: nobody else has executed cards to learn from yet. Ops can still run it by hand
(``POST .../recommendations/learning/run``).

Each shop runs in its own session and transaction: a failure is counted and logged and never stops
the rest. Logs carry counts and shop ids only, never values.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ops import STAGE_PILOT, OpsShopSettings
from juli_backend.services.ops import ops_role
from juli_backend.services.ops.overview import list_shops
from juli_backend.services.shopee_recommendations import measure

logger = logging.getLogger(__name__)

SHOPEE = "shopee"
ENV_SHOP_IDS = "RECO_LEARNING_SHOP_IDS"
SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class DailyLearningSummary:
    """Per-run counts, logged and returned by the beat step (counts only)."""

    shops: int = 0
    failed: int = 0
    observations: int = 0
    calibration_rows: int = 0


def _extra_ids() -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for part in os.environ.get(ENV_SHOP_IDS, "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(uuid.UUID(part))
        except ValueError:
            logger.warning("reco_learning_bad_shop_id")  # the value itself is not logged
    return out


async def pilot_shop_ids(session: Any) -> list[uuid.UUID]:
    """Shopee shops in the Ops stage "pilot" or listed in ``RECO_LEARNING_SHOP_IDS``."""
    shopee = {s.shop_id for s in await list_shops(session) if s.platform == SHOPEE}
    async with ops_role(session):
        staged = set(
            (
                await session.execute(
                    select(OpsShopSettings.shop_id).where(OpsShopSettings.stage == STAGE_PILOT)
                )
            )
            .scalars()
            .all()
        )
    return sorted(shopee & (staged | _extra_ids()), key=str)


async def run_daily_learning(
    factory: SessionFactory, *, now: datetime | None = None
) -> DailyLearningSummary:
    """Run the learning step for every pilot shop, one session each."""
    moment = now if now is not None else datetime.now(UTC).replace(tzinfo=None)
    async with factory() as session:
        shop_ids = await pilot_shop_ids(session)
    failed = observations = rows = 0
    for shop_id in shop_ids:
        try:
            async with factory() as session:
                async with with_shop_scope(session, shop_id):
                    report = await measure.run_learning(session, shop_id, now=moment)
                    await session.commit()
        except Exception as exc:
            failed += 1
            # Type only: a message can carry row values (client data).
            logger.error(
                "shopee_reco_learning_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
            continue
        observations += report.observations_total
        rows += report.states
    summary = DailyLearningSummary(len(shop_ids), failed, observations, rows)
    logger.info(
        "shopee_reco_learning_daily",
        extra={
            "shops": summary.shops,
            "failed": summary.failed,
            "observations": summary.observations,
            "calibration_rows": summary.calibration_rows,
        },
    )
    return summary
