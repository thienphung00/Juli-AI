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
    COUNTS,
    MONEY_METRICS,
    bucket,
    metric_value,
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
    if kind == "top_products":
        tot: dict[str, list[float]] = {}
        for r in await data.product_daily(*w.cur):
            t = tot.setdefault(r["item_id"], [0.0, 0.0])
            t[0] += float(r["gmv"] or 0)
            t[1] += float(r["orders"] or 0)
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
        cur: dict[str, float] = {}
        old: dict[str, float] = {}
        for r in await data.product_daily(*w.cur):
            cur[r["item_id"]] = cur.get(r["item_id"], 0.0) + float(r["gmv"] or 0)
        for r in await data.product_daily(*w.prev) if w.prev else []:
            old[r["item_id"]] = old.get(r["item_id"], 0.0) + float(r["gmv"] or 0)
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
        series = [
            (
                r["day"],
                metric_value(rows, metric, r["day"], r["day"])
                if metric in (*COUNTS, "aov", "ctr", "ctor")
                else None,
            )
            for r in rows
            if w.cur[0] <= r["day"] <= w.cur[1]
        ]
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
        srows = await data.source_daily(*w.cur, item_id)
        n = (w.cur[1] - w.cur[0]).days + 1
        cov: dict[str, float] = {}
        for s in {bucket(r["source"]) for r in srows}:
            cov[s] = (
                len(
                    {r["day"] for r in srows if bucket(r["source"]) == s and r["views"] is not None}
                )
                / n
            )
        ch = []
        for c in v.get("channels") or []:
            partial = c["key"] in cov and cov[c["key"]] < 0.8
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
        now, before = await _total(data, metric, w, rows)
        out["title_vi"] = label
        # `value` is the display string the UI renders (`JuliDataAnswerData.value`); an object here
        # crashed the page (React #31). The raw numbers ride beside it.
        out["value"] = fmt.value(metric, now)
        out["value_raw"] = now
        out["before"] = before
        out["before_vi"] = fmt.value(metric, before) if w.prev else None
        out["delta"] = fmt.delta(metric, now, before) if w.prev else None
    return out


async def _total(
    data: DataPort, metric: str, w: Any, rows: list[dict[str, Any]]
) -> tuple[float | None, float | None]:
    if metric == "roas_break_even":  # the registry's metric over the overview's shop components
        o1 = (await data.overview(*w.cur)).get("shop_profit") or {}
        o0 = ((await data.overview(*w.prev)).get("shop_profit") or {}) if w.prev else {}
        return _break_even(o1), (_break_even(o0) if w.prev else None)
    if metric in MONEY_METRICS:
        o1 = await data.overview(*w.cur)
        o0 = await data.overview(*w.prev) if w.prev else {}
        key = {
            "profit": ("shop_profit", "profit"),
            "margin": ("shop_profit", "margin_pct"),
            "ads_spend": ("shop_metrics", "ad_spend"),
            "roas": ("shop_metrics", "ads_roas_placed"),
        }[metric]
        now = (o1.get(key[0]) or {}).get(key[1])
        before = (o0.get(key[0]) or {}).get(key[1]) if o0 else None
        if metric == "margin":
            now = None if now is None else now / 100
            before = None if before is None else before / 100
        return now, before
    now = metric_value(rows, metric, *w.cur)
    return now, (metric_value(rows, metric, *w.prev) if w.prev else None)


def default_metric(chain: str | None) -> str:
    return CHAIN_METRIC.get(chain or "", "gmv")


def _break_even(shop_profit: dict[str, Any]) -> float | None:
    from juli_backend.services.analytics_agent.registry_reads import roas_break_even

    return roas_break_even(
        shop_profit.get("net_revenue"), shop_profit.get("contribution_before_ads")
    )
