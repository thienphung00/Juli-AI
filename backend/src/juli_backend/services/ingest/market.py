"""``market_search`` (P92 B-10): page 1 of a PUBLIC Shopee search, read weekly by the Connector.

The rows land in the shared public market lane -- ``market_listing_snapshots`` (one row per card)
and ``market_keyword_snapshots`` (one row per keyword x sort x day) -- which have no ``shop_id``
and are Ops-only (``juli_ops``; the token's ``juli_app`` role has no grant). The write therefore
runs in a short ``ops_role`` block around those two statements only; the tenant scope around it
is untouched.

Safeguards, because a shop token writes a shared table:

- the keyword of every row must be one of THAT shop's own keyword seeds (``shop_keyword_seeds``,
  enabled, with a role other than ``loai_tru``): a token cannot plant arbitrary keywords;
- server switch ``CONNECTOR_MARKET_SEARCH`` (default off) and an optional shop allowlist
  ``CONNECTOR_MARKET_SHOP_IDS`` (comma-separated Juli shop ids; empty = any shop once the switch
  is on). The pilot is ORY only;
- no buyer field exists in the row model; the raw copy is cut to the row model's fields.

Source ranking is the other datasets': ``collector`` holds the post's ``source`` and a row of the
same card key is only replaced by the same or a higher rank (vendor < extension < file < api).
"""

from __future__ import annotations

import os
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_RANK
from juli_backend.models.market import MarketKeywordSnapshot, MarketListingSnapshot
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.market_stats import median, percentile
from juli_backend.services.ops.access import ops_role

ENV_FLAG = "CONNECTOR_MARKET_SEARCH"
ENV_SHOPS = "CONNECTOR_MARKET_SHOP_IDS"
PLATFORM = "shopee"
MAX_KEYWORDS_PER_PRODUCT = 3
#: A keyword with a capture newer than this is not due again (weekly cadence).
DUE_AFTER_DAYS = 6
#: Role of a seed that is dropped (``loai_tru``): never searched.
EXCLUDED_ROLE = "loai_tru"


def enabled(shop_id: uuid.UUID | str | None = None) -> bool:
    if os.environ.get(ENV_FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    allowed = {s.strip() for s in os.environ.get(ENV_SHOPS, "").split(",") if s.strip()}
    return not allowed or (shop_id is not None and str(shop_id) in allowed)


def fold(text: str) -> str:
    return " ".join(text.casefold().split())


async def shop_keywords(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, list[str]]:
    """``{item_id: [keyword, ...]}``: each product's 1-3 main keywords (core role first, then the
    other kept roles), from the shop's enabled seeds. Tenant scope must be set by the caller."""
    rows = (
        await session.scalars(
            select(ShopKeywordSeed).where(
                ShopKeywordSeed.shop_id == shop_id,
                ShopKeywordSeed.platform == PLATFORM,
                ShopKeywordSeed.enabled.is_(True),
                ShopKeywordSeed.role.is_not(None),
                ShopKeywordSeed.role != EXCLUDED_ROLE,
            )
        )
    ).all()
    per_item: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for seed in rows:
        items = [seed.item_scope] if seed.item_scope else list(seed.item_ids or [])
        rank = 0 if seed.role == "chinh" else 1
        for item in items:
            per_item[str(item)].append((rank, seed.keyword))
    out: dict[str, list[str]] = {}
    for item, entries in sorted(per_item.items()):
        seen: set[str] = set()
        picked: list[str] = []
        for _, keyword in sorted(entries):
            if fold(keyword) in seen:
                continue
            seen.add(fold(keyword))
            picked.append(keyword)
            if len(picked) == MAX_KEYWORDS_PER_PRODUCT:
                break
        out[item] = picked
    return out


async def allowed_keywords(session: AsyncSession, shop_id: uuid.UUID) -> set[str]:
    """Every keyword the shop's seeds allow (folded), kept roles only."""
    rows = (
        await session.scalars(
            select(ShopKeywordSeed.keyword).where(
                ShopKeywordSeed.shop_id == shop_id,
                ShopKeywordSeed.platform == PLATFORM,
                ShopKeywordSeed.enabled.is_(True),
                ShopKeywordSeed.role.is_not(None),
                ShopKeywordSeed.role != EXCLUDED_ROLE,
            )
        )
    ).all()
    return {fold(k) for k in rows}


async def last_collected(session: AsyncSession, keywords: list[str]) -> dict[str, date]:
    """The newest collection day of each keyword in the public lane (``{}`` if unreadable)."""
    if not keywords:
        return {}
    try:
        async with session.begin_nested(), ops_role(session):
            rows = (
                await session.execute(
                    select(MarketKeywordSnapshot.keyword, MarketKeywordSnapshot.collected_on).where(
                        MarketKeywordSnapshot.platform == PLATFORM,
                        MarketKeywordSnapshot.keyword.in_(keywords),
                    )
                )
            ).all()
    except Exception:
        return {}
    out: dict[str, date] = {}
    for keyword, day in rows:
        if keyword not in out or day > out[keyword]:
            out[keyword] = day
    return out


def due(keywords: list[str], last: dict[str, date], today: date) -> list[str]:
    cutoff = today - timedelta(days=DUE_AFTER_DAYS)
    return [k for k in keywords if k not in last or last[k] <= cutoff]


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def _discounted(row: Any) -> bool:
    if row.discount_pct is not None and row.discount_pct > 0:
        return True
    return row.price_before_discount is not None and row.price_before_discount > row.price


def card_values(row: Any, *, collected_at: datetime, source: str, source_version: str) -> dict:
    extra: dict[str, Any] = {
        "is_ad": bool(row.is_ad),
        "source_version": source_version,
        "source_rank": SOURCE_RANK[source],
    }
    for key in ("price_min", "price_max", "price_before_discount"):
        if getattr(row, key) is not None:
            extra[key] = float(getattr(row, key))
    if row.shop_title:
        extra["shop_title"] = row.shop_title
    if row.image_id:
        extra["image_id"] = row.image_id
    return {
        "id": uuid.uuid4(),
        "platform": PLATFORM,
        "keyword": row.keyword,
        "category": None,
        "sort": row.sort,
        "page": row.page,
        "pos": row.pos,
        "collected_at": collected_at,
        "platform_item_id": row.item_id,
        "platform_shop_id": row.shop_id,
        "title": row.title,
        "price": row.price,
        "discount_pct": row.discount_pct,
        "rating": row.rating,
        "sold_text": row.sold_text,
        "sold_monthly": row.sold_monthly,
        "sold_lifetime": row.sold_lifetime,
        "collector": source,
        "extra": extra,
    }


def keyword_summaries(rows: list[Any], collected_on: date) -> list[dict[str, Any]]:
    """One ``market_keyword_snapshots`` value set per keyword x sort; ads cards are left out of
    every statistic (they are placements, not the market's price)."""
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in rows:
        if not row.is_ad:
            groups[(row.keyword, row.sort)].append(row)
    out: list[dict[str, Any]] = []
    for (keyword, sort), cards in sorted(groups.items()):
        prices = [float(c.price) for c in cards]
        sold = [float(c.sold_monthly) for c in cards if c.sold_monthly is not None]
        shops = {c.shop_id for c in cards if c.shop_id}
        med, p75 = median(sold), percentile(sold, 0.75)
        out.append(
            {
                "id": uuid.uuid4(),
                "platform": PLATFORM,
                "keyword": keyword,
                "category": None,
                "sort": sort,
                "collected_on": collected_on,
                "pages": max(c.page for c in cards),
                "n_cards": len(cards),
                "n_shops": len(shops),
                "median_price_page1": Decimal(str(round(median(prices) or 0, 4))),
                "share_discounted": Decimal(
                    str(round(sum(1 for c in cards if _discounted(c)) / len(cards), 4))
                ),
                "sold_monthly_median": None if med is None else Decimal(str(round(med, 4))),
                "sold_monthly_p75": None if p75 is None else Decimal(str(round(p75, 4))),
                "extra": {"unit": "vnd"},
            }
        )
    return out


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


async def write_market_search(
    session: AsyncSession, rows: list[Any], body: Any, provenance: dict[str, Any]
) -> None:
    """Upsert the cards and the keyword summaries (inside ``ops_role``; nothing commits)."""
    if not rows:
        return
    source = str(provenance["source"])
    collected_at = _naive(provenance["captured_at"])
    values = [
        card_values(
            r,
            collected_at=collected_at,
            source=source,
            source_version=str(provenance["source_version"]),
        )
        for r in rows
    ]
    summaries = keyword_summaries(rows, body.period.end)
    insert = _insert(session)
    key = ["platform", "keyword", "sort", "page", "pos", "collected_at"]
    rank = case(
        *[(MarketListingSnapshot.collector == s, r) for s, r in SOURCE_RANK.items()], else_=0
    )
    async with ops_role(session):
        for start in range(0, len(values), 200):
            stmt = insert(MarketListingSnapshot).values(values[start : start + 200])
            stmt = stmt.on_conflict_do_update(
                index_elements=key,
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "platform_item_id",
                        "platform_shop_id",
                        "title",
                        "price",
                        "discount_pct",
                        "rating",
                        "sold_text",
                        "sold_monthly",
                        "sold_lifetime",
                        "collector",
                        "extra",
                    )
                },
                where=rank <= SOURCE_RANK[source],
            )
            await session.execute(stmt)
        for summary in summaries:
            stmt = insert(MarketKeywordSnapshot).values(summary)
            stmt = stmt.on_conflict_do_update(
                index_elements=["platform", "keyword", "sort", "collected_on"],
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "pages",
                        "n_cards",
                        "n_shops",
                        "median_price_page1",
                        "share_discounted",
                        "sold_monthly_median",
                        "sold_monthly_p75",
                        "extra",
                    )
                },
            )
            await session.execute(stmt)


__all__ = [
    "ENV_FLAG",
    "allowed_keywords",
    "due",
    "enabled",
    "keyword_summaries",
    "last_collected",
    "shop_keywords",
    "write_market_search",
]
