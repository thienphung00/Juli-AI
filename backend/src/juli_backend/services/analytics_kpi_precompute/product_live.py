"""Pure KPI envelope builders for product funnel and LIVE precompute (#527)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from juli_backend.models.models import AnalyticsPerformanceInterval

Availability = Literal["available", "unavailable"]

_PRODUCT_FUNNEL_LABEL = "Product funnel (GMV)"
_LIVE_LABEL_BY_METRIC = {
    "gmv": "LIVE performance (GMV)",
    "live_hours": "LIVE performance (live hours)",
    "live_sessions": "LIVE performance (live sessions)",
}


@dataclass(frozen=True)
class KpiEnvelopeEntry:
    availability: Availability
    label: str
    series: list[dict[str, Any]]


def build_product_funnel_kpi(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    metric: Literal["gmv"] = "gmv",
) -> KpiEnvelopeEntry:
    """Sum product-grain GMV by start_date (A-34)."""
    del metric  # single supported metric in wave 2

    totals: dict[Any, Decimal] = {}
    for row in intervals:
        if row.grain != "product":
            continue
        if row.gmv is None:
            continue
        totals[row.start_date] = totals.get(row.start_date, Decimal("0")) + row.gmv

    if not totals:
        return KpiEnvelopeEntry(
            availability="unavailable",
            label=_PRODUCT_FUNNEL_LABEL,
            series=[],
        )

    series = [{"t": day.isoformat(), "v": float(value)} for day, value in sorted(totals.items())]
    return KpiEnvelopeEntry(
        availability="available",
        label=_PRODUCT_FUNNEL_LABEL,
        series=series,
    )


def _is_live_marked_row(row: AnalyticsPerformanceInterval) -> bool:
    """True when row has LIVE partition markers (not revenue-only A-36)."""
    return (
        row.live_hours is not None
        or row.live_sessions is not None
        or row.click_through_rate is not None
    )


def _live_metric_value(
    row: AnalyticsPerformanceInterval,
    metric: Literal["gmv", "live_hours", "live_sessions"],
) -> Decimal | int | None:
    if metric == "gmv":
        return row.gmv
    if metric == "live_hours":
        return row.live_hours
    return row.live_sessions


def build_live_performance_kpi(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    metric: Literal["gmv", "live_hours", "live_sessions"] = "gmv",
) -> KpiEnvelopeEntry:
    """Shop-grain LIVE rollup rows only (A-28/A-29)."""
    label = _LIVE_LABEL_BY_METRIC[metric]
    totals: dict[Any, Decimal] = {}

    for row in intervals:
        if row.grain != "shop" or not _is_live_marked_row(row):
            continue
        value = _live_metric_value(row, metric)
        if value is None:
            continue
        totals[row.start_date] = totals.get(row.start_date, Decimal("0")) + Decimal(value)

    if not totals:
        return KpiEnvelopeEntry(
            availability="unavailable",
            label=label,
            series=[],
        )

    series = [{"t": day.isoformat(), "v": float(value)} for day, value in sorted(totals.items())]
    return KpiEnvelopeEntry(
        availability="available",
        label=label,
        series=series,
    )
