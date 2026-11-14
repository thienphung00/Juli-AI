"""Quyết định for the sample shop: cards in every tab, made through the app's own services.

Moved from ``scripts/sample_shop/decisions.py`` (P100 S2-G) so any backend caller re-seeds exactly
what the loader seeds, without importing ``scripts/``. The reset itself is an operator command
(``python -m scripts.sample_shop --reset``, owner decision (c)): no API route.
The loader keeps its own session handling and calls the steps below.

The history ends on the plan's ``end_date``. The steps replay what a seller and the Connector would
have done on the way there, each with the time it would have happened (the services all take
``now``), so nothing is written as a result:

- **Đo lường** (measured): a "Voucher đơn tối thiểu" the seller built in Tự tạo ~16 days before the
  end date, approved, started and read back from ``voucher_settings`` the next day. Its 7-day window
  closed 8 days before the end date; ``measure.read_change_sets`` (ADR-077 ratio-form DiD on the
  product's daily AOV against the other products) wrote the reading from the order rows.
- **Đo lường** (counting down): a "Sửa tên sản phẩm" built in Tự tạo, approved, applied 5 days
  before the end date and read back from ``item_catalog`` (the new name); its 7-day window is open.
- **Đang thực hiện**: one approved "Ảnh bìa" card the seller has not done yet.
- **Đề xuất**: the engine's own cards (``generate_cards`` as of ``now``), sent to the shop.
- **Nội dung** (P100 S2-D): the pre-written titles, banners and style profile
  (``content_specs.seed_content_specs``), after the cards they belong to.

No LLM call: the engine computes with arithmetic, the title is a fixed string. Every step takes
the caller's session and leaves the commit to the caller.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.sample_shop.catalog import (
    KEYWORDS,
    NEW_TITLE,
    PRODUCTS,
    TITLE_APPLIED_DAYS_BEFORE_END,
    TITLE_PRODUCT,
    VOUCHER_DAYS,
    VOUCHER_ID,
    VOUCHER_MIN_SPEND,
    VOUCHER_PRODUCT,
    VOUCHER_QUANTITY,
    VOUCHER_START_DAYS_BEFORE_END,
    VOUCHER_VALUE,
)

GMT7 = timezone(timedelta(hours=7))
#: The generator's history length (``scripts/sample_shop/generator.DAYS``): the decision cards
#: need the full 30 days (the voucher reading needs the 14 days before it).
HISTORY_DAYS = 30
#: A seller does the Seller Centre work in the morning (GMT+7); the Connector reads at noon.
ACT_HOUR = 9
#: The window the seller picks for both measured cards (days).
WINDOW_DAYS = 7
#: The cover card the seller approved and has not done yet is on this product (index).
APPROVED_COVER_PRODUCT = 5
#: The cover card that stays in Đề xuất is on this product (index).
OPEN_COVER_PRODUCT = 4


@dataclass(frozen=True)
class VoucherSeed:
    """The one shop voucher the history holds (the generator's ``VoucherRun`` settings)."""

    voucher_id: str
    item_id: str
    value: int
    min_spend: int
    quantity: int
    starts_on: date
    ends_on: date


@dataclass(frozen=True)
class TitleSeed:
    """A product's title as the seller changed it: ``old`` until ``applied_on``, ``new`` after."""

    item_id: str
    old: str
    new: str
    applied_on: date


@dataclass(frozen=True)
class SeedPlan:
    """What the decision cards are made of -- plain values, the same the generator uses."""

    start_date: date
    end_date: date
    #: (item_id, keyword): the "Chính" keywords written to ``shop_keyword_seeds``
    keywords: tuple[tuple[str, str], ...]
    voucher: VoucherSeed | None
    title: TitleSeed | None


@dataclass
class DecisionsReport:
    skipped: bool = False
    measured: int = 0
    counting: int = 0
    approved: int = 0
    #: P100 S2-D: seeded ``card_content_specs`` rows (style profile + titles + banners)
    content_specs: int = 0
    proposed: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)


def plan_for(end_date: date, *, days: int = HISTORY_DAYS) -> SeedPlan:
    """The plan of a history of ``days`` days ending on ``end_date`` (no cards when shorter)."""
    start = end_date - timedelta(days=days - 1)
    keywords = tuple((PRODUCTS[i].item_id, kw) for i, kw in KEYWORDS)
    if days < HISTORY_DAYS:
        return SeedPlan(start, end_date, keywords, None, None)
    v_start = end_date - timedelta(days=VOUCHER_START_DAYS_BEFORE_END)
    voucher = VoucherSeed(
        VOUCHER_ID,
        PRODUCTS[VOUCHER_PRODUCT].item_id,
        VOUCHER_VALUE,
        VOUCHER_MIN_SPEND,
        VOUCHER_QUANTITY,
        v_start,
        v_start + timedelta(days=VOUCHER_DAYS),
    )
    title = TitleSeed(
        PRODUCTS[TITLE_PRODUCT].item_id,
        PRODUCTS[TITLE_PRODUCT].name,
        NEW_TITLE,
        end_date - timedelta(days=TITLE_APPLIED_DAYS_BEFORE_END),
    )
    return SeedPlan(start, end_date, keywords, voucher, title)


def utc_at(day: date, hour: int = ACT_HOUR, minute: int = 0) -> datetime:
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
    session: AsyncSession, shop_id: uuid.UUID, plan: SeedPlan, now: datetime
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
    for item_id, keyword in plan.keywords:
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


async def write_title_snapshots(session: AsyncSession, shop_id: uuid.UUID, plan: SeedPlan) -> int:
    """The item snapshots that carry the title: the old one when the history starts, the new one
    after the change (the gateway's ``item_snapshot`` has no title column; the title it reads
    lives in ``platform_items.name``, so these two rows are written like the tracked-field rows).
    Idempotent: a snapshot already captured at that moment is left alone."""
    from juli_backend.models.shopee_profit import PlatformItemSnapshot

    change = plan.title
    if change is None:
        return 0
    first = utc_at(plan.start_date, 8, 30)
    after = utc_at(change.applied_on, 14, 30)
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
                image_urls=[product.cover_url],
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


async def seed_history(
    session: AsyncSession, shop_id: uuid.UUID, plan: SeedPlan, *, user_id: uuid.UUID
) -> None:
    """Steps 1-2: the voucher and the title, built in Tự tạo, approved, done, window set."""
    from juli_backend.services.shopee_recommendations import change_sets, service
    from juli_backend.services.shopee_recommendations.manual import Actor, create_manual

    voucher, change = plan.voucher, plan.title
    assert voucher is not None and change is not None
    actor = Actor("seller", user_id)

    async def build(variant: dict[str, Any], made: datetime, as_of: date) -> uuid.UUID:
        out = await create_manual(
            session, shop_id, [variant], 0, True, actor, now=made, as_of=as_of
        )
        return uuid.UUID(out["id"])

    async def approve_and_do(
        card_id: uuid.UUID, decided: datetime, done: datetime, voucher_id: str | None
    ) -> None:
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

    # 1. the voucher: built the day before it starts, started that morning
    made = utc_at(voucher.starts_on - timedelta(days=1))
    vid = await build(
        {
            "change_kind": "min_spend_voucher",
            "items": [voucher.item_id],
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
        vid, made + timedelta(hours=1), utc_at(voucher.starts_on, ACT_HOUR, 30), voucher.voucher_id
    )
    # 2. the title: built the day before, applied that morning
    t_made = utc_at(change.applied_on - timedelta(days=1))
    tid = await build(
        {
            "change_kind": "title",
            "items": [change.item_id],
            "inputs": {"title": change.new},
            "extra": {
                "current_title": change.old,
                "core": [k for i, k in plan.keywords if i == change.item_id],
                "notes": [],
            },
        },
        t_made,
        change.applied_on - timedelta(days=1),
    )
    await approve_and_do(
        tid, t_made + timedelta(hours=1), utc_at(change.applied_on, ACT_HOUR, 30), None
    )


async def read_back(
    session: AsyncSession, shop_id: uuid.UUID, plan: SeedPlan, report: DecisionsReport
) -> None:
    """Step 3, after the Connector's later reads: the title snapshots, the read-back of both
    changes and the measurement of the closed window."""
    from juli_backend.services.card_events import verification
    from juli_backend.services.shopee_recommendations import measure

    await write_title_snapshots(session, shop_id, plan)
    read_at = utc_at(plan.end_date + timedelta(days=1), 1)
    await verification.verify_shop(session, shop_id, read_at)
    lr = measure.LearningReport()
    await measure.read_change_sets(session, shop_id, plan.end_date, lr)
    report.measured = lr.readings
    report.notes.append(f"measure skipped: {lr.skipped}")


async def propose(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, report: DecisionsReport
) -> None:
    """Step 4: the engine's own cards as of ``now``, sent to the shop."""
    from juli_backend.services.shopee_recommendations import service

    gen = await service.generate_cards(session, shop_id, now=now)
    report.proposed.update(gen.by_kind)
    await service.publish(session, shop_id, None, now=now)


async def approve_cover(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    now: datetime,
    report: DecisionsReport,
) -> None:
    """Step 5: the seller approved one cover card and has not done it yet."""
    from juli_backend.services.shopee_recommendations import service, store

    item = PRODUCTS[APPROVED_COVER_PRODUCT].item_id
    for p, card in await store.list_cards(session, shop_id, statuses=["sent"]):
        if card["change_kind"] == "cover_image" and p.item_id == item:
            await service.decide(
                session, shop_id, p.id, decision="approve", user_id=user_id,
                now=now - timedelta(hours=2),
            )  # fmt: skip
            report.approved += 1
            return
    report.notes.append("no cover card to approve")


async def seed_content(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, report: DecisionsReport
) -> None:
    """Step 6 (P100 S2-D): the seeded titles, banners and style profile (no LLM call)."""
    from juli_backend.services.sample_shop.content_specs import seed_content_specs

    made = await seed_content_specs(session, shop_id, now=now)
    report.content_specs += made.style_profile + made.titles + made.banners


async def seed_all(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: SeedPlan,
    *,
    user_id: uuid.UUID,
    now: datetime,
) -> DecisionsReport:
    """Every step in ONE transaction (the caller holds the shop's scope and commits): for a shop
    whose data rows, the Connector's later reads included, are already in place (the reset)."""
    report = DecisionsReport()
    if plan.voucher is None or plan.title is None:
        report.skipped = True
        report.notes.append("history too short for the decision cards")
        return report
    await seed_keywords(session, shop_id, plan, now)
    await seed_history(session, shop_id, plan, user_id=user_id)
    await session.flush()
    await read_back(session, shop_id, plan, report)
    await session.flush()
    await propose(session, shop_id, now=now, report=report)
    await session.flush()
    await approve_cover(session, shop_id, user_id=user_id, now=now, report=report)
    await session.flush()
    await seed_content(session, shop_id, now=now, report=report)
    return report


__all__ = [
    "ACT_HOUR",
    "APPROVED_COVER_PRODUCT",
    "HISTORY_DAYS",
    "OPEN_COVER_PRODUCT",
    "WINDOW_DAYS",
    "DecisionsReport",
    "SeedPlan",
    "TitleSeed",
    "VoucherSeed",
    "approve_cover",
    "has_proposals",
    "plan_for",
    "propose",
    "read_back",
    "seed_all",
    "seed_content",
    "seed_history",
    "seed_keywords",
    "utc_at",
    "write_title_snapshots",
]
