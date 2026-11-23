"""Deterministic chains (J4 / J4g / P1b): formula -> scope -> time, bottom-up fallback.

Pure code, no LLM, no Jev. `within_noise` is decided at the BOTTOM (P1b): the chain always runs in
full; explained share >= 70 % -> explained (noise noted); < 70 % and inside the band with no Poisson
significance -> within_noise; < 70 % and outside -> unexplained. The only early stop is a headline
change < 3 % (or 0). NULL is never 0; a source with views on < 50 % of the current window's days is
missing; unknown source codes (`o:*`) are grouped as "khac" ("Khác").
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.analytics_agent import mathx
from juli_backend.services.analytics_agent.labels import SHOPEE_SOURCES
from juli_backend.services.analytics_agent.types import DataPort, LabelTable
from juli_backend.services.analytics_agent.windows import (
    Windows,
    anchor_for,
    build_windows,
    campaign_days,
)
from juli_backend.services.metrics.compute import raw_value

EXPLAINED_SHARE = 0.70
FOLLOW_SHARE = 0.20
TOP_N = 2
Z_FLAG = 3.0
NOISE_MIN = 0.01
NOISE_HISTORY_DAYS = 120
MIN_CHANGE = 0.03

KNOWN_SOURCES = ("the_san_pham_khac", "trang_shop", "video", "live", "lien_ket", "chenh_lech_nguon")
OTHER = "khac"
MONEY_METRICS = {"profit", "margin", "ads_spend", "roas"}
COST_METRIC = "cost_ratio"
CHAIN_METRIC = {
    "orders_change": "orders",
    "ctr_change": "ctr",
    "ctor_change": "ctor",
    "gmv_change": "gmv",
    "profit_change": "profit",
    "ads_change": "roas",
    "cost_change": COST_METRIC,
}
MV_METRICS = {"views", "ctr", "ctor", "aov", "orders", "gmv", "margin"}
MV_CHANNEL_SOURCE = {
    "trang_shop": "trang_shop",
    "video": "video",
    "live": "live",
    "lien_ket": "lien_ket",
}
COUNTS = ("gmv", "orders", "units", "views", "clicks")


def split_node(node: str, labels: LabelTable) -> tuple[str, str]:
    """`source.metric` -> (source, metric). A product name is never split: "[Deal 15.11] Combo"
    has a dot too, so only a known source or metric before it and a known metric after count."""
    base, _, sub = node.partition(".")
    if (
        sub
        and sub in labels.metrics
        and (base in labels.sources or base in labels.metrics or base == OTHER)
    ):
        return base, sub
    return node, ""


def bucket(src: str) -> str:
    return src if src in KNOWN_SOURCES else OTHER


@dataclass
class Finding:
    level: str
    node: str
    now: float | None
    before: float | None
    contribution_pct: float | None = None
    flags: list[str] = field(default_factory=list)
    evidence_ref: str = ""


@dataclass
class ChainResult:
    chain: str
    metric: str
    windows: Windows
    stop_reason: str
    findings: list[Finding]
    steps: list[str]
    explained_share: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    item_id: str | None = None
    item_name: str | None = None
    noise: dict[str, Any] | None = (
        None  # {"band": (lo, hi) | None, "in_band": bool | None, "significant": ..}
    )

    def node_vi(self, node: str, labels: LabelTable) -> str:
        base, sub = split_node(node, labels)
        if base in labels.sources or base == OTHER:
            label = labels.source(base)
        else:
            label = labels.metrics.get(base, base)
        return f"{label} ({labels.metric(sub)})" if sub else label

    def json(self, labels: LabelTable) -> dict[str, Any]:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 6)

        w = self.windows
        return {
            "chain": self.chain,
            "metric": self.metric,
            "stop_reason": self.stop_reason,
            "product": {"item_id": self.item_id, "name": self.item_name} if self.item_id else None,
            "window": {
                "preset": w.preset,
                "label_vi": w.label(),
                "cur": [str(x) for x in w.cur],
                "prev": [str(x) for x in w.prev] if w.prev else None,
                "context": [str(x) for x in w.context] if w.context else None,
                "same_weekday": [str(x) for x in w.same_weekday],
                "flags": w.flags,
            },
            "explained_share": r(self.explained_share),
            "findings": [
                {
                    **f.__dict__,
                    "node_vi": self.node_vi(f.node, labels),
                    "now": r(f.now),
                    "before": r(f.before),
                    "contribution_pct": r(f.contribution_pct),
                }
                for f in self.findings
            ],
            "events": self.events,
            "steps": self.steps,
            "noise": self.noise,
        }


# --------------------------------------------------------------------------- aggregates


def _sum(rows: list[dict[str, Any]], key: str, a: date, b: date) -> float | None:
    vals = [r[key] for r in rows if a <= r["day"] <= b and r.get(key) is not None]
    return float(sum(vals)) if vals else None


def _days_with(rows: list[dict[str, Any]], key: str, a: date, b: date) -> int:
    return len({r["day"] for r in rows if a <= r["day"] <= b and r.get(key) is not None})


#: ratio metric -> its components; the formula is the metric registry's (no second definition)
RATIO_COMPONENTS = {
    "aov": ("gmv", "orders"),
    "ctr": ("clicks", "views"),
    "ctor": ("orders", "clicks"),
}


def metric_value(rows: list[dict[str, Any]], metric: str, a: date, b: date) -> float | None:
    """Sum of a count over the window, or a ratio evaluated by `services.metrics` (NULL stays
    NULL)."""
    if metric in COUNTS:
        return _sum(rows, metric, a, b)
    comps = {
        c: (None if (v := _sum(rows, c, a, b)) is None else Decimal(str(v)))
        for c in RATIO_COMPONENTS[metric]
    }
    out = raw_value(metric, comps)
    return float(out) if isinstance(out, Decimal) else None


def noise_band(
    rows: list[dict[str, Any]], metric: str, length: int, before: date
) -> tuple[float, float] | None:
    """F3: changes between back-to-back windows of `length` days in the recent history (10th-90th
    pct)."""
    first = before - timedelta(days=NOISE_HISTORY_DAYS)
    days = sorted(r["day"] for r in rows if first <= r["day"] < before)
    if len(days) < length * 3:
        return None
    zs: list[float] = []
    end = before - timedelta(days=1)
    first = max(first, days[0])
    while end - timedelta(days=2 * length - 1) >= first:
        a1, b1 = end - timedelta(days=length - 1), end
        a0, b0 = a1 - timedelta(days=length), a1 - timedelta(days=1)
        v1, v0 = metric_value(rows, metric, a1, b1), metric_value(rows, metric, a0, b0)
        if v0 and v1 is not None:
            zs.append((v1 - v0) / v0)
        end -= timedelta(days=1)
    if len(zs) < 8:
        return None
    zs.sort()

    def q(p: float) -> float:
        return zs[min(len(zs) - 1, max(0, round(p * (len(zs) - 1))))]

    return min(q(0.10), -NOISE_MIN), max(q(0.90), NOISE_MIN)


def _drill_base(w: Windows) -> tuple[date, date]:
    """The comparison window of the drills. Yesterday: the latest same weekday that is not a double
    day."""
    if w.prev:
        return w.prev
    base = next((d for d in w.same_weekday if d.day != d.month), w.same_weekday[0])
    return base, base


# --------------------------------------------------------------------------- chain runner


async def run_chain(
    data: DataPort,
    chain: str,
    metric: str | None,
    preset: str,
    as_of: date,
    *,
    item_id: str | None = None,
    explicit: tuple[date, date] | None = None,
    named_month: str | None = None,
    fallback: bool = True,
) -> ChainResult:
    metric = metric or CHAIN_METRIC.get(chain, "gmv")
    if item_id and (metric in MONEY_METRICS - {"margin"} or metric == COST_METRIC):
        metric = "gmv" if metric != COST_METRIC else metric
    rows = await data.shop_daily(as_of, item_id)
    complete = [r for r in rows if r["complete"]]
    latest = max((r["day"] for r in complete), default=None)
    names = await data.item_names([item_id]) if item_id else {}
    res_kw: dict[str, Any] = {
        "item_id": item_id,
        "item_name": names.get(item_id) if item_id else None,
    }
    if latest is None:
        w = build_windows(preset, as_of)
        return ChainResult(
            chain,
            metric,
            w,
            "data_missing",
            [Finding("shop", "shop_metrics_daily", None, None, flags=["no_rows"])],
            ["step0: no complete shop rows"],
            item_id=res_kw["item_id"],
            item_name=res_kw["item_name"],
        )
    anchor = anchor_for(preset, as_of, latest)
    w = build_windows(preset, anchor, explicit=explicit, named_month=named_month)
    steps = [f"step0: latest complete day {latest}; window {w.label()} ({w.preset})"]
    if preset == "yesterday_vs_same_weekday" and latest < as_of:
        return ChainResult(
            chain,
            metric,
            w,
            "data_stale",
            [
                Finding(
                    "shop", "latest_complete_day", None, None, flags=[f"latest_complete:{latest}"]
                )
            ],
            steps,
            item_id=res_kw["item_id"],
            item_name=res_kw["item_name"],
        )

    need = {"ctr": "views", "ctor": "clicks", "views": "views", "clicks": "clicks"}.get(
        metric, "orders"
    )
    if metric == COST_METRIC:
        need = "orders"

    def cov(a: date, b: date) -> float:
        return _days_with(rows, need, a, b) / ((b - a).days + 1)

    c_cur = cov(*w.cur)
    if w.same_weekday:
        c_prev = sum(
            1
            for d in w.same_weekday
            if any(r["day"] == d and r.get(need) is not None for r in rows)
        ) / len(w.same_weekday)
    else:
        c_prev = cov(*w.prev) if w.prev else 1.0
    steps.append(f"step0: coverage cur {c_cur:.0%} prev {c_prev:.0%} ({need})")
    if min(c_cur, c_prev) < 0.5:
        return ChainResult(
            chain,
            metric,
            w,
            "data_missing",
            [Finding("shop", f"coverage_{need}", c_cur, c_prev, flags=["coverage_below_50"])],
            steps,
            item_id=res_kw["item_id"],
            item_name=res_kw["item_name"],
        )
    per_day = min(c_cur, c_prev) < 0.8
    if per_day:
        w.flags.append("partial_coverage")

    if metric == COST_METRIC:
        res = await _cost_chain(data, chain, w, rows, steps, item_id, fallback)
    elif metric in MONEY_METRICS:
        res = await _money_chain(data, chain, metric, w, rows, steps, fallback, item_id)
    else:
        res = await _count_chain(
            data, chain, metric, w, rows, steps, per_day, need, item_id, fallback
        )
    res.item_id, res.item_name = res_kw["item_id"], res_kw["item_name"]
    return res


async def _count_chain(
    data: DataPort,
    chain: str,
    metric: str,
    w: Windows,
    rows: list[dict[str, Any]],
    steps: list[str],
    per_day: bool,
    need: str,
    item_id: str | None,
    fallback: bool,
) -> ChainResult:
    findings: list[Finding] = []

    def val(a: date, b: date, m: str = metric) -> float | None:
        v = metric_value(rows, m, a, b)
        if v is not None and per_day and m in COUNTS:
            v /= max(1, _days_with(rows, need, a, b))
        return v

    now = val(*w.cur)
    band: tuple[float, float] | None = None
    if w.same_weekday:
        hist = [
            h for h in (metric_value(rows, metric, d, d) for d in w.same_weekday) if h is not None
        ]
        before = statistics.fmean(hist) if hist else None
        d28 = sorted(
            v
            for v in (
                metric_value(
                    rows, metric, w.cur[0] - timedelta(days=k), w.cur[0] - timedelta(days=k)
                )
                for k in range(1, 29)
            )
            if v is not None
        )
        if before and len(d28) >= 14:

            def q(p: float) -> float:
                return d28[round(p * (len(d28) - 1))]

            band = ((q(0.10) - before) / before, (q(0.90) - before) / before)
            zeros = sum(1 for v in d28 if v == 0)
            if zeros:
                w.flags.append(f"zero_days_last_28:{zeros}")
    else:
        before = val(*w.prev) if w.prev else None
        length = (w.cur[1] - w.cur[0]).days + 1
        band = noise_band(rows, metric, length, w.cur[0])
    head = Finding("shop", metric, now, before)
    if w.context:
        head.flags.append(f"context_full_prev_month:{metric_value(rows, metric, *w.context)}")
    findings.append(head)
    if now is None or before is None:
        return ChainResult(chain, metric, w, "data_missing", findings, steps)
    rel = (now - before) / before if before else None
    steps.append(
        f"step1: {metric} {before:.4g} -> {now:.4g}" + (f" ({rel:+.1%})" if rel is not None else "")
    )
    in_band: bool | None = None
    if band:
        head.flags.append(f"noise_band:{band[0]:+.1%}..{band[1]:+.1%}")
        in_band = rel is not None and band[0] <= rel <= band[1]
        head.flags.append("inside_noise_band" if in_band else "outside_noise_band")
    else:
        head.flags.append("no_noise_band")
    significant: bool | None = None
    if metric in ("orders", "clicks", "views", "units") and not per_day:
        days_cur = (w.cur[1] - w.cur[0]).days + 1
        assert w.prev or w.same_weekday
        prev = w.prev
        lam = (
            before
            if w.same_weekday or prev is None
            else before * days_cur / ((prev[1] - prev[0]).days + 1)
        )
        z = mathx.poisson_z(now, lam)
        if z is not None:
            significant = abs(z) >= 1.96
            head.flags += [
                f"poisson_z:{z:+.2f}",
                "significant" if significant else "not_significant",
            ]
    noise_ok = (in_band is True and significant is not True) or (
        in_band is None and significant is False
    )
    noise = {"band": band, "in_band": in_band, "significant": significant}
    delta = now - before
    if delta == 0 or (rel is not None and abs(rel) < MIN_CHANGE):
        head.flags.append(f"change_below_{MIN_CHANGE:.0%}")
        steps.append("stop: within_noise (change below 3 %)")
        return ChainResult(chain, metric, w, "within_noise", findings, steps, noise=noise)

    explained: list[float] = []
    a1, b1 = w.cur
    a0, b0 = _drill_base(w)
    if not w.prev:
        steps.append(f"step2: drill-down compares with {a0:%d/%m}")
    followed = metric
    if metric in ("orders", "gmv"):
        if metric == "orders":
            fac = {
                "views": (val(a0, b0, "views"), val(a1, b1, "views")),
                "ctr": (metric_value(rows, "ctr", a0, b0), metric_value(rows, "ctr", a1, b1)),
                "ctor": (metric_value(rows, "ctor", a0, b0), metric_value(rows, "ctor", a1, b1)),
            }
        else:
            fac = {
                "orders": (val(a0, b0, "orders"), val(a1, b1, "orders")),
                "aov": (metric_value(rows, "aov", a0, b0), metric_value(rows, "aov", a1, b1)),
            }
        if all(x is not None and y is not None for x, y in fac.values()):
            eff = mathx.lmdi(
                before,
                now,
                {k: (float(x or 0), float(y or 0)) for k, (x, y) in fac.items()},
            )
            for k, e in sorted(eff.items(), key=lambda kv: -abs(kv[1])):
                findings.append(
                    Finding(
                        "formula",
                        k,
                        fac[k][1],
                        fac[k][0],
                        100 * e / delta,
                        evidence_ref=f"lmdi:{metric}",
                    )
                )
            same = [(k, e) for k, e in eff.items() if e * delta > 0]
            if same:
                followed = max(same, key=lambda kv: abs(kv[1]))[0]
            steps.append(
                "step2 lmdi: " + ", ".join(f"{k} {100 * e / delta:+.0f}%" for k, e in eff.items())
            )
        else:
            steps.append("step2: factors missing -> skip formula split")

    srows = await data.source_daily(a0, b1, item_id)

    def seg(a: date, b: date, num: str, den: str | None) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        for src in (*KNOWN_SOURCES, OTHER):
            rs = [r for r in srows if bucket(r["source"]) == src and a <= r["day"] <= b]
            if den is None:
                vals = [r[num] for r in rs if r[num] is not None]
                if vals:
                    out[src] = (float(sum(vals)), 1.0)
            else:
                pairs = [(r[num], r[den]) for r in rs if r[num] is not None and r[den] is not None]
                if pairs:
                    out[src] = (float(sum(p[0] for p in pairs)), float(sum(p[1] for p in pairs)))
        return out

    def src_cov(src: str, a: date, b: date) -> float:
        return len(
            {
                r["day"]
                for r in srows
                if bucket(r["source"]) == src and r["views"] is not None and a <= r["day"] <= b
            }
        ) / ((b - a).days + 1)

    missing_src = [
        s
        for s in KNOWN_SOURCES
        if s != "chenh_lech_nguon" and src_cov(s, a0, b0) >= 0.5 and src_cov(s, a1, b1) < 0.5
    ]
    for s in missing_src:
        findings.append(
            Finding(
                "source",
                s,
                None,
                None,
                flags=["no_data_in_current_window"],
                evidence_ref="source_metrics_daily",
            )
        )
    if followed in ("ctr", "ctor"):
        num, den = ("clicks", "views") if followed == "ctr" else ("orders", "clicks")
        s0, s1 = seg(a0, b0, num, den), seg(a1, b1, num, den)
        for s in missing_src:
            s0.pop(s, None)
            s1.pop(s, None)
        rm = mathx.rate_mix(s0, s1)
        r0 = metric_value(rows, followed, a0, b0) or 0
        r1 = metric_value(rows, followed, a1, b1) or 0
        d_r = sum(v["rate"] + v["mix"] for v in rm.values()) or (r1 - r0)
        parts = sorted(
            ((k, v["rate"] + v["mix"], v) for k, v in rm.items()), key=lambda t: -abs(t[1])
        )
        for k, tot, v in parts:
            if d_r and abs(tot / d_r) >= FOLLOW_SHARE:
                findings.append(
                    Finding(
                        "source",
                        k,
                        v["r1"],
                        v["r0"],
                        100 * tot / d_r,
                        flags=[f"rate_effect:{v['rate']:+.5f}", f"mix_effect:{v['mix']:+.5f}"],
                        evidence_ref=f"rate_mix:{followed}",
                    )
                )
        follow = [
            (k, tot)
            for k, tot, _ in parts
            if d_r and tot * d_r > 0 and abs(tot / d_r) >= FOLLOW_SHARE
        ][:TOP_N]
        if follow:
            explained.append(sum(t for _, t in follow) / d_r)
        steps.append("step3 rate/mix " + followed)
    else:
        key = {"views": "views", "clicks": "clicks"}.get(
            followed, "orders" if followed == "orders" else "gmv"
        )
        if followed != "aov":
            s0, s1 = seg(a0, b0, key, None), seg(a1, b1, key, None)
            d_src = {
                k: s1.get(k, (0.0, 1.0))[0] - s0.get(k, (0.0, 1.0))[0]
                for k in set(s0) | set(s1)
                if k not in missing_src
            }
            tot = sum(d_src.values())
            parts2 = sorted(d_src.items(), key=lambda kv: -abs(kv[1]))
            for k, d in parts2:
                if tot and abs(d / tot) >= FOLLOW_SHARE:
                    findings.append(
                        Finding(
                            "source",
                            f"{k}.{key}",
                            s1.get(k, (None,))[0],
                            s0.get(k, (None,))[0],
                            100 * d / tot,
                            evidence_ref=f"additive:{key}",
                        )
                    )
            fol = [d for k, d in parts2 if tot and d * tot > 0 and abs(d / tot) >= FOLLOW_SHARE][
                :TOP_N
            ]
            if fol and tot:
                explained.append(sum(fol) / tot)
            steps.append(f"step3 additive {key}")

    sold_prev: set[str] | None = None
    prow = await data.product_daily(a0, b1) if not item_id else []
    if metric in ("orders", "gmv") and prow:
        key = "gmv" if metric == "gmv" else "orders"
        p0: dict[str, float] = {}
        p1: dict[str, float] = {}
        for r in prow:
            if a0 <= r["day"] <= b0:
                p0[r["item_id"]] = p0.get(r["item_id"], 0) + float(r[key] or 0)
            elif a1 <= r["day"] <= b1:
                p1[r["item_id"]] = p1.get(r["item_id"], 0) + float(r[key] or 0)
        cov0 = len({r["day"] for r in prow if a0 <= r["day"] <= b0}) / ((b0 - a0).days + 1)
        if cov0 < 0.5:
            findings.append(
                Finding(
                    "product",
                    "product_rows",
                    None,
                    None,
                    flags=[f"product_coverage_prev:{cov0:.0%}"],
                    evidence_ref="product_metrics_daily",
                )
            )
            steps.append(
                "step4: product rows cover too little of the comparison window -> chưa kiểm tra "
                "được"
            )
        else:
            dp = {k: p1.get(k, 0) - p0.get(k, 0) for k in set(p0) | set(p1)}
            tot = sum(dp.values())
            top = sorted(dp.items(), key=lambda kv: -abs(kv[1]))[:5]
            pn = await data.item_names([k for k, _ in top])
            for k, d in top:
                if tot and abs(d / tot) >= FOLLOW_SHARE:
                    findings.append(
                        Finding(
                            "product",
                            pn.get(k, k),
                            p1.get(k, 0),
                            p0.get(k, 0),
                            100 * d / tot,
                            evidence_ref=f"product:{k}",
                        )
                    )
            fol2 = [d for _, d in top if tot and d * tot > 0 and abs(d / tot) >= FOLLOW_SHARE][
                :TOP_N
            ]
            if fol2 and tot:
                explained.append(sum(fol2) / tot)
            sold_prev = {k for k, v in p0.items() if v > 0}
            steps.append("step4 products")

    series = [
        (r["day"], float(r[metric]))
        for r in rows
        if a0 <= r["day"] <= b1 and metric in COUNTS and r.get(metric) is not None
    ]
    cp = mathx.change_point(series) if len(series) >= 6 else None
    if cp and cp < a1:
        findings.append(
            Finding("time", "change_point", None, None, flags=[f"started_before_window:{cp}"])
        )
        cp = None
    if cp:
        findings.append(Finding("time", "change_point", None, None, flags=[f"start_day:{cp}"]))

    await _endpoint_scope(data, metric, w, findings, steps, explained, missing_src, item_id)

    share = min(1.0, max(explained)) if explained else None
    stop = "explained" if share is not None and share >= EXPLAINED_SHARE else "unexplained"
    res = ChainResult(chain, metric, w, stop, findings, steps, share, noise=noise)
    if stop == "unexplained" and fallback:
        await _bottom_up(data, res, rows, metric, (a1, b1), delta, sold_prev)
    if res.stop_reason == "unexplained" and noise_ok:
        res.stop_reason = "within_noise"
    steps.append(f"stop: {res.stop_reason}")
    return res


async def _bottom_up(
    data: DataPort,
    res: ChainResult,
    rows: list[dict[str, Any]],
    metric: str,
    cur: tuple[date, date],
    delta: float,
    sold_prev: set[str] | None = None,
) -> None:
    a, b = cur
    res.steps.append("fallback: bottom-up event scan")
    impact = 0.0
    key = metric if metric in COUNTS else "gmv"
    hist = [
        float(r[key])
        for r in rows
        if a - timedelta(days=28) <= r["day"] < a and r.get(key) is not None
    ]
    exp = statistics.median(hist) if hist else None
    for r in rows:
        if a <= r["day"] <= b and r.get(key) is not None:
            z = mathx.robust_z(float(r[key]), hist)
            if z is not None and abs(z) >= Z_FLAG:
                gap = float(r[key]) - (exp or 0)
                res.events.append(
                    {
                        "kind": "daily_outlier",
                        "day": str(r["day"]),
                        "value": float(r[key]),
                        "expected": exp,
                        "z": round(z, 2),
                        "impact": gap,
                    }
                )
                impact += gap
    ah = [
        float(r["ads_spend"])
        for r in rows
        if a - timedelta(days=28) <= r["day"] < a and r.get("ads_spend") is not None
    ]
    for r in rows:
        if a <= r["day"] <= b and r.get("ads_spend") is not None:
            z = mathx.robust_z(float(r["ads_spend"]), ah)
            if z is not None and z <= -Z_FLAG:
                res.events.append(
                    {
                        "kind": "ads_spend_drop",
                        "day": str(r["day"]),
                        "value": float(r["ads_spend"]),
                        "expected": statistics.median(ah),
                        "z": round(z, 2),
                    }
                )
    st = await data.stock_events(a, b)
    sold = sold_prev

    def keep(i: str) -> bool:
        return sold is None or i in sold

    out_items = sorted({r["item_id"] for r in st if r["min_available"] == 0 and keep(r["item_id"])})
    unl = sorted(
        {
            r["item_id"]
            for r in st
            if r["statuses"] and "unlisted" in r["statuses"] and keep(r["item_id"])
        }
    )
    if st:
        nm = await data.item_names(out_items[:5] + unl[:5])
        if out_items:
            res.events.append(
                {
                    "kind": "stock_out",
                    "items": [nm.get(i, i) for i in out_items[:5]],
                    "count": len(out_items),
                }
            )
        if unl:
            res.events.append(
                {"kind": "unlisted", "items": [nm.get(i, i) for i in unl[:5]], "count": len(unl)}
            )
    for d in campaign_days(a, b):
        res.events.append({"kind": "campaign_day", "day": str(d)})
    if delta and impact and impact * delta > 0 and abs(impact / delta) >= EXPLAINED_SHARE:
        res.stop_reason = "explained"
        res.explained_share = min(1.0, abs(impact / delta))


async def _endpoint_scope(
    data: DataPort,
    metric: str,
    w: Windows,
    findings: list[Finding],
    steps: list[str],
    explained: list[float],
    missing_src: list[str],
    item_id: str | None,
) -> None:
    """metric-view by channel and product; only when its previous window equals ours."""
    if metric not in MV_METRICS or not w.prev:
        return
    n = (w.cur[1] - w.cur[0]).days + 1
    if w.prev != (w.cur[0] - timedelta(days=n), w.cur[0] - timedelta(days=1)):
        steps.append("endpoint metric-view: comparison window differs -> SQL scope only")
        return
    v = await data.metric_view(metric, w.cur[0], w.cur[1], item_id)
    total = (v.get("total") or {}).get("impact")
    if total is None:
        imps = [p["impact"] for p in v.get("products") or [] if p.get("impact") is not None]
        total = sum(imps) if imps else None
    rows: list[tuple[str, dict[str, Any]]] = []
    for c in v.get("channels") or []:
        if MV_CHANNEL_SOURCE.get(c["key"]) in missing_src:
            findings.append(
                Finding(
                    "endpoint.channel",
                    c["key"],
                    None,
                    None,
                    flags=["no_data_in_current_window"],
                    evidence_ref=f"metric_view:{metric}:channel:{c['key']}",
                )
            )
            continue
        rows.append(("channel", c))
    rows += [("product", p) for p in v.get("products") or []]
    for kind, r in rows:
        if r.get("impact") is None or not total:
            continue
        sh = r["impact"] / total
        if abs(sh) >= FOLLOW_SHARE:
            findings.append(
                Finding(
                    f"endpoint.{kind}",
                    r.get("name") or r["key"],
                    r.get("now"),
                    r.get("prev"),
                    100 * sh,
                    flags=[f"impact_vnd:{r['impact']:.0f}"],
                    evidence_ref=f"metric_view:{metric}:{kind}:{r['key']}",
                )
            )
    prods = sorted(
        (
            p["impact"]
            for k, p in rows
            if k == "product" and p.get("impact") is not None and total and p["impact"] * total > 0
        ),
        key=abs,
        reverse=True,
    )[:TOP_N]
    if prods and total:
        explained.append(sum(prods) / total)
    steps.append(f"endpoint metric-view {metric}: {len(rows)} rows")


# --------------------------------------------------------------------------- money chains


async def _money_chain(
    data: DataPort,
    chain: str,
    metric: str,
    w: Windows,
    rows: list[dict[str, Any]],
    steps: list[str],
    fallback: bool,
    item_id: str | None,
) -> ChainResult:
    findings: list[Finding] = []
    explained: list[float] = []
    a1, b1 = w.cur
    a0, b0 = _drill_base(w)
    o1, o0 = await data.overview(a1, b1), await data.overview(a0, b0)
    p1, p0 = o1.get("shop_profit") or {}, o0.get("shop_profit") or {}
    m1, m0 = o1.get("shop_metrics") or {}, o0.get("shop_metrics") or {}
    if metric in ("profit", "margin"):
        key = "profit" if metric == "profit" else "margin_pct"
        now, before = p1.get(key), p0.get(key)
        if metric == "margin":
            now = None if now is None else now / 100
            before = None if before is None else before / 100
        cov1, cov0 = p1.get("gmv_share_pct"), p0.get("gmv_share_pct")
        head = Finding(
            "shop",
            metric,
            now,
            before,
            flags=[f"cost_coverage_now:{cov1}%", f"cost_coverage_before:{cov0}%"],
            evidence_ref="overview:shop_profit",
        )
        if (cov1 or 0) < 50 or (cov0 or 0) < 50:
            return ChainResult(
                chain, metric, w, "data_missing", [head], steps + ["step1: cost coverage < 50 %"]
            )
        if (cov1 or 0) < 80 or (cov0 or 0) < 80:
            w.flags.append("partial_cost_coverage")
    else:
        now, before = (
            (m1.get("ad_spend"), m0.get("ad_spend"))
            if metric == "ads_spend"
            else (m1.get("ads_roas_placed"), m0.get("ads_roas_placed"))
        )
        head = Finding("shop", metric, now, before, evidence_ref="overview:shop_metrics")
    findings.append(head)
    if now is None or before is None:
        return ChainResult(chain, metric, w, "data_missing", findings, steps + ["step1: no value"])
    rel = (now - before) / abs(before) if before else None
    delta = now - before
    if delta == 0 or (rel is not None and abs(rel) < MIN_CHANGE):
        return ChainResult(
            chain, metric, w, "within_noise", findings, steps + ["stop: within_noise (< 3 %)"]
        )
    if metric == "profit":
        b_1, b_0 = p1.get("bridge") or {}, p0.get("bridge") or {}
        parts = {
            "product_profit": (b_1.get("product_profit"), b_0.get("product_profit")),
            "ads_no_order_days": (
                -(b_1.get("ads_no_order_days") or 0),
                -(b_0.get("ads_no_order_days") or 0),
            ),
            "other_marketing": (
                -(b_1.get("other_marketing") or 0),
                -(b_0.get("other_marketing") or 0),
            ),
        }
        same: list[float] = []
        for k, (x1, x0) in parts.items():
            if x1 is None or x0 is None:
                continue
            d = x1 - x0
            if abs(d / delta) >= FOLLOW_SHARE:
                findings.append(
                    Finding("formula", k, x1, x0, 100 * d / delta, evidence_ref="overview:bridge")
                )
            if d * delta > 0:
                same.append(d)
        if same:
            explained.append(max(same, key=abs) / delta)
    elif metric == "margin":
        pr0, pr1 = p0.get("profit"), p1.get("profit")
        nr0, nr1 = p0.get("net_revenue"), p1.get("net_revenue")
        pr, nr = (pr0, pr1), (nr0, nr1)
        if pr0 and pr1 and nr0 and nr1 and min(pr0, pr1, nr0, nr1) > 0:
            lp, ln_ = math.log(pr1 / pr0), -math.log(nr1 / nr0)
            tot = lp + ln_
            if tot:
                findings.append(
                    Finding(
                        "formula",
                        "profit",
                        pr[1],
                        pr[0],
                        100 * lp / tot,
                        evidence_ref="overview:shop_profit",
                    )
                )
                findings.append(
                    Finding(
                        "formula",
                        "net_revenue",
                        nr[1],
                        nr[0],
                        100 * ln_ / tot,
                        evidence_ref="overview:shop_profit",
                    )
                )
        await _endpoint_scope(data, "margin", w, findings, steps, explained, [], item_id)
    else:
        g0, g1 = _sum(rows, "ads_gmv", a0, b0), _sum(rows, "ads_gmv", a1, b1)
        sp0, sp1 = _sum(rows, "ads_spend", a0, b0), _sum(rows, "ads_spend", a1, b1)
        g, sp = (g0, g1), (sp0, sp1)
        if metric == "roas" and g0 and g1 and sp0 and sp1 and min(g0, g1, sp0, sp1) > 0:
            lg, ls = math.log(g1 / g0), -math.log(sp1 / sp0)
            tot = lg + ls
            if tot:
                findings.append(
                    Finding(
                        "formula",
                        "ads_gmv",
                        g[1],
                        g[0],
                        100 * lg / tot,
                        evidence_ref="shop_metrics_daily",
                    )
                )
                findings.append(
                    Finding(
                        "formula",
                        "ads_spend",
                        sp[1],
                        sp[0],
                        100 * ls / tot,
                        evidence_ref="shop_metrics_daily",
                    )
                )
                explained.append(max((lg, ls), key=lambda v: v * tot) / tot)
    share = min(1.0, max(explained)) if explained else None
    stop = "explained" if share is not None and share >= EXPLAINED_SHARE else "unexplained"
    res = ChainResult(chain, metric, w, stop, findings, steps, share)
    if stop == "unexplained" and fallback:
        await _bottom_up(data, res, rows, "gmv", (a1, b1), 0.0)
    steps.append(f"stop: {res.stop_reason}")
    return res


# --------------------------------------------------------------------------- cost_change (U2e)


def _cost(lines: dict[str, Any]) -> float | None:
    """Tổng chi phí = ads + affiliate (the known ones; both unknown = None, never 0). Offers is its
    own line."""
    known = [lines[k] for k in ("cost_ads", "cost_affiliate") if lines.get(k) is not None]
    return float(sum(known)) if known else None


async def _cost_chain(
    data: DataPort,
    chain: str,
    w: Windows,
    rows: list[dict[str, Any]],
    steps: list[str],
    item_id: str | None,
    fallback: bool,
) -> ChainResult:
    """Total cost as % of net revenue, 7d vs 7d before: split by line -> product -> start day.
    Figures come from the analytics service (overview shop_profit net revenue + channel split
    costs)."""
    a1, b1 = w.cur
    a0, b0 = _drill_base(w)
    l1, l0 = await data.cost_lines_pair(a1, b1, a0, b0, item_id)
    c1, c0 = _cost(l1), _cost(l0)
    nr1, nr0 = l1.get("net_revenue"), l0.get("net_revenue")
    findings: list[Finding] = []
    head = Finding(
        "shop", COST_METRIC, None, None, evidence_ref="channel_split:kpis+overview:shop_profit"
    )
    findings.append(head)
    if c1 is None or c0 is None or not nr1 or not nr0:
        head.flags.append("cost_or_net_revenue_unknown")
        return ChainResult(
            chain,
            COST_METRIC,
            w,
            "data_missing",
            findings,
            steps + ["step1: cost / net revenue missing"],
        )
    head.now, head.before = c1 / nr1, c0 / nr0
    rel = (head.now - head.before) / head.before if head.before else None
    steps.append(f"step1: cost / net revenue {head.before:.4f} -> {head.now:.4f}")
    if head.now == head.before or (rel is not None and abs(rel) < MIN_CHANGE):
        head.flags.append(f"change_below_{MIN_CHANGE:.0%}")
        return ChainResult(
            chain, COST_METRIC, w, "within_noise", findings, steps + ["stop: within_noise (< 3 %)"]
        )
    explained: list[float] = []
    d_cost = c1 - c0
    # formula: ln(ratio1/ratio0) = ln(cost1/cost0) - ln(nr1/nr0)
    if c1 > 0 and c0 > 0 and nr1 > 0 and nr0 > 0:
        lc, ln_ = math.log(c1 / c0), -math.log(nr1 / nr0)
        tot = lc + ln_
        if tot:
            findings.append(
                Finding(
                    "formula", "cost_total", c1, c0, 100 * lc / tot, evidence_ref="lmdi:cost_ratio"
                )
            )
            findings.append(
                Finding(
                    "formula",
                    "net_revenue",
                    nr1,
                    nr0,
                    100 * ln_ / tot,
                    evidence_ref="lmdi:cost_ratio",
                )
            )
    # scope 1: by cost line (ads, affiliate; offers is its own line)
    line_d: dict[str, float] = {}
    for k in ("cost_ads", "cost_affiliate"):
        if l1.get(k) is not None and l0.get(k) is not None:
            line_d[k] = float(l1[k]) - float(l0[k])
    for k, d in sorted(line_d.items(), key=lambda kv: -abs(kv[1])):
        if d_cost and d * d_cost > 0 and abs(d / d_cost) >= FOLLOW_SHARE:  # same direction only
            findings.append(
                Finding(
                    "line",
                    k,
                    float(l1[k]),
                    float(l0[k]),
                    100 * d / d_cost,
                    evidence_ref=f"channel_split:{k}",
                )
            )
    same = [d for d in line_d.values() if d_cost and d * d_cost > 0]
    if same and d_cost:
        explained.append(max(same, key=abs) / d_cost)
    if l1.get("cost_offers") is not None and l0.get("cost_offers") is not None:
        findings.append(
            Finding(
                "line",
                "cost_offers",
                float(l1["cost_offers"]),
                float(l0["cost_offers"]),
                None,
                flags=["own_line"],
                evidence_ref="channel_split:cost_offers",
            )
        )
    for k in ("cost_ads", "cost_affiliate"):
        if (l1.get(k) is None) != (l0.get(k) is None):
            findings.append(
                Finding("line", k, l1.get(k), l0.get(k), None, flags=["no_data_in_one_window"])
            )
    steps.append("step2 lines: " + ", ".join(f"{k} {d:+.0f}" for k, d in line_d.items()))
    # scope 2: product (top sellers; the line figures per product come from the same channel split)
    if not item_id:
        prow = await data.product_daily(a1, b1)
        gmv: dict[str, float] = {}
        for r in prow:
            gmv[r["item_id"]] = gmv.get(r["item_id"], 0.0) + float(r["gmv"] or 0)
        top = [k for k, _ in sorted(gmv.items(), key=lambda kv: -kv[1])[:5]]
        pd: dict[str, tuple[float, float]] = {}
        for k in top:
            p1, p0 = await data.cost_lines_pair(a1, b1, a0, b0, k)
            q1, q0 = _cost(p1), _cost(p0)
            if q1 is not None and q0 is not None:
                pd[k] = (q1, q0)
        pn = await data.item_names(list(pd))
        for k, (q1, q0) in sorted(pd.items(), key=lambda kv: -abs(kv[1][0] - kv[1][1])):
            if d_cost and (q1 - q0) * d_cost > 0 and abs((q1 - q0) / d_cost) >= FOLLOW_SHARE:
                findings.append(
                    Finding(
                        "product",
                        pn.get(k, k),
                        q1,
                        q0,
                        100 * (q1 - q0) / d_cost,
                        evidence_ref=f"product:{k}",
                    )
                )
        fol = [
            q1 - q0
            for q1, q0 in pd.values()
            if d_cost and (q1 - q0) * d_cost > 0 and abs((q1 - q0) / d_cost) >= FOLLOW_SHARE
        ][:TOP_N]
        if fol and d_cost:
            explained.append(sum(fol) / d_cost)
    # time: start day of the ads spend shift
    series = [
        (r["day"], float(r["ads_spend"]))
        for r in rows
        if a0 <= r["day"] <= b1 and r.get("ads_spend") is not None
    ]
    cp = mathx.change_point(series) if len(series) >= 6 else None
    if cp and cp >= a1:
        findings.append(Finding("time", "change_point", None, None, flags=[f"start_day:{cp}"]))
    share = min(1.0, max(explained)) if explained else None
    stop = "explained" if share is not None and share >= EXPLAINED_SHARE else "unexplained"
    res = ChainResult(chain, COST_METRIC, w, stop, findings, steps, share)
    if stop == "unexplained" and fallback:
        await _bottom_up(data, res, rows, "gmv", (a1, b1), 0.0)
    steps.append(f"stop: {res.stop_reason}")
    return res


__all__ = ["ChainResult", "Finding", "run_chain", "metric_value", "noise_band", "SHOPEE_SOURCES"]
