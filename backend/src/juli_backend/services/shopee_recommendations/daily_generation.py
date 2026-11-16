"""New Shopee recommendation cards every day, from the system rules, sent to the seller.

``run_shop`` (inside the shop's tenant scope; the caller commits) for ONE real Shopee shop:

1. only ``shops.kind = 'real'`` Shopee shops: never the reviewer's sample shop (it has its own
   reset) and never a sandbox shop;
2. one run per (shop, local day): the cycle key ``daily-YYYY-MM-DD`` is written on every card the
   run saves, and a shop that already has a card of that cycle is skipped (``already_done``);
3. a shop whose newest orders or traffic day is older than ``forecast_base.stale_marker`` allows
   (EXPECTED_LAG_DAYS + grace, judged against the local day) gets no new cards (``stale``);
4. ``generate_cards(persist=True, max_cards=DAILY_MAX_CARDS)``: the engine's own product queue
   (one open card per product), locks and ranking decide what is new, so a rerun adds nothing;
5. the new cards go straight to the seller's Đề xuất (``publish`` of exactly those ids): no Ops
   send step.

Triggers: the Connector's daily run report (``POST /v1/ingest/connector-ticks``, one task per
shop) and the 02:00 UTC beat (``run_all``: every real Shopee shop with no daily generation yet).
One session per shop; a failure is counted and logged (type only) and stops no other shop.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Shop
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.ops.overview import list_shops
from juli_backend.services.shopee_analytics import forecast_base
from juli_backend.services.shopee_recommendations import config, service
from juli_backend.services.shopee_recommendations.loader import load_env

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Any]

#: Vietnam local day (GMT+7), the seller's day.
LOCAL_OFFSET = timedelta(hours=7)
#: At most this many new cards a day per shop (the engine's own queue and ranking cut first).
DAILY_MAX_CARDS = config.DEFAULT_TOP_N
CYCLE_PREFIX = "daily-"

STATUS_DONE = "done"
STATUS_ALREADY_DONE = "already_done"
STATUS_STALE = "stale"
STATUS_NOT_REAL = "not_real"
STATUS_NO_DATA = "no_data"
STATUS_NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ShopRun:
    status: str
    generated: int = 0
    sent: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class RunSummary:
    shops: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    cards: int = 0


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def local_day(now: datetime) -> date:
    return (now + LOCAL_OFFSET).date()


def cycle_key(day: date) -> str:
    return f"{CYCLE_PREFIX}{day.isoformat()}"


def _is_sample(shop: Shop) -> bool:
    from juli_backend.services.stock_alert.settings import is_sample_shop

    return is_sample_shop(shop)


async def _already_generated(session: AsyncSession, shop_id: uuid.UUID, cycle: str) -> bool:
    n = await session.scalar(
        select(func.count())
        .select_from(ShopProposal)
        .where(ShopProposal.shop_id == shop_id, ShopProposal.cycle == cycle)
    )
    return bool(n)


async def run_shop(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> ShopRun:
    moment = (now or _now()).replace(tzinfo=None)
    today = local_day(moment)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.platform != "shopee":
        return ShopRun(STATUS_NOT_FOUND)
    if (shop.kind or "real") != "real" or _is_sample(shop):
        return ShopRun(STATUS_NOT_REAL)
    cycle = cycle_key(today)
    if await _already_generated(session, shop_id, cycle):
        return ShopRun(STATUS_ALREADY_DONE)
    env = await load_env(session, shop_id, now=moment)
    if env is None:
        return ShopRun(STATUS_NO_DATA)
    env.today = today
    marker = forecast_base.stale_marker(forecast_base.last_days(env.funnel_history), today)
    if marker is not None:
        return ShopRun(STATUS_STALE, reason=f"{marker.dataset}_through_{marker.through}")
    report = await service.generate_cards(
        session,
        shop_id,
        now=moment,
        cycle=cycle,
        persist=True,
        max_cards=DAILY_MAX_CARDS,
        env=env,
    )
    ids = [uuid.UUID(c) for c in report.card_ids]
    sent = await service.publish(session, shop_id, ids, now=moment) if ids else []
    return ShopRun(STATUS_DONE, generated=report.persisted, sent=len(sent))


async def run_one(
    factory: SessionFactory, shop_id: uuid.UUID, reason: str, *, now: datetime | None = None
) -> ShopRun:
    """One shop in its own session and scope, committed; logs the outcome."""
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            result = await run_shop(session, shop_id, now=now)
            await session.commit()
    logger.info(
        "shopee_daily_cards_shop",
        extra={
            "shop_id": str(shop_id),
            "reason": reason,
            "status": result.status,
            "generated": result.generated,
            "sent": result.sent,
            "skip_reason": result.reason,
        },
    )
    return result


async def run_all(
    factory: SessionFactory, reason: str = "daily_beat", *, now: datetime | None = None
) -> RunSummary:
    """Every Shopee shop with no daily generation yet today; never raises."""
    try:
        async with factory() as session:
            shop_ids = [s.shop_id for s in await list_shops(session) if s.platform == "shopee"]
    except Exception as exc:
        logger.error("shopee_daily_cards_list_failed", extra={"error_type": type(exc).__name__})
        return RunSummary(failed=1)
    done = skipped = failed = cards = 0
    for shop_id in shop_ids:
        try:
            result = await run_one(factory, shop_id, reason, now=now)
        except Exception as exc:  # type only: a message can carry client values
            failed += 1
            logger.error(
                "shopee_daily_cards_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
            continue
        if result.status == STATUS_DONE:
            done += 1
            cards += result.sent
        else:
            skipped += 1
    summary = RunSummary(len(shop_ids), done, skipped, failed, cards)
    logger.info(
        "shopee_daily_cards",
        extra={
            "reason": reason,
            "shops": summary.shops,
            "done": summary.done,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "cards": summary.cards,
        },
    )
    return summary


__all__ = [
    "DAILY_MAX_CARDS",
    "RunSummary",
    "ShopRun",
    "cycle_key",
    "local_day",
    "run_all",
    "run_one",
    "run_shop",
]
