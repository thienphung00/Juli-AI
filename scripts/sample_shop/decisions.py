"""Quyết định for the sample shop -- the loader's side of ``services/sample_shop/seed.py``.

P100 S2-G: the steps (and what they make: cards in Đề xuất / Đang thực hiện / Đo lường) live in
the backend, so the API's "Đặt lại dữ liệu mẫu" re-seeds exactly what this loader seeds. This
module keeps the loader's session handling: the history steps commit before the Connector's later
reads are ingested (``ingest_late``), then the read-back, the engine's cards and the approved cover.

Idempotent: the step runs only while the shop has no proposal; a re-run finds them and stops.
Only the loader's own sample shop gets here (``loader.ensure_shop`` has already refused anything
else). No LLM call.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.services.sample_shop.seed import (
    ACT_HOUR,
    APPROVED_COVER_PRODUCT,
    OPEN_COVER_PRODUCT,
    WINDOW_DAYS,
    DecisionsReport,
    SeedPlan,
    TitleSeed,
    VoucherSeed,
    approve_cover,
    has_proposals,
    propose,
    read_back,
    seed_history,
    seed_keywords,
    write_title_snapshots,
)
from scripts.sample_shop.generator import SampleShop


def plan_of(sample: SampleShop) -> SeedPlan:
    """The generated shop's decision plan (the same values ``seed.plan_for`` derives)."""
    v, t = sample.voucher, sample.title_change
    return SeedPlan(
        start_date=sample.start_date,
        end_date=sample.end_date,
        keywords=tuple(sample.keywords),
        voucher=(
            VoucherSeed(
                v.voucher_id, v.item_id, v.value, v.min_spend, v.quantity, v.starts_on, v.ends_on
            )
            if v is not None
            else None
        ),
        title=TitleSeed(t.item_id, t.old, t.new, t.applied_on) if t is not None else None,
    )


async def run(
    factory: async_sessionmaker[AsyncSession],
    sample: SampleShop,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    ingest_late: Callable[[], Awaitable[object]],
) -> DecisionsReport:
    """Replay the seller's and the Connector's steps (``services/sample_shop/seed.py``)."""
    from juli_backend.database import Shop
    from juli_backend.database.tenant_context import with_shop_scope

    report = DecisionsReport()
    plan = plan_of(sample)
    if plan.voucher is None or plan.title is None:
        report.skipped = True
        report.notes.append("history too short for the decision cards")
        return report
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            if await has_proposals(session, shop_id):
                report.skipped = True
                return report
            shop = await session.get(Shop, shop_id)
            assert shop is not None
            user_id = shop.user_id
            await seed_keywords(session, shop_id, plan, now)
            await seed_history(session, shop_id, plan, user_id=user_id)
            await session.commit()
    # the Connector's later reads: the new name (and the snapshots that carry it)
    await ingest_late()
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            await read_back(session, shop_id, plan, report)
            await session.commit()
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            await propose(session, shop_id, now=now, report=report)
            await session.commit()
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            await approve_cover(session, shop_id, user_id=user_id, now=now, report=report)
            await session.commit()
    return report


__all__ = [
    "ACT_HOUR",
    "APPROVED_COVER_PRODUCT",
    "OPEN_COVER_PRODUCT",
    "WINDOW_DAYS",
    "DecisionsReport",
    "plan_of",
    "run",
    "write_title_snapshots",
]
