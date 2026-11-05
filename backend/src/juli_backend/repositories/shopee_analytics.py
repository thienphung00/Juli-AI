"""Read-only access to the Shopee tables the analytics read APIs (P90 step 7) aggregate.

Every class here is a :class:`ShopScopedRepo` (or, for the public fee table, a
:class:`SessionRepo`) used for reading only: the writers of these tables are the ingest
gateway (``services/ingest``, one-writer rule) and the settings import. Queries take the
window as plain dates; a ``datetime`` bound is naive UTC like every persistence-edge time.

The order-line repo returns the PII-free ``shopee_order_lines`` columns only (the table has
no buyer column); ``order_ref`` is a keyed hash and never leaves the service layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.market import MarketKeywordMetric, MarketListingSnapshot
from juli_backend.models.platform_data import (
    PlatformItem,
    PlatformPeriodMetric,
    PlatformPromotion,
)
from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.models.shopee_profit import (
    AdCampaignPurpose,
    PlatformFeeFormula,
    PlatformItemSnapshot,
    ShopeeOrderIncome,
    ShopeeOrderLine,
)
from juli_backend.repositories._base import SessionRepo, ShopScopedRepo

PLATFORM_SHOPEE = "shopee"


class ShopeeOrderLinesRepo(ShopScopedRepo[ShopeeOrderLine]):
    _model = ShopeeOrderLine

    async def in_window(self, shop_id: uuid.UUID, start: date, end: date) -> list[ShopeeOrderLine]:
        """Lines whose order was placed on a day in ``[start, end]`` (platform calendar day)."""
        lo = datetime.combine(start, datetime.min.time())
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time())
        return await self._all(
            self._scoped(
                shop_id,
                ShopeeOrderLine.platform == PLATFORM_SHOPEE,
                ShopeeOrderLine.ordered_at >= lo,
                ShopeeOrderLine.ordered_at < hi,
            ).order_by(
                ShopeeOrderLine.ordered_at, ShopeeOrderLine.order_ref, ShopeeOrderLine.line_no
            )
        )

    async def day_bounds(self, shop_id: uuid.UUID) -> tuple[date, date] | None:
        stmt = self._scoped(shop_id, ShopeeOrderLine.platform == PLATFORM_SHOPEE).with_only_columns(
            func.min(ShopeeOrderLine.ordered_at), func.max(ShopeeOrderLine.ordered_at)
        )
        first, last = (await self._session.execute(stmt)).one()
        if first is None:
            return None
        return first.date(), last.date()

    async def kol_pair_lines(
        self, shop_id: uuid.UUID, kol_key: str, item_id: str, start: date, end: date
    ) -> list[ShopeeOrderLine]:
        """P91 D-9: the affiliate-marked lines of one KOL x product on days in ``[start, end]``."""
        lo = datetime.combine(start, datetime.min.time())
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time())
        return await self._all(
            self._scoped(
                shop_id,
                ShopeeOrderLine.platform == PLATFORM_SHOPEE,
                ShopeeOrderLine.kol_key == kol_key,
                ShopeeOrderLine.item_id == item_id,
                ShopeeOrderLine.ordered_at >= lo,
                ShopeeOrderLine.ordered_at < hi,
            ).order_by(ShopeeOrderLine.ordered_at, ShopeeOrderLine.order_ref)
        )

    async def days_with_lines(self, shop_id: uuid.UUID, start: date, end: date) -> set[date]:
        """Calendar days in the window that have at least one order line."""
        lo = datetime.combine(start, datetime.min.time())
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time())
        stmt = self._scoped(
            shop_id,
            ShopeeOrderLine.platform == PLATFORM_SHOPEE,
            ShopeeOrderLine.ordered_at >= lo,
            ShopeeOrderLine.ordered_at < hi,
        ).with_only_columns(func.date(ShopeeOrderLine.ordered_at).distinct())
        return {r[0] for r in (await self._session.execute(stmt)).all()}


class ShopeeOrderIncomeRepo(ShopScopedRepo[ShopeeOrderIncome]):
    """The income export's per-order actuals (migration 119), read by ``order_ref``."""

    _model = ShopeeOrderIncome
    CHUNK = 1000

    async def for_refs(self, shop_id: uuid.UUID, refs: Collection[str]) -> list[ShopeeOrderIncome]:
        """The income rows of the given orders (a ref with none is simply absent)."""
        ordered = sorted(set(refs))
        out: list[ShopeeOrderIncome] = []
        for start in range(0, len(ordered), self.CHUNK):
            part = ordered[start : start + self.CHUNK]
            out.extend(
                await self._all(
                    self._scoped(
                        shop_id,
                        ShopeeOrderIncome.platform == PLATFORM_SHOPEE,
                        ShopeeOrderIncome.order_ref.in_(part),
                    )
                )
            )
        return out

    async def count_in_window(self, shop_id: uuid.UUID, start: date, end: date) -> int:
        """Income rows whose order was placed on a day in ``[start, end]``."""
        stmt = self._scoped(
            shop_id,
            ShopeeOrderIncome.platform == PLATFORM_SHOPEE,
            ShopeeOrderIncome.ordered_on >= start,
            ShopeeOrderIncome.ordered_on <= end,
        ).with_only_columns(func.count())
        return int((await self._session.execute(stmt)).scalar_one())


class PlatformDailyMetricsRepo(ShopScopedRepo[PlatformDailyMetric]):
    _model = PlatformDailyMetric

    async def window(
        self,
        shop_id: uuid.UUID,
        *,
        datasets: Collection[str],
        start: date,
        end: date,
        streams: Collection[str] | None = None,
        order_types: Collection[str] | None = None,
        item_id: str | None = None,
        any_item: bool = False,
    ) -> list[PlatformDailyMetric]:
        """Day rows in ``[start, end]``. ``item_id`` None = shop level (``''``) unless
        ``any_item`` asks for shop and item rows alike."""
        stmt = self._scoped(
            shop_id,
            PlatformDailyMetric.platform == PLATFORM_SHOPEE,
            PlatformDailyMetric.dataset.in_(list(datasets)),
            PlatformDailyMetric.day >= start,
            PlatformDailyMetric.day <= end,
        )
        if streams is not None:
            stmt = stmt.where(PlatformDailyMetric.stream.in_(list(streams)))
        if order_types is not None:
            stmt = stmt.where(PlatformDailyMetric.order_type.in_(list(order_types)))
        if not any_item:
            stmt = stmt.where(PlatformDailyMetric.item_id == (item_id or ""))
        return await self._all(stmt)

    async def latest_day(self, shop_id: uuid.UUID, dataset: str) -> date | None:
        stmt = self._scoped(
            shop_id,
            PlatformDailyMetric.platform == PLATFORM_SHOPEE,
            PlatformDailyMetric.dataset == dataset,
        ).with_only_columns(func.max(PlatformDailyMetric.day))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def latest_days(self, shop_id: uuid.UUID) -> dict[str, date]:
        """The newest ``day`` of every dataset the shop has day rows for."""
        stmt = (
            self._scoped(shop_id, PlatformDailyMetric.platform == PLATFORM_SHOPEE)
            .with_only_columns(PlatformDailyMetric.dataset, func.max(PlatformDailyMetric.day))
            .group_by(PlatformDailyMetric.dataset)
        )
        return {d: day for d, day in (await self._session.execute(stmt)).all() if day is not None}


class PlatformPeriodMetricsRepo(ShopScopedRepo[PlatformPeriodMetric]):
    _model = PlatformPeriodMetric

    async def overlapping(
        self,
        shop_id: uuid.UUID,
        *,
        datasets: Collection[str],
        start: date,
        end: date,
        order_types: Collection[str] | None = None,
        item_id: str | None = None,
        any_item: bool = True,
    ) -> list[PlatformPeriodMetric]:
        """Period rows that overlap ``[start, end]`` at all (the caller picks which to use:
        periods overlap each other and are never added blindly)."""
        stmt = self._scoped(
            shop_id,
            PlatformPeriodMetric.platform == PLATFORM_SHOPEE,
            PlatformPeriodMetric.dataset.in_(list(datasets)),
            PlatformPeriodMetric.period_start <= end,
            PlatformPeriodMetric.period_end >= start,
        )
        if order_types is not None:
            stmt = stmt.where(PlatformPeriodMetric.order_type.in_(list(order_types)))
        if not any_item:
            stmt = stmt.where(PlatformPeriodMetric.item_id == (item_id or ""))
        return await self._all(stmt)

    async def latest_ends(self, shop_id: uuid.UUID) -> dict[str, date]:
        """The newest ``period_end`` of every dataset the shop has period rows for."""
        stmt = (
            self._scoped(shop_id, PlatformPeriodMetric.platform == PLATFORM_SHOPEE)
            .with_only_columns(
                PlatformPeriodMetric.dataset, func.max(PlatformPeriodMetric.period_end)
            )
            .group_by(PlatformPeriodMetric.dataset)
        )
        return {d: end for d, end in (await self._session.execute(stmt)).all() if end is not None}


class PlatformItemsRepo(ShopScopedRepo[PlatformItem]):
    _model = PlatformItem

    async def all_items(self, shop_id: uuid.UUID) -> list[PlatformItem]:
        return await self._all(self._scoped(shop_id, PlatformItem.platform == PLATFORM_SHOPEE))


class PlatformItemSnapshotsRepo(ShopScopedRepo[PlatformItemSnapshot]):
    _model = PlatformItemSnapshot

    async def latest_per_item(
        self, shop_id: uuid.UUID, item_ids: Collection[str] | None = None
    ) -> list[PlatformItemSnapshot]:
        """The newest snapshot of every (item, variation)."""
        newest = (
            self._scoped(shop_id, PlatformItemSnapshot.platform == PLATFORM_SHOPEE)
            .with_only_columns(
                PlatformItemSnapshot.item_id.label("item_id"),
                PlatformItemSnapshot.variation_id.label("variation_id"),
                func.max(PlatformItemSnapshot.captured_at).label("captured_at"),
            )
            .group_by(PlatformItemSnapshot.item_id, PlatformItemSnapshot.variation_id)
            .subquery()
        )
        stmt = self._scoped(shop_id, PlatformItemSnapshot.platform == PLATFORM_SHOPEE).join(
            newest,
            (PlatformItemSnapshot.item_id == newest.c.item_id)
            & (PlatformItemSnapshot.variation_id == newest.c.variation_id)
            & (PlatformItemSnapshot.captured_at == newest.c.captured_at),
        )
        if item_ids is not None:
            stmt = stmt.where(PlatformItemSnapshot.item_id.in_(list(item_ids)))
        return await self._all(stmt)

    async def history(
        self, shop_id: uuid.UUID, item_id: str, limit: int = 50
    ) -> list[PlatformItemSnapshot]:
        """The item's own snapshots (variation ``''``), newest first -- one per change."""
        stmt = (
            self._scoped(
                shop_id,
                PlatformItemSnapshot.platform == PLATFORM_SHOPEE,
                PlatformItemSnapshot.item_id == item_id,
                PlatformItemSnapshot.variation_id == "",
            )
            .order_by(PlatformItemSnapshot.captured_at.desc())
            .limit(limit)
        )
        return await self._all(stmt)

    async def latest_capture(self, shop_id: uuid.UUID) -> datetime | None:
        stmt = self._scoped(
            shop_id, PlatformItemSnapshot.platform == PLATFORM_SHOPEE
        ).with_only_columns(func.max(PlatformItemSnapshot.captured_at))
        return (await self._session.execute(stmt)).scalar_one_or_none()


class PlatformPromotionsRepo(ShopScopedRepo[PlatformPromotion]):
    _model = PlatformPromotion

    async def overlapping(
        self,
        shop_id: uuid.UUID,
        *,
        promo_types: Collection[str],
        start: date,
        end: date,
        order_types: Collection[str] | None = None,
    ) -> list[PlatformPromotion]:
        stmt = self._scoped(
            shop_id,
            PlatformPromotion.platform == PLATFORM_SHOPEE,
            PlatformPromotion.promo_type.in_(list(promo_types)),
            PlatformPromotion.period_start <= end,
            PlatformPromotion.period_end >= start,
        )
        if order_types is not None:
            stmt = stmt.where(PlatformPromotion.order_type.in_(list(order_types)))
        return await self._all(stmt)


class ShopRulesReadRepo(ShopScopedRepo[ShopRule]):
    """The CURRENT rule projection (``shop_rules``); history is ``shop_rule_versions``."""

    _model = ShopRule

    async def current(
        self, shop_id: uuid.UUID, rule_keys: Collection[str] | None = None
    ) -> list[ShopRule]:
        stmt = self._scoped(shop_id)
        if rule_keys is not None:
            stmt = stmt.where(ShopRule.rule_key.in_(list(rule_keys)))
        return await self._all(stmt)


class ShopKeywordSeedsReadRepo(ShopScopedRepo[ShopKeywordSeed]):
    _model = ShopKeywordSeed

    async def roled(self, shop_id: uuid.UUID) -> list[ShopKeywordSeed]:
        return await self._all(
            self._scoped(
                shop_id,
                ShopKeywordSeed.platform == PLATFORM_SHOPEE,
                ShopKeywordSeed.enabled.is_(True),
                ShopKeywordSeed.role.is_not(None),
            )
        )


class AdCampaignPurposesReadRepo(ShopScopedRepo[AdCampaignPurpose]):
    _model = AdCampaignPurpose

    async def latest(self, shop_id: uuid.UUID) -> list[AdCampaignPurpose]:
        """The newest purpose row of each campaign key."""
        rows = await self._all(
            self._scoped(shop_id, AdCampaignPurpose.platform == PLATFORM_SHOPEE).order_by(
                AdCampaignPurpose.campaign_key, AdCampaignPurpose.set_at.desc()
            )
        )
        seen: set[str] = set()
        out: list[AdCampaignPurpose] = []
        for row in rows:
            if row.campaign_key not in seen:
                seen.add(row.campaign_key)
                out.append(row)
        return out


class PlatformFeeFormulasReadRepo(SessionRepo):
    """Public reference table (no ``shop_id``): the platform's versioned fee policy."""

    async def for_platform(self, platform: str = PLATFORM_SHOPEE) -> Sequence[PlatformFeeFormula]:
        return await self._all(
            select(PlatformFeeFormula).where(PlatformFeeFormula.platform == platform)
        )


class MarketKeywordMetricsReadRepo(SessionRepo):
    """Public lane: the newest collected numbers for a set of keywords."""

    async def latest(self, keywords: Collection[str]) -> list[MarketKeywordMetric]:
        if not keywords:
            return []
        rows = await self._all(
            select(MarketKeywordMetric)
            .where(
                MarketKeywordMetric.keyword.in_(list(keywords)),
                MarketKeywordMetric.status == "ok",
            )
            .order_by(MarketKeywordMetric.keyword, MarketKeywordMetric.collected_on.desc())
        )
        seen: set[str] = set()
        out: list[MarketKeywordMetric] = []
        for row in rows:
            if row.keyword not in seen:
                seen.add(row.keyword)
                out.append(row)
        return out

    async def related(
        self, seeds: Collection[str], *, limit: int = 300
    ) -> list[MarketKeywordMetric]:
        """P92: the other keywords the lookups of these seeds listed (``keyword != seed``), the
        newest numbers of each, highest volume first."""
        if not seeds:
            return []
        rows = await self._all(
            select(MarketKeywordMetric)
            .where(
                MarketKeywordMetric.seed.in_(list(seeds)),
                MarketKeywordMetric.keyword != MarketKeywordMetric.seed,
                MarketKeywordMetric.status == "ok",
            )
            .order_by(MarketKeywordMetric.keyword, MarketKeywordMetric.collected_on.desc())
        )
        newest: dict[str, MarketKeywordMetric] = {}
        for row in rows:
            newest.setdefault(row.keyword, row)
        ordered = sorted(newest.values(), key=lambda r: (-(r.volume or 0), r.keyword))
        return ordered[:limit]


class MarketListingsReadRepo(SessionRepo):
    """Public lane: the search cards the owner collected (competitor titles)."""

    async def top_titles(
        self, keywords: Collection[str], *, per_keyword: int = 10
    ) -> dict[str, list[str]]:
        """Per keyword the titles of its newest collection, best position first."""
        if not keywords:
            return {}
        rows = await self._all(
            select(MarketListingSnapshot)
            .where(
                MarketListingSnapshot.keyword.in_(list(keywords)),
                MarketListingSnapshot.title.is_not(None),
            )
            .order_by(
                MarketListingSnapshot.keyword,
                MarketListingSnapshot.collected_at.desc(),
                MarketListingSnapshot.page,
                MarketListingSnapshot.pos,
            )
        )
        newest: dict[str, datetime] = {}
        out: dict[str, list[str]] = {}
        for row in rows:
            at = newest.setdefault(row.keyword, row.collected_at)
            if row.collected_at != at or len(out.setdefault(row.keyword, [])) >= per_keyword:
                continue
            if row.title:
                out[row.keyword].append(row.title)
        return out


__all__ = [
    "AdCampaignPurposesReadRepo",
    "MarketKeywordMetricsReadRepo",
    "MarketListingsReadRepo",
    "PlatformDailyMetricsRepo",
    "PlatformFeeFormulasReadRepo",
    "PlatformItemSnapshotsRepo",
    "PlatformItemsRepo",
    "PlatformPeriodMetricsRepo",
    "PlatformPromotionsRepo",
    "ShopKeywordSeedsReadRepo",
    "ShopRulesReadRepo",
    "ShopeeOrderIncomeRepo",
    "ShopeeOrderLinesRepo",
]
