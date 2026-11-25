"""Tổng quan's numbers from the stored facts (Q2), in the shapes the screens already read.

Each builder reads through :func:`juli_backend.services.metrics.query.query` -- one range read,
the registry evaluates -- and returns the same keys as the per-request ``PeriodView`` path
(``channel_split.kpis_of`` / ``profit_split``), so the API response and the frontend do not
change. ``source`` replaces the database in tests.

- KPI row (Ròng, L1): GMV, đơn, Lợi nhuận ròng, the cost lines, Tổng chi phí, ROI and the three
  margins of the shop or of one product.
- Channel table (Ròng): Organic / Quảng cáo / TTLK from the channel cells (``shop_channel`` /
  ``product_channel``); the shop's ads no product owns and its other marketing are the
  ``unattributed`` row, never dropped.
- Product channel GMV (A8): a product whose report rows are zeros shows 0, "—" (``None``) only
  when it has no row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.metrics.query import QueryResult, RowSource, Scope, query
from juli_backend.services.shopee_analytics.fmt import num
from juli_backend.services.shopee_profit.ladder import LADDER_METRICS, Ladder

ZERO = Decimal(0)
#: what the KPI row reads (registry ids)
KPI_METRICS: tuple[str, ...] = ("gmv", "orders", "cost_total", "roi", *LADDER_METRICS)
#: the channel table's columns (``channel_split.SPLIT_COLUMNS``) -> registry ids
SPLIT_METRICS: Mapping[str, str] = {
    "gmv": "gmv",
    "orders": "orders",
    "net_revenue": "net_revenue_known",
    "cost_offers": "cost_offers",
    "contribution": "contribution",
    "cost_ads": "cost_ads",
    "cost_affiliate": "cost_affiliate",
    "profit": "profit",
}
CHANNELS = ("organic", "ads", "affiliate")
UNATTRIBUTED = "unattributed"


def _scope(product_id: str | None) -> Scope:
    return Scope.shop() if product_id is None else Scope.product(product_id)


def _ladder(res: QueryResult) -> Ladder | None:
    if all(res.values.get(m) is None for m in LADDER_METRICS):
        return None
    values = {m: res.values.get(m) for m in (*LADDER_METRICS, "cost_total")}
    # the ladder's margins are fractions (``channel_split.kpis_of`` multiplies by 100)
    for m in ("margin_gross", "margin_contribution", "margin"):
        v = values.get(m)
        values[m] = None if v is None else v / 100
    return Ladder(dict(res.components), values)


def _kpis(res: QueryResult) -> dict[str, Any]:
    from juli_backend.services.shopee_analytics.channel_split import kpis_of

    v = res.values
    return kpis_of(
        v.get("gmv"),
        v.get("orders"),
        v.get("profit"),
        v.get("cost_ads"),
        v.get("cost_affiliate"),
        v.get("cost_offers"),
        _ladder(res),
    )


async def kpis(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    window: tuple[date, date],
    *,
    product_id: str | None = None,
    source: RowSource | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Tổng quan's KPI row and the previous window's (``None`` when a day of it is missing)."""
    res = await query(
        session,
        shop_id,
        KPI_METRICS,
        scope=_scope(product_id),
        window=window,
        compare=True,
        source=source,
    )
    prev = res.previous
    prev_kpis = None if prev is None or prev.missing_days else _kpis(prev)
    return _kpis(res), prev_kpis


def _row(values: Mapping[str, Any]) -> dict[str, Decimal]:
    return {col: values.get(mid) or ZERO for col, mid in SPLIT_METRICS.items()}


async def profit_split(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    window: tuple[date, date],
    *,
    product_id: str | None = None,
    source: RowSource | None = None,
) -> dict[str, Any]:
    """The channel table (``channel_split.profit_split`` shape) from the stored channel cells."""
    metrics = tuple(dict.fromkeys(SPLIT_METRICS.values()))
    cells = await query(
        session,
        shop_id,
        metrics,
        scope=_scope(product_id),
        window=window,
        group_by="channel",
        source=source,
    )
    by = {r["channel"]: r for r in cells.rows}
    rows = {ch: _row(by.get(ch, {})) for ch in CHANNELS}
    unattributed = dict.fromkeys(SPLIT_METRICS, ZERO)
    if product_id is None:
        shop = await query(
            session,
            shop_id,
            ("cost_ads", "cost_other"),
            scope=Scope.shop(),
            window=window,
            source=source,
        )
        claimed = sum((r["cost_ads"] for r in rows.values()), ZERO)
        ads_rest = (shop.values.get("cost_ads") or ZERO) - claimed
        other = shop.values.get("cost_other") or ZERO
        unattributed.update(cost_ads=ads_rest, profit=-ads_rest - other)
        unattributed["other_marketing"] = other
    total = {
        col: sum((r.get(col, ZERO) for r in (*rows.values(), unattributed)), ZERO)
        for col in SPLIT_METRICS
    }

    def js(row: Mapping[str, Decimal]) -> dict[str, Any]:
        return {k: num(v) for k, v in row.items()}

    return {
        "level": "shop" if product_id is None else "product",
        "columns": list(SPLIT_METRICS),
        "rows": {ch: js(r) for ch, r in rows.items()},
        UNATTRIBUTED: None if product_id is not None else js(unattributed),
        "total": js(total),
    }


async def product_channel_gmv(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    window: tuple[date, date],
    item_ids: Iterable[str],
    *,
    source: RowSource | None = None,
) -> dict[str, dict[str, Decimal | None]]:
    """A8: item -> GMV and its Organic / Quảng cáo / TTLK parts. A product with rows of zeros is 0;
    a product with no row is ``None`` ("—"); a channel with no cell is 0 when the product has a
    row (its GMV is fully told by the other channels)."""
    items = list(dict.fromkeys(str(i) for i in item_ids))
    out: dict[str, dict[str, Decimal | None]] = {}
    if not items:
        return out
    totals = await query(
        session,
        shop_id,
        ("gmv",),
        scope=Scope.products(items),
        window=window,
        group_by="item",
        allow_partial=True,
        source=source,
    )
    known = {r["item"]: r["gmv"] for r in totals.rows if r["_rows"]}
    for item in items:
        gmv = known.get(item)
        cells: dict[str, Decimal | None] = dict.fromkeys(
            (f"{ch}_gmv" for ch in CHANNELS), None if gmv is None else ZERO
        )
        if gmv is not None:
            split = await query(
                session,
                shop_id,
                ("gmv",),
                scope=Scope.product(item),
                window=window,
                group_by="channel",
                allow_partial=True,
                source=source,
            )
            for r in split.rows:
                cells[f"{r['channel']}_gmv"] = r["gmv"] if r["gmv"] is not None else ZERO
        out[item] = {"gmv": gmv, **cells}
    return out


__all__ = ["KPI_METRICS", "SPLIT_METRICS", "kpis", "product_channel_gmv", "profit_split"]
