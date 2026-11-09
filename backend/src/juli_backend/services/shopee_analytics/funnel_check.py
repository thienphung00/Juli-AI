"""The daily funnel check (P98 / ADR-122 d.11.3): after a metrics rebuild, compare the stored
source funnel with Shopee's raw numbers and log every gap. Never corrects anything.

For one shop and day (``shopee_source_metrics_daily`` against):

- ``missing_rows`` -- the day has a ShopMetrics row but no source rows;
- ``sources_sum`` -- the six sources of the shop (or of a product) do not add up to its
  ShopMetrics row (đơn exactly; GMV within 1đ): the identity d.3 promises is broken;
- ``shop_totals`` -- the ShopMetrics row is more than 1 % away from Shopee's own daily shop
  totals (``shop_overview``) for the day;
- ``traffic`` -- a source's stored lượt xem / lượt nhấp are more than 1 % away from the traffic
  tables (``traffic_overview``, Thẻ sản phẩm minus Trang shop as :mod:`shopee_profit.flows`).

Each finding is logged as ``shopee_funnel_mismatch`` (shop id, day, kind, metric, source, item id
and the two numbers -- aggregates only, no buyer data) and returned for Ops ("lệch số liệu").
:func:`check_days` is what the ingest hook and the backfill call: it never raises.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_metrics import (
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.compute import shop_flow_rows
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.flows import FLOW_ORDER, build_flow_tables
from juli_backend.services.shopee_profit.money import ZERO

logger = logging.getLogger(__name__)

#: a gap above this share of the expected value is a mismatch (ADR-122 d.11.3: 1 %)
TOLERANCE = Decimal("0.01")
#: GMV identity slack: the stored rows are rounded to the cent
GMV_SLACK = Decimal("1")
EVENT = "shopee_funnel_mismatch"


@dataclass(frozen=True)
class Mismatch:
    shop_id: uuid.UUID
    day: date
    kind: str  # missing_rows | sources_sum | shop_totals | traffic
    metric: str  # orders | gmv | views | clicks | rows
    stored: Decimal | None
    expected: Decimal | None
    source: str | None = None
    item_id: str | None = None

    @property
    def gap_pct(self) -> Decimal | None:
        """|stored - expected| as a percent of expected (None when expected is 0 / unknown)."""
        if self.stored is None or self.expected is None or self.expected == 0:
            return None
        return abs(self.stored - self.expected) / abs(self.expected) * 100

    def log_extra(self) -> dict[str, str | None]:
        gap = self.gap_pct
        return {
            "shop_id": str(self.shop_id),
            "day": self.day.isoformat(),
            "kind": self.kind,
            "metric": self.metric,
            "source": self.source,
            "item_id": self.item_id,
            "stored": None if self.stored is None else str(self.stored),
            "expected": None if self.expected is None else str(self.expected),
            "gap_pct": None if gap is None else f"{gap:.2f}",
        }


def _off(stored: Decimal | None, expected: Decimal | None) -> bool:
    """More than 1 % apart (one known and the other not counts as apart)."""
    if stored is None and expected is None:
        return False
    if stored is None or expected is None:
        return True
    if expected == 0:
        return stored != 0
    return abs(stored - expected) > abs(expected) * TOLERANCE


def _dec(value: int | Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _sums(
    shop_id: uuid.UUID,
    day: date,
    rows: list[ShopeeSourceMetricsDaily],
    orders: int | None,
    gmv: Decimal | None,
    item_id: str | None,
) -> list[Mismatch]:
    out: list[Mismatch] = []
    got_orders = Decimal(sum(r.orders for r in rows))
    got_gmv = sum((r.gmv for r in rows), ZERO)
    want_orders, want_gmv = Decimal(orders or 0), gmv if gmv is not None else ZERO
    if got_orders != want_orders:
        out.append(
            Mismatch(shop_id, day, "sources_sum", "orders", got_orders, want_orders, None, item_id)
        )
    if abs(got_gmv - want_gmv) > GMV_SLACK:
        out.append(Mismatch(shop_id, day, "sources_sum", "gmv", got_gmv, want_gmv, None, item_id))
    return out


async def _shop_row(
    session: AsyncSession, shop_id: uuid.UUID, day: date
) -> ShopeeShopMetricsDaily | None:
    t = ShopeeShopMetricsDaily
    return (
        await session.execute(
            select(t).where(t.shop_id == shop_id, t.day == day, t.order_type == ORDER_TYPE)
        )
    ).scalar_one_or_none()


async def _traffic_checks(
    session: AsyncSession,
    shop_id: uuid.UUID,
    day: date,
    stored: dict[str, ShopeeSourceMetricsDaily],
) -> list[Mismatch]:
    traffic = await loaders.load_shop_traffic(session, shop_id, Window(day, day))
    if traffic.basis == "none":
        return []
    table = build_flow_tables(shop_flow_rows(traffic), shop_gmv=ZERO).shop
    out: list[Mismatch] = []
    for f in FLOW_ORDER:
        raw = table.row(f.value)
        row = stored.get(f.value)
        for metric in ("views", "clicks"):
            want = _dec(getattr(raw, metric)) if raw else None
            got = _dec(getattr(row, metric)) if row else None
            if _off(got, want):
                out.append(Mismatch(shop_id, day, "traffic", metric, got, want, f.value))
    return out


async def check_day(session: AsyncSession, shop_id: uuid.UUID, day: date) -> list[Mismatch]:
    """Every gap of one built day (see the module docstring), each logged once. Read only."""
    shop = await _shop_row(session, shop_id, day)
    if shop is None:
        return []  # not built: nothing to check
    t = ShopeeSourceMetricsDaily
    rows = list(
        (await session.execute(select(t).where(t.shop_id == shop_id, t.day == day))).scalars()
    )
    out: list[Mismatch] = []
    shop_rows = [r for r in rows if r.item_id is None]
    if not shop_rows:
        out.append(Mismatch(shop_id, day, "missing_rows", "rows", Decimal(0), None))
    else:
        out += _sums(shop_id, day, shop_rows, shop.orders, shop.gmv, None)
        by_item: dict[str, list[ShopeeSourceMetricsDaily]] = defaultdict(list)
        for r in rows:
            if r.item_id is not None:
                by_item[r.item_id].append(r)
        if by_item:
            p = ShopeeProductMetricsDaily
            products = {
                x.item_id: x
                for x in (
                    await session.execute(
                        select(p).where(
                            p.shop_id == shop_id,
                            p.day == day,
                            p.order_type == ORDER_TYPE,
                            p.item_id.in_(sorted(by_item)),
                        )
                    )
                ).scalars()
            }
            for item_id, item_rows in sorted(by_item.items()):
                prod = products.get(item_id)
                out += _sums(
                    shop_id,
                    day,
                    item_rows,
                    prod.orders if prod else 0,
                    prod.gmv if prod else ZERO,
                    item_id,
                )
        out += await _traffic_checks(session, shop_id, day, {r.source: r for r in shop_rows})
    totals = await loaders.load_shop_totals(session, shop_id, Window(day, day))
    if totals.complete:
        for metric, got, want in (
            ("gmv", _dec(shop.gmv), _dec(totals.gmv)),
            ("orders", _dec(shop.orders), _dec(totals.orders)),
        ):
            if _off(got, want):
                out.append(Mismatch(shop_id, day, "shop_totals", metric, got, want))
    for m in out:
        logger.warning(EVENT, extra=m.log_extra())
    return out


async def check_days(
    session: AsyncSession, shop_id: uuid.UUID, days: Iterable[date]
) -> list[Mismatch]:
    """:func:`check_day` over ``days``; a failing check is logged and skipped, never raised (the
    ingest and the backfill must not fail because the check did)."""
    out: list[Mismatch] = []
    for day in sorted(set(days)):
        try:
            async with session.begin_nested():
                out += await check_day(session, shop_id, day)
        except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
            logger.warning(
                "shopee_funnel_check_failed",
                extra={"shop_id": str(shop_id), "day": day.isoformat()},
                exc_info=True,
            )
    return out


__all__ = ["EVENT", "Mismatch", "check_day", "check_days"]
