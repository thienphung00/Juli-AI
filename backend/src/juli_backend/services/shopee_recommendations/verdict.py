"""F10 Đo lường: the verdict, the forecast check and the calibration gate of one measured card.

Pure: no DB. :mod:`.measure` supplies the readings (``impact.Reading``), the daily history and the
card's frozen result; this module turns them into the card's measurement block.

- **Window (G12)**: the card's run days (the days it ran, from its verified start), against the
  same number of days before. :func:`run_window` names both. ``impact.read_effect`` still reads
  ``impact.PRE_DAYS`` days before; the pre dates in the block say what was read.
- **Verdict**: Tăng / Không đổi / Giảm. "Không đổi" = the measured change is inside the product's
  F3 period band (``forecast.noise.period_band`` over the run length). Judged on Δ lợi nhuận where
  the card's frozen result has a profit (Δ GMV x the result's profit per GMV), else on Δ GMV (G16);
  a card with no estimate and a non-GMV target is judged on the change of its own metric (G15).
- **Forecast check**: Dự kiến = the P50 frozen at proposal, Thực tế = the measured figure on the
  same basis; "Đúng dự báo" = Thực tế inside the frozen P10-P90 (internal, never shown).
- **Calibration gate**: only tier cao / trung_binh, measured on fresh data, feed calibration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from juli_backend.services.forecast import noise
from juli_backend.services.shopee_analytics import forecast_base
from juli_backend.services.shopee_recommendations import impact, result_store

UP, FLAT, DOWN = "tang", "khong_doi", "giam"
LABELS = {UP: "Tăng", FLAT: "Không đổi", DOWN: "Giảm"}
BASIS_PROFIT, BASIS_GMV, BASIS_METRIC = "profit", "gmv", "metric"
#: tiers whose results may calibrate (F10); thap / suppressed are shown, never used
CALIBRATING_TIERS = frozenset({"cao", "trung_binh"})
#: the history (days before the start) the F3 band is read from (the longest F2 window)
HISTORY_DAYS = 60
#: metrics whose measured change can be expressed in money (the GMV reading is the card's own)
GMV_METRICS = frozenset({"gmv", "ads_gmv"})


def run_days(card: Mapping[str, Any], fallback: int | None) -> int | None:
    """G12: the card's run length = the days its frozen result is for (``own.days``), else the
    fallback (the change set's / measurement plan's days)."""
    block = result_store.measured_block(card)
    own_days = ((block or {}).get("own") or {}).get("days")
    if isinstance(own_days, int) and own_days > 0:
        return own_days
    return fallback


def run_window(t: date, days: int) -> dict[str, Any]:
    """The measured days: the run (``t`` + 1 .. ``t`` + days) and the days before it."""
    pre = min(days, impact.PRE_DAYS)
    return {
        "days": days,
        "from": (t + timedelta(days=1)).isoformat(),
        "to": (t + timedelta(days=days)).isoformat(),
        "pre_from": (t - timedelta(days=impact.PRE_DAYS)).isoformat(),
        "pre_to": (t - timedelta(days=1)).isoformat(),
        "pre_days": max(pre, impact.PRE_DAYS),
        "label": f"Chạy và đo {days} ngày",
    }


def verdict_of(change: float | None, half_width: float | None) -> str | None:
    """Tăng / Không đổi / Giảm: ``change`` inside ``+-half_width`` (same unit) is "Không đổi"."""
    if change is None:
        return None
    if half_width is not None and abs(change) <= half_width:
        return FLAT
    return UP if change > 0 else DOWN


def stale_run(
    last_orders: date | None, last_traffic: date | None, run_end: date, uses_traffic: bool = True
) -> bool:
    """F2: the data stopped during the run -- the newest day of a dataset is older than its
    expected lag + grace days before the run's last day (no data at all counts as stale)."""
    checks = [("orders", last_orders)]
    if uses_traffic:
        checks.append(("traffic", last_traffic))
    for dataset, through in checks:
        if through is None:
            return True
        limit = (
            forecast_base.EXPECTED_LAG_DAYS[("shopee", dataset)] + forecast_base.STALE_GRACE_DAYS
        )
        if (run_end - through).days > limit:
            return True
    return False


def calibration_skip(confidence: str | None, stale: bool) -> str | None:
    """Why a result does NOT feed calibration (``None`` = it does): lowest tier, or stale data."""
    if confidence not in CALIBRATING_TIERS:
        return "lowest_tier"
    if stale:
        return "stale_run"
    return None


def _scaled(block: Mapping[str, Any] | None, metric: str, days: int) -> dict[str, float | None]:
    """The frozen own-days delta of ``metric`` ({p10, p50, p90}) spread to ``days``."""
    own = (block or {}).get("own") or {}
    d = (own.get("delta") or {}).get(metric) or {}
    own_days = own.get("days")
    k = None if not own_days else days / int(own_days)

    def at(q: str) -> float | None:
        v = d.get(q)
        return None if v is None or k is None else float(v) * k

    return {q: at(q) for q in ("p10", "p50", "p90")}


def _profit_per_gmv(block: Mapping[str, Any] | None) -> float | None:
    """The frozen result's profit per đồng of GMV (P50 over P50); None when it has no profit."""
    own = (block or {}).get("own") or {}
    d = own.get("delta") or {}
    p, g = (d.get("profit") or {}).get("p50"), (d.get("gmv") or {}).get("p50")
    if p is None or g in (None, 0):
        return None
    return float(p) / float(g)


def _check(expected: Mapping[str, float | None], actual: float | None) -> bool | None:
    lo, hi = expected.get("p10"), expected.get("p90")
    if actual is None or lo is None or hi is None:
        return None
    a, b = sorted((float(lo), float(hi)))
    return a <= actual <= b


def _diff(actual: float | None, expected: float | None) -> float | None:
    return None if actual is None or expected is None else actual - expected


def measurement(
    *,
    metric: str,
    reading: impact.Reading,
    gmv_reading: impact.Reading | None,
    block: Mapping[str, Any] | None,
    days: int,
    t: date,
    history: Sequence[float | None],
    gmv_history: Sequence[float | None],
    stale: bool = False,
    partial: bool = False,
) -> dict[str, Any]:
    """The card's measured result for the UI (see the module docstring).

    ``gmv_reading`` is the reading of the card's GMV (``None`` when the metric has none: ROAS);
    ``history`` / ``gmv_history`` the daily values before the start (the F3 band). Fields:
    ``verdict`` / ``verdict_label``, ``basis``, ``expected`` (Dự kiến, P50), ``actual`` (Thực tế),
    ``difference``, ``forecast_ok`` (internal), ``confidence``, ``calibrates``, ``window``,
    ``metric_change_pct``, ``band_pct`` and ``within_band``."""
    estimable = bool(block and block.get("estimable"))
    gmv_read = reading if metric in GMV_METRICS else gmv_reading
    ratio = _profit_per_gmv(block) if estimable else None
    out: dict[str, Any] = {
        "metric": metric,
        "window": run_window(t, days),
        "confidence": reading.confidence,
        "reason": reading.reason,
        "partial": partial,
        "estimated": estimable,
        "metric_change_pct": None if reading.impact_pct is None else reading.impact_pct * 100.0,
    }
    basis, actual, expected, half = BASIS_METRIC, None, {}, None
    band_pct: float | None = None
    judged_conf = reading.confidence
    if (
        gmv_read is not None
        and gmv_read.incremental is not None
        and gmv_read.confidence != "suppressed"
    ):
        band = noise.period_band(gmv_history, days)
        band_pct = band.band_pct
        pre = gmv_read.pre or 0.0
        half_gmv = max((band.p90 - band.p10) / 2, abs(pre) * days * noise.MIN_PCT)
        gmv_total = gmv_read.incremental * days
        if ratio is not None:
            basis, actual, half = BASIS_PROFIT, gmv_total * ratio, half_gmv * abs(ratio)
            expected = _scaled(block, "profit", days)
        else:
            basis, actual, half = BASIS_GMV, gmv_total, half_gmv
            expected = _scaled(block, "gmv", days)
        judged_conf = gmv_read.confidence
    elif reading.impact_pct is not None and reading.confidence != "suppressed":
        band = noise.period_band(history, days)
        band_pct = band.band_pct
        half = max(band_pct or 0.0, noise.MIN_PCT * 100.0) / 100.0
        actual = reading.impact_pct
        mb = result_store.metric_band(block, metric) if estimable else None
        expected = {} if mb is None else dict(mb)
    verdict = verdict_of(actual, half)
    exp50 = expected.get("p50") if expected else None
    out.update(
        verdict=verdict,
        verdict_label=None if verdict is None else LABELS[verdict],
        basis=basis if actual is not None else None,
        expected=exp50,
        expected_label="Dự kiến",
        actual=actual,
        actual_label="Thực tế",
        difference=_diff(actual, exp50),
        forecast_ok=_check(expected, actual) if expected else None,
        band_pct=band_pct,
        within_band=None if verdict is None else verdict == FLAT,
        judged_confidence=judged_conf,
    )
    skip = calibration_skip(reading.confidence, stale)
    out["calibrates"] = skip is None and not partial
    out["calibration_skip"] = "partial" if partial and skip is None else skip
    out["stale"] = stale
    return out


def ads_row(
    key: str, label: str, expected: float | None, actual: float | None, unit: str
) -> dict[str, Any]:
    """One real-vs-predicted row of an Ads card: an unread real value is None, never 0 (T16)."""
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "expected": expected,
        "actual": actual,
        "difference": _diff(actual, expected),
    }


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def ads_rows(
    block: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """G18 / G19: the new campaign's real spend / GMV / orders / ROAS / CPA against the frozen
    prediction (cost, CPA, CPA hoà vốn from the result's ``ads`` lines), ``actual`` = the output
    of ``ads_readback.read_actual``. Break-even CPA has no real counterpart (shown as the
    reference); ``cpa_verdict`` says whether the real CPA is under it."""
    ads = ((block or {}).get("option") or {}).get("ads") or {}
    cost = (block or {}).get("cost_total")
    spend_x = _num((ads.get("spend") or {}).get("after")) if ads else None
    if spend_x is None:
        spend_x = _num(cost)
    orders_x = _num((ads.get("orders") or {}).get("after"))
    cpa_x = _num((ads.get("cpa") or {}).get("after"))
    roas_x = _num((ads.get("roas_shopee") or {}).get("after"))
    gmv_x = None if roas_x is None or spend_x is None else roas_x * spend_x
    be = _num(ads.get("break_even_cpa"))
    a = actual or {}
    spend, gmv, orders = _num(a.get("spend")), _num(a.get("gmv")), _num(a.get("orders"))
    cpa = None if spend is None or not orders else spend / orders
    rows = [
        ads_row("spend", "Chi phí quảng cáo", spend_x, spend, "vnd"),
        ads_row("gmv", "GMV", gmv_x, gmv, "vnd"),
        ads_row("orders", "Đơn", orders_x, orders, "count"),
        ads_row("roas", "ROAS", roas_x, _num(a.get("roas")), "ratio"),
        ads_row("cpa", "CPA", cpa_x, cpa, "vnd"),
        ads_row("cpa_break_even", "CPA hoà vốn", be, None, "vnd"),
    ]
    rows[-1]["verdict"] = None if cpa is None or be is None else (UP if cpa < be else DOWN)
    return rows


def campaign_rows(
    block: Mapping[str, Any] | None,
    pre: Mapping[str, float],
    post: Mapping[str, float],
    days: int,
) -> list[dict[str, Any]]:
    """An edit of a running campaign, measured on campaign spend, GMV, orders and CPA (G18):
    ``pre`` / ``post`` are the per-day means (spend, gmv, orders) before and in the run; the
    run's totals are ``post x days``. Expected = the frozen ads lines (the option's "after")."""
    ads = ((block or {}).get("option") or {}).get("ads") or {}
    exp = {
        "spend": _num((ads.get("spend") or {}).get("after")),
        "orders": _num((ads.get("orders") or {}).get("after")),
        "cpa": _num((ads.get("cpa") or {}).get("after")),
    }
    spend, gmv, orders = (post.get(k) for k in ("spend", "gmv", "orders"))
    tot = {
        k: None if v is None else v * days
        for k, v in (("spend", spend), ("gmv", gmv), ("orders", orders))
    }
    cpa = None if not tot["spend"] or not tot["orders"] else tot["spend"] / tot["orders"]
    cpa_before = None if not pre.get("orders") else pre.get("spend", 0.0) / pre["orders"]
    rows = [
        ads_row("spend", "Chi phí quảng cáo", exp["spend"], tot["spend"], "vnd"),
        ads_row("gmv", "GMV", None, tot["gmv"], "vnd"),
        ads_row("orders", "Đơn", exp["orders"], tot["orders"], "count"),
        ads_row("cpa", "CPA", exp["cpa"], cpa, "vnd"),
    ]
    rows[0]["before"] = None if "spend" not in pre else pre["spend"] * days
    rows[1]["before"] = None if "gmv" not in pre else pre["gmv"] * days
    rows[2]["before"] = None if "orders" not in pre else pre["orders"] * days
    rows[3]["before"] = cpa_before
    return rows
