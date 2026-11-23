"""F4.2: which days of the last 30 the Connector has not read yet, per daily dataset.

``GET /v1/connector/shopee/read-days`` hands this to the Connector so it re-reads only the holes
(yesterday first, then oldest first). A day counts as read when an accepted extension post
(``ingest_raw_payloads``, source ``extension``) covers it, an empty page included. File imports
do not count: the Connector is asked for the days it has not read itself.
``traffic_overview`` is checked against the stored rows: it counts only when
the day has level-2 source rows (Trang shop, Tìm kiếm ...),
so days stored before F4.1 with totals only show as missing. ``flash_sale`` (F6.4) is judged by
its stored ``promotion_daily`` row of segment ``flash_sale``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import (
    SEGMENT_ALL,
    SOURCE_EXTENSION,
    IngestRawPayload,
    PlatformDailyMetric,
)
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.ingest.writers import UNRESOLVED_PREFIX

#: The order line the list page gave with no item and no SKU (``writers._line_item``).
UNKNOWN_ITEM = f"{UNRESOLVED_PREFIX}unknown"

WINDOW_DAYS = 30
PLATFORM_UTC_OFFSET = timedelta(hours=7)

#: The datasets the Connector posts once per day (or per day-sized period).
DAILY_DATASETS: tuple[str, ...] = (
    "traffic_overview",
    "shop_overview",
    "shop_traffic",
    "item_performance",
    "item_by_source",
    "item_traffic_sources",
    "product_period",
    "product_overview",
    "ads_campaign_daily",
    "ads_campaign_period",
    "affiliate_shop_period",
    "affiliate_commission_period",
    "affiliate_partner_period",
    "affiliate_product_period",
    "affiliate_content_period",
    "promotion_daily",
    "flash_sale",
    "order_lines",
    "order_income",
)
#: Datasets judged by their stored rows instead of by the posts.
_BY_ROWS = frozenset({"traffic_overview", "flash_sale"})
#: F6.4 (Connector 0.3.30): ``flash_sale`` is the Connector's name for the Flash Sale day read; it
#: posts as ``promotion_daily`` (segment ``flash_sale``), so a day counts as read by that stored row
#: (an empty day is a zero row), not by the promotion posts, which Shopee's other types also make.
_FLASH_SEGMENT = "flash_sale"


def vietnam_today(now: datetime | None = None) -> date:
    moment = now or datetime.now(UTC)
    return (moment.astimezone(UTC) + PLATFORM_UTC_OFFSET).date()


def window_days(today: date) -> list[date]:
    """The last ``WINDOW_DAYS`` days before ``today``, oldest first."""
    return [today - timedelta(days=n) for n in range(WINDOW_DAYS, 0, -1)]


def missing_by_dataset(
    covered: dict[str, set[date]], today: date, datasets: tuple[str, ...] = DAILY_DATASETS
) -> dict[str, dict[str, list[str]]]:
    """Per dataset the days of the window not in ``covered[dataset]``; a dataset with no gap is
    left out. Oldest first (the Connector reads yesterday first by itself)."""
    days = window_days(today)
    out: dict[str, dict[str, list[str]]] = {}
    for dataset in datasets:
        have = covered.get(dataset, set())
        holes = [d.isoformat() for d in days if d not in have]
        if holes:
            out[dataset] = {"missing": holes}
    return out


def _span(start: date, end: date, first: date, last: date) -> set[date]:
    lo, hi = max(start, first), min(end, last)
    return {lo + timedelta(days=n) for n in range((hi - lo).days + 1)} if lo <= hi else set()


async def covered_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    platform: str,
    today: date,
    *,
    extension_only: bool = True,
) -> dict[str, set[date]]:
    """Per daily dataset the window days read. ``extension_only=False`` (C2, "held"): a day any
    source brought counts (a file import included)."""
    first, last = today - timedelta(days=WINDOW_DAYS), today - timedelta(days=1)
    covered: dict[str, set[date]] = {}
    by_source = (IngestRawPayload.source == SOURCE_EXTENSION,) if extension_only else ()
    rows_by_source = (PlatformDailyMetric.source == SOURCE_EXTENSION,) if extension_only else ()
    posts = await session.execute(
        select(
            IngestRawPayload.dataset, IngestRawPayload.period_start, IngestRawPayload.period_end
        ).where(
            IngestRawPayload.shop_id == shop_id,
            IngestRawPayload.platform == platform,
            *by_source,
            IngestRawPayload.dataset.in_(DAILY_DATASETS),
            IngestRawPayload.period_end >= first,
            IngestRawPayload.period_start <= last,
        )
    )
    for dataset, start, end in posts:
        covered.setdefault(dataset, set()).update(_span(start, end, first, last))
    for dataset in _BY_ROWS:
        covered[dataset] = set()
    rows = await session.execute(
        select(PlatformDailyMetric.day)
        .where(
            PlatformDailyMetric.shop_id == shop_id,
            PlatformDailyMetric.platform == platform,
            PlatformDailyMetric.dataset == "traffic_overview",
            *rows_by_source,
            PlatformDailyMetric.segment != SEGMENT_ALL,
            PlatformDailyMetric.day >= first,
            PlatformDailyMetric.day <= last,
        )
        .distinct()
    )
    covered["traffic_overview"] = {d for (d,) in rows}
    flash = await session.execute(
        select(PlatformDailyMetric.day)
        .where(
            PlatformDailyMetric.shop_id == shop_id,
            PlatformDailyMetric.platform == platform,
            PlatformDailyMetric.dataset == "promotion_daily",
            *rows_by_source,
            PlatformDailyMetric.segment == _FLASH_SEGMENT,
            PlatformDailyMetric.day >= first,
            PlatformDailyMetric.day <= last,
        )
        .distinct()
    )
    covered["flash_sale"] = {d for (d,) in flash}
    if extension_only:
        # C1: a day the Connector read only from the order list, with lines that name no item
        # (``sku:unknown``), is read again (the order reader then opens each order's detail).
        unknown = await session.execute(
            select(ShopeeOrderLine.day)
            .where(
                ShopeeOrderLine.shop_id == shop_id,
                ShopeeOrderLine.platform == platform,
                ShopeeOrderLine.source == SOURCE_EXTENSION,
                ShopeeOrderLine.item_id == UNKNOWN_ITEM,
                ShopeeOrderLine.day >= first,
                ShopeeOrderLine.day <= last,
            )
            .distinct()
        )
        covered.setdefault("order_lines", set()).difference_update(d for (d,) in unknown)
    return covered


async def read_days(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, now: datetime | None = None
) -> dict[str, object]:
    today = vietnam_today(now)
    covered = await covered_days(session, shop_id, platform, today)
    return {
        "as_of": today.isoformat(),
        "window_days": WINDOW_DAYS,
        "datasets": missing_by_dataset(covered, today),
    }


def progress_of(
    held: dict[str, set[date]], read: dict[str, set[date]], today: date
) -> dict[str, dict[str, str | None]]:
    """C2, per daily dataset: ``held_through`` -- the newest window day Juli holds (any source);
    ``reading_through`` -- while the Connector still has a hole in the window, the day before
    its oldest hole (it reads holes oldest first, so its catch-up has reached that day), else
    ``None``. Ops shows "Đang đọc đến dd/mm" from it."""
    days = window_days(today)
    out: dict[str, dict[str, str | None]] = {}
    for dataset in DAILY_DATASETS:
        have = held.get(dataset, set())
        newest = max(have) if have else None
        holes = [d for d in days if d not in read.get(dataset, set())]
        out[dataset] = {
            "held_through": newest.isoformat() if newest else None,
            "reading_through": (holes[0] - timedelta(days=1)).isoformat() if holes else None,
        }
    return out


async def progress(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, now: datetime | None = None
) -> dict[str, dict[str, str | None]]:
    today = vietnam_today(now)
    held = await covered_days(session, shop_id, platform, today, extension_only=False)
    read = await covered_days(session, shop_id, platform, today)
    return progress_of(held, read, today)


def blocked_by_dataset(
    reader_blocks: list[dict[str, object]] | None, reader_datasets: dict[str, tuple[str, ...]]
) -> dict[str, str]:
    """C2 / 1(a): the shop's current reader blocks (``shopee_connector_state.reader_blocks``,
    ``[{reason, readers, section}]``) per dataset: the reason a page of that dataset is stopped
    (``login``, ``password_recheck`` ...). The first block naming a reader wins."""
    out: dict[str, str] = {}
    for block in reader_blocks or []:
        reason = block.get("reason")
        readers = block.get("readers")
        if not isinstance(reason, str) or not isinstance(readers, list):
            continue
        for reader in readers:
            for dataset in reader_datasets.get(str(reader), ()):
                out.setdefault(dataset, reason)
    return out
