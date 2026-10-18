"""Re-score a pre-D29 pending card in place with the D29 KPI (P23 follow-up). Pure.

A card written before P23 carries only the ADR-106 numbers: a target equal to
the shop median (or the product's own prior), no band, no confidence, no
window -- e.g. "CTR 3,22 % → 4,57 % ▲ 41,9 %" where D29.7 caps the target at
current + 3 × band. The emission ladder rewrites a card only when its
(product, lever) is proposed again with an unchanged diagnosis, so such a card
kept its old payload until it expired.

:func:`rescore_legacy_payload` keeps the card's own offer (product, lever,
target metric = its stage's metric) and replaces its numbers with D29's:

- the metric's adaptive window (D29.1) and window-mean band;
- KPI = the higher of the card's old reference and the product's own earlier
  level (D29.3), clamped to [current + min × band, current + max × band] (D29.7),
  a range when the product is volatile (D29.10);
- "Độ tin cậy" (D29.6) and the GMV range per month (D30.3);
- D32: all of it on the channel the card's lever acts on (``kpi_channel``),
  all channels when that channel is thin; on a channel the card's old
  reference (an all-channel shop median) is not comparable and is dropped.

``None`` when the card already has a D29 ``kpi`` or the KPI cannot be
recomputed (no daily rows, no band): the card is then shown as before, and the
read model caps its target (:func:`cap_legacy_target`).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.kpi_channel import channel_gmv_per_day, kpi_window
from juli_backend.services.optimize_product.prediction import gmv_range_per_month
from juli_backend.services.optimize_product.tunables import DiagTunables
from juli_backend.services.optimize_product.volatility import (
    METRICS,
    assess_product,
    confidence,
    kpi_target,
    select_window,
    stability,
    window_counts,
)

#: Pre-D29 stage code -> the metric it targeted.
STAGE_METRIC: Mapping[str, str] = {"card": "ctr", "page": "ctor", "basket": "aov"}

#: The band assumed for a pending card whose band cannot be computed (no daily
#: rows): its target is shown at most ``kpi_max_band_mult`` (3) × this above the
#: current value, i.e. +30 % by default -- never the uncapped shop median.
FALLBACK_BAND_PCT = 10.0

#: Payload marker: the as-of day the card was re-scored with D29 numbers.
RESCORED_KEY = "rescored_d29_as_of"


def has_d29_kpi(payload: Mapping[str, Any]) -> bool:
    return isinstance(payload.get("kpi"), Mapping)


def legacy_metric(payload: Mapping[str, Any]) -> str | None:
    """The metric a stored card is about: ``target_metric``, else its basis or stage."""
    metric = payload.get("target_metric")
    if isinstance(metric, str) and metric in METRICS:
        return metric
    diagnosis = payload.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        return None
    basis = diagnosis.get("recoverable_gmv_basis")
    if isinstance(basis, Mapping) and basis.get("stage_rate") in METRICS:
        return str(basis["stage_rate"])
    stage = diagnosis.get("stage")
    code = stage.get("code") if isinstance(stage, Mapping) else None
    return STAGE_METRIC.get(str(code)) if code else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _impact_sentence(value: float) -> str:
    vnd = f"{round(value):,}".replace(",", ".")
    return f"Có thể lấy lại khoảng {vnd} ₫ GMV mỗi ngày (ước tính)"


def rescore_legacy_payload(
    payload: Mapping[str, Any],
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    tunables: DiagTunables,
) -> dict[str, Any] | None:
    """The card payload with D29 numbers, or ``None`` (already D29 / not computable)."""
    if has_d29_kpi(payload):
        return None
    diagnosis = payload.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        return None
    metric = legacy_metric(payload)
    if metric is None or not rows:
        return None
    lever = diagnosis.get("lever")
    lever_code = lever.get("code") if isinstance(lever, Mapping) else None
    kw = kpi_window(
        rows,
        as_of=as_of,
        metric=metric,
        lever=str(lever_code) if lever_code else None,
        tunables=tunables,
        total=select_window(rows, as_of, metric, tunables),
    )
    window = kw.window
    current = window.value
    if current is None or current <= 0 or window.band_pct is None:
        return None
    basis = diagnosis.get("recoverable_gmv_basis")
    basis = basis if isinstance(basis, Mapping) else {}
    old_reference = None if kw.per_channel else _num(basis.get("reference_rate"))
    options = [
        (value, source)
        for value, source in (
            (old_reference, str(basis.get("reference") or "shop_median")),
            (window.earlier, "own_earlier"),
        )
        if value is not None and value > 0
    ]
    reference, source = max(options, key=lambda o: o[0]) if options else (current, "current")
    assessment = assess_product(
        str(diagnosis.get("tiktok_product_id") or ""), rows, as_of=as_of, tunables=tunables
    )
    cv = kw.impressions_cv(as_of) if kw.per_channel else assessment.impressions_cv
    volatile = (
        stability(cv, tunables) == "volatile"
        if kw.per_channel
        else assessment.stability == "volatile"
    )
    kpi = kpi_target(
        metric=metric,
        current=current,
        band_pct=window.band_pct,
        reference=reference,
        window_days=window.window_days,
        tunables=tunables,
        volatile=volatile,
        low_data=window.low_data,
        channel=kw.channel,
    )
    level = confidence(
        events=window.events,
        cv=cv,
        low_data=window.low_data,
        tunables=tunables,
    )
    gmv_day = window_counts(rows, as_of, window.window_days).value("gmv") or 0.0
    if kw.per_channel:
        channel_gmv = channel_gmv_per_day(rows, kw.channel, as_of, window.window_days)
        gmv_day = channel_gmv if channel_gmv is not None else gmv_day
    low, high = gmv_range_per_month(gmv_day, current, kpi.target_min, kpi.target_max)
    recoverable = gmv_day * max(kpi.target / current - 1, 0.0)

    out: dict[str, Any] = copy.deepcopy(dict(payload))
    new_diagnosis = out["diagnosis"]
    new_basis = dict(basis)
    new_basis.update(
        {
            "stage_rate": metric,
            "current_rate": current,
            "reference_rate": kpi.target,
            "reference": source,
            "window_days": window.window_days,
            "channel": kw.channel,
        }
    )
    new_diagnosis["recoverable_gmv_basis"] = new_basis
    new_diagnosis["recoverable_gmv_per_day"] = recoverable
    new_diagnosis["volatility"] = assessment.to_json()
    new_diagnosis[RESCORED_KEY] = as_of.isoformat()
    if isinstance(out.get("expected_impact"), dict):
        out["expected_impact"]["value"] = recoverable
    if isinstance(out.get("reasoning"), dict) and out["reasoning"].get("expected_impact"):
        out["reasoning"]["expected_impact"] = _impact_sentence(recoverable)
    out.update(
        {
            "target_metric": metric,
            "confidence": level,
            "kpi": {
                "metric": kpi.metric,
                "current": kpi.current,
                "target": kpi.target,
                "target_min": kpi.target_min,
                "target_max": kpi.target_max,
                "display": kpi.display,
                "band_pct": round(kpi.band_pct, 2),
                "window_days": kpi.window_days,
                "low_data": kpi.low_data,
                "day14_only": kpi.day14_only,
                "channel": kpi.channel,
            },
            "gmv_estimate": {
                "per_month_min": float(round(low)),
                "per_month_max": float(round(high)),
            },
            "sibling_cards": int(out.get("sibling_cards") or 0),
        }
    )
    return out


def cap_legacy_target(
    current: float | None,
    target: float | None,
    *,
    tunables: DiagTunables | None = None,
) -> float | None:
    """A pre-D29 target capped at current × (1 + max_mult × :data:`FALLBACK_BAND_PCT`)."""
    if current is None or target is None or current <= 0:
        return target
    mult = (tunables or DiagTunables()).kpi_max_band_mult
    ceiling = current * (1 + mult * FALLBACK_BAND_PCT / 100)
    return min(target, ceiling)


__all__ = [
    "FALLBACK_BAND_PCT",
    "RESCORED_KEY",
    "STAGE_METRIC",
    "cap_legacy_target",
    "has_d29_kpi",
    "legacy_metric",
    "rescore_legacy_payload",
]
