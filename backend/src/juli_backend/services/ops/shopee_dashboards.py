"""Juli Ops Shopee dashboards: measured data only, read-only (ADR-117 step 4, G3 / G5).

Two dashboards over the tenant tables the ingest gateway fills
(``platform_daily_metrics``, ``platform_period_metrics``, ``platform_items``,
``platform_product_flags``, ``platform_promotions``):

- **Sản phẩm + luồng**: ``products`` (per-product funnel for one export period, flags,
  12-month history) and ``flows`` (GMV by traffic flow).
- **Quảng cáo + khuyến mãi**: ``ads`` (cost / orders / ROAS by ad type, monthly and
  daily, plus the low-ROAS alert) and ``promotions`` (programme timeline).

Rules this module keeps:

- A level-2 breakdown row (``segment != 'all'``, e.g. "Trang shop" under "Thẻ sản phẩm")
  is a child of its level-1 flow and is never added to a total (G3). Ads are an overlay:
  their own block, never in the flow total.
- Period rows overlap (a 28-day window next to calendar months), so a period is never
  summed with another: the funnel reads one exact period, the 12-month history reads
  calendar-month periods only.
- Every query is aggregated in SQL; no raw payload leaves the database. Callers run
  inside ``with_shop_scope`` so RLS applies on top of the explicit ``shop_id`` filter.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics.queries import product_price_margin

PLATFORM = "shopee"
ORDER_TYPES = ("placed", "paid", "confirmed")
DEFAULT_ORDER_TYPE = "confirmed"
#: Shopee's Ads section counts placed orders (mapper docstring), so ads default to them.
DEFAULT_ADS_ORDER_TYPE = "placed"

MAX_RANGE_DAYS = 400
DEFAULT_RANGE_DAYS = 30
HISTORY_MONTHS = 12
MAX_PRODUCTS = 200

#: ROAS alert (brief G5): an ad type whose daily ROAS stays under the floor for this many
#: consecutive days, ending on its latest day with spend.
ROAS_FLOOR = Decimal("1.5")
ROAS_ALERT_MIN_DAYS = 5

FLOW_STREAMS = ("product_card", "seller_video", "seller_live", "affiliate")
STREAM_LABELS = {
    "product_card": "Thẻ sản phẩm",
    "seller_video": "Video",
    "seller_live": "Live",
    "affiliate": "Tiếp thị liên kết",
    "ads": "Dịch vụ Hiển thị",
}
SEGMENT_LABELS = {
    "search": "Tìm kiếm",
    "recommend": "Đề xuất",
    "shop_page": "Trang shop",
    "cart": "Giỏ hàng",
    "my_orders": "Đơn mua của tôi",
    "other": "Khác",
    "promo": "Khuyến mãi",
    "chat": "Chat",
    "live_tab": "Thẻ Live",
    "live_home": "Trang chủ Shopee Live",
    "video": "Video",
    "video_tab": "Thẻ Video",
    "video_home": "Trang chủ Shopee Video",
    "aff_live": "Affiliate Live",
    "aff_video": "Affiliate Video",
}
AD_TYPE_LABELS = {
    "ads_roas_custom": "GMV tối đa ROAS tùy chỉnh",
    "ads_auto_bid": "GMV tối đa tự động đấu thầu",
    "ads_shop": "Quảng cáo cửa hàng",
    "ads_gmvmax_shop": "Product Ads (GMV Max-Shop)",
    "other": "Khác",
}
PROMO_LABELS = {
    "all": "Tất cả",
    "discount": "Khuyến mãi",
    "bundle": "Combo khuyến mãi",
    "add_on_deal": "Mua kèm deal sốc",
    "flash_sale": "Flash Sale",
    "voucher": "Voucher",
}
FLAG_LABELS = {
    "new_product": "Sản phẩm mới",
    "price_competitive": "Giá cạnh tranh",
    "price_uncompetitive": "Giá chưa cạnh tranh",
    "ads_grow": "Nên chạy quảng cáo để tăng trưởng",
    "ads_optimize": "Nên tối ưu quảng cáo",
    "ads_track": "Theo dõi quảng cáo",
}


class InvalidRange(ValueError):
    """The requested date range is reversed or longer than ``MAX_RANGE_DAYS``."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def json(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def resolve_range(start: date | None, end: date | None, latest: date | None) -> DateRange:
    """Explicit bounds win; otherwise the last 30 days ending on the newest stored day."""
    if end is None:
        end = latest or date.today()
    if start is None:
        start = end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise InvalidRange("from must not be after to")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise InvalidRange(f"range is longer than {MAX_RANGE_DAYS} days")
    return DateRange(start, end)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(round(Decimal(value), 4))


def _ratio(top: Any, bottom: Any) -> float | None:
    if top is None or not bottom:
        return None
    return float(round(Decimal(top) / Decimal(bottom), 6))


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _months_back(end: date, count: int) -> date:
    """The first day of the month ``count - 1`` months before ``end``'s month."""
    index = end.year * 12 + end.month - 1 - (count - 1)
    return date(index // 12, index % 12 + 1, 1)


def _is_calendar_month(start: date, end: date) -> bool:
    """A period inside one month that starts on its first day (a month or month-to-date)."""
    return start.day == 1 and (start.year, start.month) == (end.year, end.month)


async def _rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    statement = text(sql)
    for name, value in params.items():
        if isinstance(value, list):
            statement = statement.bindparams(bindparam(name, expanding=True))
    return list((await session.execute(statement, params)).all())


async def latest_day(session: AsyncSession, shop_id: uuid.UUID, dataset: str) -> date | None:
    rows = await _rows(
        session,
        "SELECT max(day) FROM platform_daily_metrics "
        "WHERE shop_id = :shop AND platform = 'shopee' AND dataset = :dataset",
        shop=shop_id,
        dataset=dataset,
    )
    return rows[0][0] if rows else None


# -- flows ---------------------------------------------------------------------------

_FLOW_DAILY = """
SELECT stream, segment, sum(gmv), sum(orders), sum(impressions), sum(clicks), sum(buyers)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview'
  AND item_id = '' AND order_type = :ot AND day BETWEEN :a AND :b
GROUP BY stream, segment
"""
_FLOW_MONTHLY_DAILY = """
SELECT date_trunc('month', day)::date AS month, stream, segment, sum(gmv), sum(orders)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview'
  AND item_id = '' AND order_type = :ot AND day BETWEEN :a AND :b
  AND (segment = 'all' OR segment = 'shop_page')
GROUP BY 1, 2, 3
"""
_FLOW_MONTHLY_PERIOD = """
SELECT period_start, period_end, stream, segment, gmv, orders
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview_period'
  AND item_id = '' AND order_type = :ot AND period_start >= :a AND period_end <= :b
  AND (segment = 'all' OR segment = 'shop_page')
"""
_SHOP_MONTHLY = """
SELECT date_trunc('month', day)::date AS month, stream, segment, sum(gmv), sum(orders)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'shop_overview'
  AND item_id = '' AND order_type = :ot AND day BETWEEN :a AND :b
GROUP BY 1, 2, 3
"""
_SHOP_MONTHLY_PERIOD = """
SELECT period_start, period_end, stream, segment, gmv, orders
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'shop_overview_period'
  AND item_id = '' AND order_type = :ot AND period_start >= :a AND period_end <= :b
"""


def _flow_cell(row: Any, offset: int) -> dict[str, float | None]:
    return {
        "gmv": _num(row[offset]),
        "orders": _num(row[offset + 1]),
        "impressions": _num(row[offset + 2]),
        "clicks": _num(row[offset + 3]),
        "buyers": _num(row[offset + 4]),
    }


def _sum(values: list[float | None]) -> float:
    return round(sum(v for v in values if v is not None), 4)


def build_flows(rows: list[Any]) -> dict[str, Any]:
    """Group (stream, segment, ...) rows into flows with children; ads stay an overlay."""
    by_stream: dict[str, dict[str, Any]] = {}
    for row in rows:
        stream, segment = row[0], row[1]
        cell = _flow_cell(row, 2)
        slot = by_stream.setdefault(stream, {"total": None, "children": []})
        if segment == "all":
            slot["total"] = cell
        else:
            slot["children"].append(
                {"segment": segment, "label": SEGMENT_LABELS.get(segment, segment), **cell}
            )
    flows = []
    for stream in FLOW_STREAMS:
        found = by_stream.get(stream)
        if found is None:
            continue
        slot = found
        slot["children"].sort(key=lambda c: -(c["gmv"] or 0))
        flows.append(
            {
                "stream": stream,
                "label": STREAM_LABELS[stream],
                **(slot["total"] or {}),
                "has_total_row": slot["total"] is not None,
                "children": slot["children"],
            }
        )
    ads = by_stream.get("ads")
    overlay = None
    if ads is not None:
        parts = [c for c in ads["children"]]
        overlay = {
            "stream": "ads",
            "label": STREAM_LABELS["ads"],
            "gmv": _sum([c["gmv"] for c in parts]),
            "orders": _sum([c["orders"] for c in parts]),
            "in_total": False,
        }
    return {
        # G3: only the level-1 total rows; a child (Trang shop, Tìm kiếm ...) is never added.
        "total_gmv": _sum([f.get("gmv") for f in flows]),
        "total_orders": _sum([f.get("orders") for f in flows]),
        "flows": flows,
        "ads_overlay": overlay,
    }


def _merge_months(
    daily: list[Any], period: list[Any], width: int
) -> dict[date, dict[tuple[str, str], list[float | None]]]:
    """Month -> (stream, segment) -> values; daily rows win, period rows fill missing months."""
    out: dict[date, dict[tuple[str, str], list[float | None]]] = defaultdict(dict)
    for row in daily:
        out[row[0]][(row[1], row[2])] = [_num(v) for v in row[3 : 3 + width]]
    daily_months = set(out)
    best: dict[tuple[date, str, str], Any] = {}
    for row in period:
        if not _is_calendar_month(row[0], row[1]):
            continue
        key = (row[0], row[2], row[3])
        if key not in best or row[1] > best[key][1]:
            best[key] = row
    for (month, stream, segment), row in best.items():
        if month not in daily_months:
            out[month][(stream, segment)] = [_num(v) for v in row[4 : 4 + width]]
    return out


async def shop_monthly(
    session: AsyncSession, shop_id: uuid.UUID, order_type: str, a: date, b: date
) -> list[dict[str, Any]]:
    """Shop GMV / orders per month: day rows of ``shop_overview`` win, calendar-month rows of
    ``shop_overview_period`` fill the months with none (the way flows merge traffic periods),
    so a history that came as monthly roll-ups (Jan-Sep) shows."""
    daily = await _rows(session, _SHOP_MONTHLY, shop=shop_id, ot=order_type, a=a, b=b)
    period = await _rows(session, _SHOP_MONTHLY_PERIOD, shop=shop_id, ot=order_type, a=a, b=b)
    merged = _merge_months(daily, period, 2)
    return [
        {
            "month": month.isoformat(),
            "gmv": cells[(stream, segment)][0],
            "orders": cells[(stream, segment)][1],
        }
        for month, cells in sorted(merged.items())
        for (stream, segment) in cells
        if (stream, segment) == ("total", "all")
    ]


async def flows(
    session: AsyncSession,
    shop_id: uuid.UUID,
    window: DateRange,
    order_type: str = DEFAULT_ORDER_TYPE,
) -> dict[str, Any]:
    rows = await _rows(
        session, _FLOW_DAILY, shop=shop_id, ot=order_type, a=window.start, b=window.end
    )
    body = build_flows(rows)
    h0 = _months_back(window.end, HISTORY_MONTHS)
    daily_m = await _rows(
        session, _FLOW_MONTHLY_DAILY, shop=shop_id, ot=order_type, a=h0, b=window.end
    )
    period_m = await _rows(
        session, _FLOW_MONTHLY_PERIOD, shop=shop_id, ot=order_type, a=h0, b=window.end
    )
    merged = _merge_months(daily_m, period_m, 2)
    monthly = []
    for month in sorted(merged):
        cells = merged[month]
        monthly.append(
            {
                "month": month.isoformat(),
                "streams": {s: v[0] for (s, seg), v in cells.items() if seg == "all"},
                "shop_page_gmv": cells.get(("product_card", "shop_page"), [None])[0],
            }
        )
    return {
        "range": window.json(),
        "order_type": order_type,
        **body,
        "monthly": monthly,
        "shop_monthly": await shop_monthly(session, shop_id, order_type, h0, window.end),
        "has_data": bool(rows),
    }


# -- products ------------------------------------------------------------------------

_PRODUCT_PERIODS = """
SELECT period_start, period_end, count(*)
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'product_period'
  AND order_type = :ot AND variation_id = ''
GROUP BY 1, 2
ORDER BY period_end DESC, period_start ASC
LIMIT 60
"""
_PRODUCT_FUNNEL = """
SELECT item_id, impressions, clicks, visitors, page_views, add_to_cart, orders, gmv, units, buyers
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'product_period'
  AND order_type = :ot AND variation_id = '' AND period_start = :ps AND period_end = :pe
"""
_PRODUCT_NAMES = """
SELECT item_id, variation_id, name
FROM platform_items
WHERE shop_id = :shop AND platform = 'shopee' AND item_id IN :ids
"""
_PRODUCT_BY_FLOW = """
SELECT item_id, stream, gmv, orders
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'item_by_source_period'
  AND order_type = :ot AND variation_id = '' AND segment = 'all'
  AND period_start = :ps AND period_end = :pe AND item_id IN :ids
"""
_PRODUCT_HISTORY = """
SELECT item_id, period_start, period_end, gmv, orders
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'product_period'
  AND order_type = :ot AND variation_id = '' AND period_start >= :a AND period_end <= :b
  AND item_id IN :ids
"""
_PRODUCT_FLAGS = """
SELECT item_id, flag, period_start, period_end
FROM platform_product_flags
WHERE shop_id = :shop AND platform = 'shopee' AND period_start <= :pe AND period_end >= :ps
  AND item_id IN :ids
"""


def _funnel(row: Any) -> dict[str, Any]:
    _, impressions, clicks, visitors, page_views, atc, orders, gmv, units, buyers = row
    return {
        "impressions": _num(impressions),
        "clicks": _num(clicks),
        "visitors": _num(visitors),
        "page_views": _num(page_views),
        "add_to_cart": _num(atc),
        "orders": _num(orders),
        "gmv": _num(gmv),
        "units": _num(units),
        "buyers": _num(buyers),
        "ctr": _ratio(clicks, impressions),
        "add_to_cart_rate": _ratio(atc, visitors),
        "click_to_order": _ratio(orders, clicks),
    }


def _pick_period(periods: list[Any], start: date | None, end: date | None) -> DateRange | None:
    if start is not None and end is not None:
        return DateRange(start, end)
    if not periods:
        return None
    first = periods[0]  # newest end, then the longest
    return DateRange(first[0], first[1])


async def products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    order_type: str = DEFAULT_ORDER_TYPE,
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    periods = await _rows(session, _PRODUCT_PERIODS, shop=shop_id, ot=order_type)
    period_list = [
        {"from": p[0].isoformat(), "to": p[1].isoformat(), "items": int(p[2])} for p in periods
    ]
    chosen = _pick_period(periods, period_start, period_end)
    empty: dict[str, Any] = {
        "order_type": order_type,
        "period": chosen.json() if chosen else None,
        "periods": period_list,
        "items_total": 0,
        "totals": None,
        "products": [],
        "shop_monthly": [],
        "has_data": False,
    }
    if chosen is None:
        return empty
    limit = max(1, min(limit, MAX_PRODUCTS))
    funnel_rows = await _rows(
        session,
        _PRODUCT_FUNNEL,
        shop=shop_id,
        ot=order_type,
        ps=chosen.start,
        pe=chosen.end,
    )
    if not funnel_rows:
        return empty
    funnel_rows.sort(key=lambda r: -(r[7] or 0))
    totals = _funnel(("", *[_total(funnel_rows, i) for i in range(1, 10)]))
    shown = funnel_rows[:limit]
    ids = [r[0] for r in shown]

    names: dict[str, str] = {}
    for item_id, variation_id, name in sorted(
        await _rows(session, _PRODUCT_NAMES, shop=shop_id, ids=ids), key=lambda r: r[1] != ""
    ):
        if name and item_id not in names:
            names[item_id] = name
    by_flow: dict[str, dict[str, dict[str, float | None]]] = defaultdict(dict)
    for item_id, stream, gmv, orders in await _rows(
        session,
        _PRODUCT_BY_FLOW,
        shop=shop_id,
        ot=order_type,
        ps=chosen.start,
        pe=chosen.end,
        ids=ids,
    ):
        by_flow[item_id][stream] = {"gmv": _num(gmv), "orders": _num(orders)}
    h0 = _months_back(chosen.end, HISTORY_MONTHS)
    history: dict[str, dict[date, tuple[date, float | None, float | None]]] = defaultdict(dict)
    for item_id, ps, pe, gmv, orders in await _rows(
        session, _PRODUCT_HISTORY, shop=shop_id, ot=order_type, a=h0, b=chosen.end, ids=ids
    ):
        if not _is_calendar_month(ps, pe):
            continue
        current = history[item_id].get(ps)
        if current is None or pe > current[0]:
            history[item_id][ps] = (pe, _num(gmv), _num(orders))
    flags: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for item_id, flag, ps, pe in await _rows(
        session, _PRODUCT_FLAGS, shop=shop_id, ps=chosen.start, pe=chosen.end, ids=ids
    ):
        seen = flags[item_id].get(flag)
        if seen is None or pe.isoformat() > seen["to"]:
            flags[item_id][flag] = {
                "flag": flag,
                "label": FLAG_LABELS.get(flag, flag),
                "from": ps.isoformat(),
                "to": pe.isoformat(),
            }
    # P92 B-9: giá (min-max, list struck) and biên with its basis, from the shop's own order lines
    # over the same period, the figures the matrix shows. Dashes (None) when there is no order data.
    money = await product_price_margin(
        session, shop_id, start=chosen.start, end=chosen.end, item_ids=ids
    )
    no_price = {
        "price_min": None,
        "price_max": None,
        "list_price": None,
        "price_basis": None,
        "margin_pct": None,
        "margin_basis": "chưa tính",
    }
    return {
        **empty,
        "items_total": len(funnel_rows),
        "totals": totals,
        "products": [
            {
                "item_id": row[0],
                "name": names.get(row[0]),
                **_funnel(row),
                **money.get(row[0], no_price),
                "by_flow": by_flow.get(row[0], {}),
                "history": [
                    {"month": m.isoformat(), "gmv": v[1], "orders": v[2]}
                    for m, v in sorted(history.get(row[0], {}).items())
                ],
                "flags": sorted(flags.get(row[0], {}).values(), key=lambda f: f["flag"]),
            }
            for row in shown
        ],
        "shop_monthly": await shop_monthly(session, shop_id, order_type, h0, chosen.end),
        "has_data": True,
    }


def _total(rows: list[Any], index: int) -> Decimal | None:
    values = [r[index] for r in rows if r[index] is not None]
    return sum(values, Decimal(0)) if values else None


# -- ads -----------------------------------------------------------------------------

# ``ads_expense`` lives in ``extra`` as a number (VND); anything else counts as no spend.
# ``segment <> 'all'``: ads rows carry the ad type as the segment; an ``all`` row would be
# the total of the types and must not be added to them.
_ADS_DAILY = """
SELECT day, segment, sum(gmv), sum(orders),
       sum(CASE WHEN jsonb_typeof(extra -> 'ads_expense') = 'number'
                THEN (extra ->> 'ads_expense')::numeric END),
       sum(impressions), sum(clicks)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview'
  AND stream = 'ads' AND segment <> 'all' AND item_id = '' AND order_type = :ot
  AND day BETWEEN :a AND :b
GROUP BY day, segment ORDER BY day
"""
_ADS_MONTHLY_DAILY = """
SELECT date_trunc('month', day)::date, segment, sum(gmv), sum(orders),
       sum(CASE WHEN jsonb_typeof(extra -> 'ads_expense') = 'number'
                THEN (extra ->> 'ads_expense')::numeric END)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview'
  AND stream = 'ads' AND segment <> 'all' AND item_id = '' AND order_type = :ot
  AND day BETWEEN :a AND :b
GROUP BY 1, segment
"""
# Connector ``ads_campaign_daily``: one Shopee ads-homepage row per campaign per day.
# ``cost`` / budget / ROAS target live in ``extra``; GMV and orders are the broad figures.
_ADS_CAMPAIGNS = """
SELECT segment,
       max(platform_source),
       sum(gmv), sum(orders), sum(impressions), sum(clicks),
       sum(CASE WHEN jsonb_typeof(extra -> 'cost') = 'number'
                THEN (extra ->> 'cost')::numeric END),
       max(extra ->> 'state'),
       max(CASE WHEN jsonb_typeof(extra -> 'daily_budget') = 'number'
                THEN (extra ->> 'daily_budget')::numeric END),
       max(CASE WHEN jsonb_typeof(extra -> 'roi_two_target') = 'number'
                THEN (extra ->> 'roi_two_target')::numeric END)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'ads_campaign_daily'
  AND segment <> 'all' AND order_type = :ot
  AND day BETWEEN :a AND :b
GROUP BY segment
ORDER BY 7 DESC NULLS LAST, 2
"""
_ADS_MONTHLY_PERIOD = """
SELECT period_start, period_end, 'ads', segment, gmv, orders,
       CASE WHEN jsonb_typeof(extra -> 'ads_expense') = 'number'
            THEN (extra ->> 'ads_expense')::numeric END
FROM platform_period_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'traffic_overview_period'
  AND stream = 'ads' AND segment <> 'all' AND item_id = '' AND order_type = :ot
  AND period_start >= :a AND period_end <= :b
"""


def _ad_cell(gmv: Any, orders: Any, cost: Any) -> dict[str, float | None]:
    cost_d = Decimal(cost) if cost is not None else None
    return {
        "cost": _num(cost_d),
        "orders": _num(orders),
        "gmv": _num(gmv),
        "roas": _ratio(gmv, cost_d),
        "cost_per_order": _ratio(cost_d, orders),
    }


def roas_alerts(daily: list[tuple[date, str, Any, Any]]) -> list[dict[str, Any]]:
    """Ad types whose latest run of consecutive days with spend all sit under ``ROAS_FLOOR``.

    ``daily``: (day, ad type, gmv, cost). Days without spend are not evidence either way
    and are ignored; a missing calendar day ends the run.
    """
    per_type: dict[str, dict[date, tuple[Decimal, Decimal]]] = defaultdict(dict)
    for day, ad_type, gmv, cost in daily:
        if cost is None or Decimal(cost) <= 0:
            continue
        gmv_d = Decimal(gmv or 0)
        old = per_type[ad_type].get(day, (Decimal(0), Decimal(0)))
        per_type[ad_type][day] = (old[0] + gmv_d, old[1] + Decimal(cost))
    alerts = []
    for ad_type, days in per_type.items():
        run: list[date] = []
        gmv_sum = cost_sum = Decimal(0)
        for day in sorted(days, reverse=True):
            gmv_d, cost_d = days[day]
            if gmv_d / cost_d >= ROAS_FLOOR or (run and run[-1] - day != timedelta(days=1)):
                break
            run.append(day)
            gmv_sum += gmv_d
            cost_sum += cost_d
        if len(run) >= ROAS_ALERT_MIN_DAYS:
            alerts.append(
                {
                    "ad_type": ad_type,
                    "label": AD_TYPE_LABELS.get(ad_type, ad_type),
                    "days": len(run),
                    "from": run[-1].isoformat(),
                    "to": run[0].isoformat(),
                    "roas": _ratio(gmv_sum, cost_sum),
                    "floor": float(ROAS_FLOOR),
                }
            )
    return sorted(alerts, key=lambda a: a["ad_type"])


async def ads(
    session: AsyncSession,
    shop_id: uuid.UUID,
    window: DateRange,
    order_type: str = DEFAULT_ADS_ORDER_TYPE,
) -> dict[str, Any]:
    daily_rows = await _rows(
        session, _ADS_DAILY, shop=shop_id, ot=order_type, a=window.start, b=window.end
    )
    types: dict[str, list[Any]] = defaultdict(lambda: [Decimal(0), Decimal(0), None])
    daily: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, None]))
    for day, ad_type, gmv, orders, cost, _impr, _clicks in daily_rows:
        slot = types[ad_type]
        slot[0] += Decimal(gmv or 0)
        slot[1] += Decimal(orders or 0)
        if cost is not None:
            slot[2] = (slot[2] or Decimal(0)) + Decimal(cost)
        daily[day.isoformat()][ad_type] = [gmv, orders, cost]
    by_type = [
        {
            "ad_type": ad_type,
            "label": AD_TYPE_LABELS.get(ad_type, ad_type),
            **_ad_cell(v[0], v[1], v[2]),
        }
        for ad_type, v in sorted(types.items())
    ]
    total_cost = sum((Decimal(v[2]) for v in types.values() if v[2] is not None), Decimal(0))
    total_gmv = sum((v[0] for v in types.values()), Decimal(0))
    total_orders = sum((v[1] for v in types.values()), Decimal(0))

    h0 = _months_back(window.end, HISTORY_MONTHS)
    monthly_daily = await _rows(
        session, _ADS_MONTHLY_DAILY, shop=shop_id, ot=order_type, a=h0, b=window.end
    )
    monthly_period = await _rows(
        session, _ADS_MONTHLY_PERIOD, shop=shop_id, ot=order_type, a=h0, b=window.end
    )
    merged = _merge_months(
        [(m, "ads", seg, g, o, c) for m, seg, g, o, c in monthly_daily], monthly_period, 3
    )
    monthly = []
    for month in sorted(merged):
        cells = merged[month]
        parts = [
            {
                "ad_type": seg,
                "label": AD_TYPE_LABELS.get(seg, seg),
                **_ad_cell(v[0], v[1], v[2]),
            }
            for (_stream, seg), v in sorted(cells.items())
        ]
        cost = sum((p["cost"] or 0) for p in parts)
        gmv = sum((p["gmv"] or 0) for p in parts)
        orders = sum((p["orders"] or 0) for p in parts)
        monthly.append(
            {
                "month": month.isoformat(),
                **_ad_cell(gmv, orders, cost or None),
                "by_type": parts,
            }
        )
    alerts = roas_alerts([(d, t, g, c) for d, t, g, _o, c, _i, _k in daily_rows])
    campaign_rows = await _rows(
        session, _ADS_CAMPAIGNS, shop=shop_id, ot=order_type, a=window.start, b=window.end
    )
    campaigns = [_campaign(row) for row in campaign_rows]
    # When the traffic-overview ads slice is missing, the homepage campaigns are the ads screen.
    if campaigns and not by_type:
        camp_gmv = sum((Decimal(c["gmv"] or 0) for c in campaigns), Decimal(0))
        camp_orders = sum((Decimal(c["orders"] or 0) for c in campaigns), Decimal(0))
        camp_cost = sum(
            (Decimal(c["cost"] or 0) for c in campaigns if c["cost"] is not None),
            Decimal(0),
        )
        total_gmv, total_orders, total_cost = camp_gmv, camp_orders, camp_cost
        by_type = [
            {
                "ad_type": "campaign",
                "label": "Chiến dịch",
                **_ad_cell(camp_gmv, camp_orders, camp_cost or None),
            }
        ]
    return {
        "range": window.json(),
        "order_type": order_type,
        "total": _ad_cell(total_gmv, total_orders, total_cost or None),
        "by_type": by_type,
        "daily": [
            {
                "day": day,
                "by_type": [
                    {"ad_type": t, **_ad_cell(v[0], v[1], v[2])} for t, v in sorted(parts.items())
                ],
            }
            for day, parts in sorted(daily.items())
        ],
        "monthly": monthly,
        "campaigns": campaigns,
        "campaigns_available": bool(campaigns),
        "alerts": alerts,
        "alert_rule": {"floor": float(ROAS_FLOOR), "min_days": ROAS_ALERT_MIN_DAYS},
        "has_data": bool(daily_rows) or bool(campaigns),
    }


def _campaign(row: Any) -> dict[str, Any]:
    """One Shopee ads-homepage campaign over the window: broad GMV / orders, cost in đồng."""
    _segment, name, gmv, orders, impressions, clicks, cost, state, budget, roi_target = row
    cell = _ad_cell(gmv, orders, cost)
    impr = Decimal(impressions) if impressions is not None else None
    clk = Decimal(clicks) if clicks is not None else None
    return {
        "campaign_id": str(_segment),
        "name": name or "Chiến dịch",
        "state": state,
        "impressions": _num(impr),
        "clicks": _num(clk),
        "ctr": _ratio(clk, impr),
        "daily_budget": _num(budget),
        "roi_target": _num(roi_target),
        **cell,
    }


# -- promotions ----------------------------------------------------------------------

_PROMO_PROGRAMS = """
SELECT promo_type, program_name, starts_at, ends_at, ordinal, max(status),
       sum(gmv), sum(orders), sum(units), sum(buyers)
FROM platform_promotions
WHERE shop_id = :shop AND platform = 'shopee' AND order_type = :ot
  AND period_start <= :b AND period_end >= :a
  AND period_start = date_trunc('month', period_start)
  AND date_trunc('month', period_end) = date_trunc('month', period_start)
  AND starts_at <= (CAST(:b AS date) + 1) AND (ends_at IS NULL OR ends_at >= CAST(:a AS date))
GROUP BY promo_type, program_name, starts_at, ends_at, ordinal
ORDER BY starts_at, promo_type, ordinal
"""
_PROMO_DAILY = """
SELECT day, segment, sum(gmv), sum(orders)
FROM platform_daily_metrics
WHERE shop_id = :shop AND platform = 'shopee' AND dataset = 'promotion_daily'
  AND order_type = :ot AND day BETWEEN :a AND :b
GROUP BY day, segment ORDER BY day
"""


async def promotions(
    session: AsyncSession,
    shop_id: uuid.UUID,
    window: DateRange,
    order_type: str = DEFAULT_ORDER_TYPE,
) -> dict[str, Any]:
    programs = await _rows(
        session, _PROMO_PROGRAMS, shop=shop_id, ot=order_type, a=window.start, b=window.end
    )
    daily = await _rows(
        session, _PROMO_DAILY, shop=shop_id, ot=order_type, a=window.start, b=window.end
    )
    return {
        "range": window.json(),
        "order_type": order_type,
        "programs": [
            {
                "promo_type": p[0],
                "type_label": PROMO_LABELS.get(p[0], p[0]),
                "name": p[1],
                "starts_at": p[2].isoformat(),
                "ends_at": p[3].isoformat() if p[3] else None,
                "status": p[5],
                "gmv": _num(p[6]),
                "orders": _num(p[7]),
                "units": _num(p[8]),
                "buyers": _num(p[9]),
            }
            for p in programs
        ],
        "daily": [
            {
                "day": r[0].isoformat(),
                "promo_type": r[1],
                "type_label": PROMO_LABELS.get(r[1], r[1]),
                "gmv": _num(r[2]),
                "orders": _num(r[3]),
            }
            for r in daily
        ],
        "has_data": bool(programs or daily),
    }
