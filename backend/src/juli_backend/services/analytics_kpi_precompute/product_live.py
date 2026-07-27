"""Pure KPI envelope builders for product funnel and LIVE precompute (#527)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from juli_backend.models.models import AnalyticsPerformanceInterval

Availability = Literal["available", "unavailable"]

_PRODUCT_FUNNEL_LABEL = "Product funnel (GMV)"


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
