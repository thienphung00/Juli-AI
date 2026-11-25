"""Data answers (E4): what / how much, no cause, no card. Rendered by code; no LLM.

Kinds: metric_total, top_products (from product rows), daily_trend, channel_breakdown (per-platform
labels, "thiếu dữ liệu" for a source without data). Every answer carries the freshness line.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.chains import (
    CHAIN_METRIC,
    bucket,
)
from juli_backend.services.analytics_agent.types import DataPort, LabelTable
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    clip_to_freshness,
    sale_days_vi,
)

MISSING = "thiếu dữ liệu"


def fresh_line(latest: date) -> str:
    return f"Số liệu đến hết {latest:%d/%m}"


async def run_lookup(
    data: DataPort,
    labels: LabelTable,
    kind: str,
    metric: str,
    preset: str,
    as_of: date,
    *,
    explicit: tuple[date, date] | None = None,
    named_month: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    """Returns the `data_answer` event payload, or {"stop": "data_missing"} when the shop has no
    data."""
    rows = await data.shop_daily(as_of, item_id)
    latest = max((r["day"] for r in rows if r["complete"]), default=None)
    if latest is None:
        return {"stop": "data_missing"}
    w = build_windows(
        preset,
        anchor_for(preset, as_of, latest),
        explicit=explicit,
        named_month=named_month,
        sale_aware=True,
    )
    w = clip_to_freshness(w, latest)  # no sum past the day the footer names
    out: dict[str, Any] = {
        "type": "data_answer",
        "kind": kind,
        "window_vi": w.label(),
        "fresh_vi": fresh_line(latest),
        "stop": "data_answer",
    }
    if sale := sale_days_vi(w):
        out["sale_vi"] = sale
    label = labels.metric(metric)
    scope = "products" if item_id else "shop"
    items = [item_id] if item_id else None
    if kind == "top_products":
        tot = {  # `query(group_by="item")` window totals, one row per product
            r["item_id"]: (float(r["gmv"] or 0), float(r["orders"] or 0))
            for r in await data.product_daily(*w.cur)
        }
        top = sorted(tot.items(), key=lambda kv: -kv[1][0])[:5]
        names = await data.item_names([k for k, _ in top])
        out["title_vi"] = "Top sản phẩm theo GMV"
        out["rows"] = [
            {
                "rank": i + 1,
                "item_id": k,
                "name": names.get(k, k),
                "gmv": g,
                "orders": o,
                "gmv_vi": fmt.value("gmv", g),
                "orders_vi": fmt.value("orders", o),
                # the UI row contract (`JuliDataRow`): label, value, detail, link
                "label_vi": names.get(k, k),
                "value_vi": fmt.value("gmv", g),
                "detail_vi": f"{fmt.value('orders', o)} đơn",
                "link": {"kind": "product", "item_id": k},
            }
            for i, (k, (g, o)) in enumerate(top)
        ]
    elif kind == "top_decliners":
        cur = {r["item_id"]: float(r["gmv"] or 0) for r in await data.product_daily(*w.cur)}
        old = {
            r["item_id"]: float(r["gmv"] or 0)
            for r in (await data.product_daily(*w.prev) if w.prev else [])
        }
        drops = sorted(
            ((k, cur.get(k, 0.0) - v, cur.get(k, 0.0), v) for k, v in old.items()),
            key=lambda t: t[1],
        )
        drops = [t for t in drops if t[1] < 0][:5]
        names = await data.item_names([k for k, *_ in drops])
        out["kind"] = "top_products"  # the UI's ranked-list kind
        out["title_vi"] = "Sản phẩm giảm mạnh nhất (GMV)"
        out["rows"] = [
            {
                "rank": i + 1,
                "item_id": k,
                "name": names.get(k, k),
                "label_vi": names.get(k, k),
                "value_vi": "▼ " + fmt.value("gmv", abs(d)),
                "detail_vi": f"{fmt.value('gmv', before)} → {fmt.value('gmv', now)}",
                "link": {"kind": "product", "item_id": k},
            }
            for i, (k, d, now, before) in enumerate(drops)
        ]
    elif kind == "daily_trend":
        day_rows = (
            await data.metrics(
                [registry_id(metric)], *w.cur, scope=scope, items=items, group_by="day"
            )
        ).get("rows", [])
        series = [(r["day"], _scaled(metric, r.get(registry_id(metric)))) for r in day_rows]
        out["title_vi"] = f"{label} theo ngày"
        out["series"] = [
            {
                "day": f"{d:%d/%m}",
                "label_vi": f"{d:%d/%m}",
                "value": v,
                "value_vi": fmt.value(metric, v),
            }
            for d, v in series
        ]
    elif kind == "channel_breakdown":
        v = await data.metric_view(metric, w.cur[0], w.cur[1], item_id)
        srows = await data.source_totals(*w.cur, item_id)
        seen = {bucket(r["source"]) for r in srows}
        reported = {bucket(r["source"]) for r in srows if r["views"] is not None}
        ch = []
        for c in v.get("channels") or []:
            partial = c["key"] in seen and c["key"] not in reported
            missing = c.get("now") is None
            ch.append(
                {
                    "channel": c["key"],
                    "label_vi": labels.source(c["key"]),
                    "value": c.get("now"),
                    "value_vi": fmt.value(metric, c.get("now")) if not missing else MISSING,
                    "note_vi": MISSING if (partial or missing) else None,
                    "missing": bool(partial or missing),
                }
            )
        out["title_vi"] = f"{label} theo kênh"
        out["rows"] = ch
    else:
        now, before = await _total(data, metric, w, item_id)
        out["title_vi"] = label
        # `value` is the display string the UI renders (`JuliDataAnswerData.value`); an object here
        # crashed the page (React #31). The raw numbers ride beside it.
        out["value"] = fmt.value(metric, now)
        out["value_raw"] = now
        out["before"] = before
        out["before_vi"] = fmt.value(metric, before) if w.prev else None
        out["delta"] = fmt.delta(metric, now, before) if w.prev else None
    return out


#: Chat metric keys that are named differently in the registry.
REGISTRY_ID = {"ads_spend": "cost_ads"}
POINTS = {
    "margin",
    "ctr",
    "ctor",
}  # the registry holds percentage points; the app formats a fraction


def registry_id(metric: str) -> str:
    return REGISTRY_ID.get(metric, metric)


def _scaled(metric: str, v: Any) -> float | None:
    """A registry value as the app's formatter takes it (points -> fraction); None stays None."""
    if v is None:
        return None
    return float(v) / 100 if metric in POINTS else float(v)


async def _total(
    data: DataPort, metric: str, w: Any, item_id: str | None = None
) -> tuple[float | None, float | None]:
    """The window's value and the window before it: one `query()` per window (the previous one is
    the sale-aware window). ROAS hoà vốn, profit, margin, ads and the counts are registry ids;
    nothing is summed here."""
    rid = registry_id(metric)
    scope = "products" if item_id else "shop"
    items = [item_id] if item_id else None

    async def read(win: tuple[date, date]) -> float | None:
        res = await data.metrics([rid], *win, scope=scope, items=items)
        return _scaled(metric, (res.get("values") or {}).get(rid))

    now = await read(w.cur)
    before = await read(w.prev) if w.prev else None  # the window the comparison names (sale-aware)
    return now, before


def default_metric(chain: str | None) -> str:
    return CHAIN_METRIC.get(chain or "", "gmv")
