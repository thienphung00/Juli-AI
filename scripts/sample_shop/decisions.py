"""Quyết định for the sample shop: cards in every tab, made through the app's own services.

The history ends on ``--end-date``. This module replays what a seller and the Connector would have
done on the way there, each step with the time it would have happened (the services all take
``now``), so nothing is written as a result:

- **Đo lường** (measured): a "Voucher đơn tối thiểu" the seller built in Tự tạo ~16 days before the
  end date, approved, started and read back from ``voucher_settings`` the next day. Its 7-day window
  closed 8 days before the end date; ``measure.read_change_sets`` (ADR-077 ratio-form DiD on the
  product's daily AOV against the other products) wrote the reading from the order rows.
- **Đo lường** (counting down): a "Sửa tên sản phẩm" built in Tự tạo, approved, applied 5 days
  before the end date and read back from ``item_catalog`` (the new name); its 7-day window is open.
- **Đang thực hiện**: one approved "Ảnh bìa" card the seller has not done yet.
- **Đề xuất**: the engine's own cards (``generate_cards`` as of the end date), sent to the shop.

Idempotent: the step runs only while the shop has no proposal; a re-run finds them and stops.
Only the loader's own sample shop gets here (``loader.ensure_shop`` has already refused anything
else). No LLM call: the engine computes with arithmetic, the title is a fixed string.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.sample_shop.catalog import PRODUCTS, VOUCHER_PRODUCT
from scripts.sample_shop.generator import GMT7, SampleShop

#: A seller does the Seller Centre work in the morning (GMT+7); the Connector reads at noon.
ACT_HOUR = 9
#: The window the seller picks for both measured cards (days).
WINDOW_DAYS = 7
#: The cover card the seller approved and has not done yet is on this product (index).
APPROVED_COVER_PRODUCT = 5
#: The cover card that stays in Đề xuất is on this product (index).
OPEN_COVER_PRODUCT = 4


@dataclass
class DecisionsReport:
    skipped: bool = False
    measured: int = 0
    counting: int = 0
    approved: int = 0
    proposed: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)


def _utc(day: date, hour: int = ACT_HOUR, minute: int = 0) -> datetime:
    """A GMT+7 wall-clock moment as the naive UTC the services store."""
    local = datetime.combine(day, datetime.min.time(), tzinfo=GMT7).replace(
        hour=hour, minute=minute
    )
    return local.astimezone(UTC).replace(tzinfo=None)


async def has_proposals(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    from juli_backend.models.shop_proposals import ShopProposal

    found = await session.scalar(
        select(func.count()).select_from(ShopProposal).where(ShopProposal.shop_id == shop_id)
    )
    return bool(found)


async def seed_keywords(
    session: AsyncSession, shop_id: uuid.UUID, sample: SampleShop, now: datetime
) -> int:
    """The shop's "Chính" keywords per product (the audit the Tiêu đề cards are held against)."""
    from juli_backend.models.shop_keywords import ShopKeywordSeed

    have = {
        (s.keyword, s.item_scope)
        for s in (
            await session.execute(select(ShopKeywordSeed).where(ShopKeywordSeed.shop_id == shop_id))
        ).scalars()
    }
    added = 0
    for item_id, keyword in sample.keywords:
        if (keyword, item_id) in have:
            continue
        session.add(
            ShopKeywordSeed(
                id=uuid.uuid4(),
                shop_id=shop_id,
                platform="shopee",
                keyword=keyword,
                pattern="common_phrase",
                item_ids=[item_id],
                role="chinh",
                item_scope=item_id,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        added += 1
    await session.flush()
    return added


async def write_title_snapshots(
    session: AsyncSession, shop_id: uuid.UUID, sample: SampleShop
) -> int:
    """The item snapshots that carry the title: the old one when the history starts, the new one
    after the change (the gateway's ``item_snapshot`` has no title column; the title it reads
    lives in ``platform_items.name``, so these two rows are written like the tracked-field rows)."""
    from juli_backend.models.shopee_profit import PlatformItemSnapshot

    change = sample.title_change
    if change is None:
        return 0
    first = _utc(sample.start_date, 8, 30)
    after = _utc(change.applied_on, 14, 30)
    written = 0
    for at, title in ((first, change.old), (after, change.new)):
        exists = await session.scalar(
            select(func.count())
            .select_from(PlatformItemSnapshot)
            .where(
                PlatformItemSnapshot.shop_id == shop_id,
                PlatformItemSnapshot.platform == "shopee",
                PlatformItemSnapshot.item_id == change.item_id,
                PlatformItemSnapshot.variation_id == "",
                PlatformItemSnapshot.captured_at == at,
            )
        )
        if exists:
            continue
        product = next(p for p in PRODUCTS if p.item_id == change.item_id)
        prices = [v.price for v in product.variations]
        session.add(
            PlatformItemSnapshot(
                id=uuid.uuid4(),
                shop_id=shop_id,
                platform="shopee",
                item_id=change.item_id,
                variation_id="",
                captured_at=at,
                title=title,
                image_urls=[f"sample_{product.parent_sku.lower()}_cover"],
                image_hashes=[],
                category_path=[],
                list_price=max(prices),
                current_price=min(prices),
                stock=sum(v.stock for v in product.variations),
                source="extension",
                source_rank=1,
            )
        )
        written += 1
    await session.flush()
    return written


async def run(
    factory: async_sessionmaker[AsyncSession],
    sample: SampleShop,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    ingest_late: Callable[[], Awaitable[object]],
) -> DecisionsReport:
    """Replay the seller's and the Connector's steps (see the module docstring)."""
    from juli_backend.database import Shop
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.card_events import verification
    from juli_backend.services.shopee_recommendations import (
        change_sets,
        measure,
        service,
        store,
    )
    from juli_backend.services.shopee_recommendations.manual import Actor, create_manual

    report = DecisionsReport()
    voucher, change = sample.voucher, sample.title_change
    if voucher is None or change is None:
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
            await seed_keywords(session, shop_id, sample, now)
            actor = Actor("seller", user_id)

            async def build(variant: dict, made: datetime, as_of: date) -> uuid.UUID:
                out = await create_manual(
                    session, shop_id, [variant], 0, True, actor, now=made, as_of=as_of
                )
                return uuid.UUID(out["id"])

            async def approve_and_do(
                card_id: uuid.UUID, decided: datetime, done: datetime, voucher_id: str | None
            ) -> uuid.UUID:
                await service.decide(
                    session, shop_id, card_id, decision="approve", user_id=user_id, now=decided
                )
                out = await service.mark_executed(
                    session,
                    shop_id,
                    card_id,
                    now=done,
                    executed_at=done,
                    user_id=user_id,
                    voucher_id=voucher_id,
                )
                cs = uuid.UUID(out["change_set"]["id"])
                await change_sets.set_window(session, shop_id, cs, WINDOW_DAYS, now=done)
                return cs

            # 1. the voucher: built the day before it starts, started that morning
            v_item = PRODUCTS[VOUCHER_PRODUCT].item_id
            made = _utc(voucher.starts_on - timedelta(days=1))
            vid = await build(
                {
                    "change_kind": "min_spend_voucher",
                    "items": [v_item],
                    "inputs": {
                        "value": voucher.value,
                        "min_spend": voucher.min_spend,
                        "quantity": voucher.quantity,
                        "days": (voucher.ends_on - voucher.starts_on).days,
                    },
                },
                made,
                voucher.starts_on - timedelta(days=1),
            )
            await approve_and_do(
                vid,
                made + timedelta(hours=1),
                _utc(voucher.starts_on, ACT_HOUR, 30),
                voucher.voucher_id,
            )
            # 2. the title: built the day before, applied that morning
            t_made = _utc(change.applied_on - timedelta(days=1))
            tid = await build(
                {
                    "change_kind": "title",
                    "items": [change.item_id],
                    "inputs": {"title": change.new},
                    "extra": {
                        "current_title": change.old,
                        "core": [k for i, k in sample.keywords if i == change.item_id],
                        "notes": [],
                    },
                },
                t_made,
                change.applied_on - timedelta(days=1),
            )
            await approve_and_do(
                tid, t_made + timedelta(hours=1), _utc(change.applied_on, ACT_HOUR, 30), None
            )
            await session.commit()
    # 3. the Connector's later reads: the new name (and the snapshots that carry it)
    await ingest_late()
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            await write_title_snapshots(session, shop_id, sample)
            read_at = _utc(sample.end_date + timedelta(days=1), 1)
            await verification.verify_shop(session, shop_id, read_at)
            lr = measure.LearningReport()
            await measure.read_change_sets(session, shop_id, sample.end_date, lr)
            report.measured = lr.readings
            report.notes.append(f"measure skipped: {lr.skipped}")
            await session.commit()
    # 4. the engine's own cards as of the end date, sent to the shop
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            gen = await service.generate_cards(session, shop_id, now=now)
            report.proposed.update(gen.by_kind)
            await service.publish(session, shop_id, None, now=now)
            await session.commit()
    # 5. the seller approved one cover card and has not done it yet
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            item = PRODUCTS[APPROVED_COVER_PRODUCT].item_id
            for p, card in await store.list_cards(session, shop_id, statuses=["sent"]):
                if card["change_kind"] == "cover_image" and p.item_id == item:
                    await service.decide(
                        session, shop_id, p.id, decision="approve", user_id=user_id,
                        now=now - timedelta(hours=2),
                    )  # fmt: skip
                    report.approved += 1
                    break
            else:
                report.notes.append("no cover card to approve")
            await session.commit()
    return report
