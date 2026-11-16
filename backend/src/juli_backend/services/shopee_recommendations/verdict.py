"""F10 Đo lường, the Shopee side: what ``card_measure`` does not know.

The effect, window, verdict (Tăng / Không đổi / Giảm inside the F3 band), forecast check and
calibration gate are ``services.card_measure.reader.measure`` (one model for both platforms).
This module adds the Shopee-only parts, pure and DB free:

- **G12** :func:`run_days`: the card's run length = the days its frozen result is for.
- **G16** the verdict basis: Δ lợi nhuận where the card's frozen result has a profit (the GMV
  reading x the result's profit per GMV; the sign and the band are those of GMV), else ΔGMV.
- **G15** a card with no estimate (or a non-GMV target) still gets its verdict on its own metric.
- **Forecast check**: Dự kiến = the P50 frozen at proposal, Thực tế on the same basis; "Đúng
  dự báo" inside the frozen P10-P90 (internal, never shown).
- **G18 / G19** :func:`ads_rows` / :func:`campaign_rows`: real spend / GMV / orders / ROAS / CPA
  against the predicted cost, CPA and CPA hoà vốn.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from juli_backend.services.card_measure import reader
from juli_backend.services.shopee_recommendations import result_store

# literals, not reader.VERDICT_*: card_measure.reader imports shopee_recommendations (impact),
# whose package import reaches this module while reader is still half-initialised
UP, FLAT, DOWN = "tang", "khong_doi", "giam"
BASIS_PROFIT, BASIS_GMV, BASIS_METRIC = "profit", "gmv", "metric"
#: metrics whose measured change is already money (the GMV reading is the card's own)
GMV_METRICS = frozenset({"gmv", "ads_gmv"})
#: the shortest "before" window the reader accepts (impact.read_effect needs 7 days)
MIN_PRE_DAYS = 7


def run_days(card: Mapping[str, Any], fallback: int | None) -> int | None:
    """G12: the card's run length = the days its frozen result is for (``own.days``), else the
    fallback (the change set's / measurement plan's days)."""
    block = result_store.measured_block(card)
    own_days = ((block or {}).get("own") or {}).get("days")
    if isinstance(own_days, int) and own_days > 0:
        return own_days
    return fallback


def pre_days_for(days: int) -> int:
    """The "before" window: the same number of days as the run (at least 7)."""
    return max(days, MIN_PRE_DAYS)


def run_window(t: date, days: int) -> dict[str, Any]:
    """The measured days: the run (``t`` + 1 .. ``t`` + days) and the days before it."""
    pre = pre_days_for(days)
    return {
        "days": days,
        "from": (t + timedelta(days=1)).isoformat(),
        "to": (t + timedelta(days=days)).isoformat(),
        "pre_from": (t - timedelta(days=pre)).isoformat(),
        "pre_to": (t - timedelta(days=1)).isoformat(),
        "pre_days": pre,
        "label": f"Chạy và đo {days} ngày",
    }


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


def profit_per_gmv(block: Mapping[str, Any] | None) -> float | None:
    """The frozen result's profit per đồng of GMV (P50 over P50); None when it has no profit or
    it is not positive (a loss-making card is judged on GMV)."""
    own = (block or {}).get("own") or {}
    d = own.get("delta") or {}
    p, g = (d.get("profit") or {}).get("p50"), (d.get("gmv") or {}).get("p50")
    if p is None or g in (None, 0):
        return None
    ratio = float(p) / float(g)
    return ratio if ratio > 0 else None


def _check(expected: Mapping[str, float | None], actual: float | None) -> bool | None:
    return reader.forecast_hit(
        actual, reader.Forecast(expected.get("p50"), expected.get("p10"), expected.get("p90"))
    )


def _usable(m: reader.Measurement | None) -> bool:
    return (
        m is not None and m.reading.incremental is not None and m.reading.confidence != "suppressed"
    )


def payload(
    m: reader.Measurement,
    gmv_m: reader.Measurement | None,
    *,
    block: Mapping[str, Any] | None,
    days: int,
    t: date,
    partial: bool = False,
) -> dict[str, Any]:
    """The card's measured result for the UI. ``m`` = the reading of the card's own metric (it
    calibrates), ``gmv_m`` = the card's GMV reading (``None`` when it has none: ROAS). Fields:
    ``verdict`` / ``verdict_label``, ``basis``, ``expected`` (Dự kiến, P50), ``actual`` (Thực
    tế), ``difference``, ``forecast_ok`` (internal), ``confidence``, ``calibrates``,
    ``calibration_skip``, ``window``, ``metric_change_pct``, ``band_pct``, ``within_band``."""
    estimable = bool(block and block.get("estimable"))
    gm = m if m.metric in GMV_METRICS else gmv_m
    ratio = profit_per_gmv(block) if estimable else None
    basis, actual, expected = BASIS_METRIC, None, {}
    judged = m
    if gm is not None and _usable(gm):
        judged = gm
        assert gm.reading.incremental is not None
        if ratio is not None:
            basis, actual = BASIS_PROFIT, gm.reading.incremental * days * ratio
            expected = _scaled(block, "profit", days)
        else:
            basis, actual = BASIS_GMV, gm.reading.incremental * days
            expected = _scaled(block, "gmv", days)
    elif m.reading.impact_pct is not None and m.reading.confidence != "suppressed":
        actual = m.reading.impact_pct
        mb = result_store.metric_band(block, m.metric) if estimable else None
        expected = {} if mb is None else dict(mb)
    verdict = judged.verdict
    exp50 = expected.get("p50") if expected else None
    skip: str | None = None
    if partial:
        skip = "partial"
    elif m.reading.confidence not in reader.CALIBRATING_TIERS:
        skip = "lowest_tier"
    elif not m.fresh:
        skip = "stale_run"
    return {
        **m.to_json(),
        "window": run_window(t, days),
        "partial": partial,
        "estimated": estimable,
        "metric_change_pct": None if m.reading.impact_pct is None else m.reading.impact_pct * 100,
        "verdict": verdict,
        "verdict_label": None if verdict is None else reader.VERDICT_VI[verdict],
        "basis": basis if actual is not None else None,
        "expected": exp50,
        "expected_label": "Dự kiến",
        "actual": actual,
        "actual_label": "Thực tế",
        "difference": None if actual is None or exp50 is None else actual - exp50,
        "forecast_ok": _check(expected, actual) if expected else None,
        "within_band": None if verdict is None else verdict == FLAT,
        "judged_confidence": judged.reading.confidence,
        "band_pct": judged.band_pct,
        "calibrates": skip is None,
        "calibration_skip": skip,
        "stale": not m.fresh,
    }


def _diff(actual: float | None, expected: float | None) -> float | None:
    return None if actual is None or expected is None else actual - expected


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
