"""Funnel-first target-metric map — ADR-077 decision 1 (#1041).

Which daily metric a mutation is judged against is **data**, not branching logic:
a mutation touches the point in the funnel it can plausibly move, so that is the
metric the DiD compute in :mod:`juli_backend.services.impact.compute` reads.
Every column referenced here already exists on
``analytics_performance_intervals`` (``AnalyticsPerformanceInterval`` in
``models.py``), daily grain, per product — this module never touches that ORM
model or issues a query; it only names which of its columns matter per
mutation kind.

- SEO keywords / title: primary ``impressions`` (total-traffic proxy for
  visibility — honest limitation: search traffic is not separable from
  other traffic sources in this data), secondary ``ctr``.
- Description: primary ``conversion_rate``, secondary ``items_sold``.
- Image: primary ``ctr``, secondary ``conversion_rate``.
- Price: primary ``gmv``, secondary ``sku_orders`` and ``gmv_per_order``
  (``gmv`` ÷ ``sku_orders``, derived — not a raw column).

A multi-mutation run (e.g. a single Optimize Product run that both rewrites the
title and updates the price) produces one reading per (mutation, metric) pair
**plus** one run-level rollup reading keyed on the ActionCard's
``expected_impact.metric`` — see
:func:`juli_backend.services.impact.reading.compute_run_readings`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class MutationKind(str, Enum):
    """The four mutation kinds ADR-077 decision 1 maps to target metrics.

    Named after the seller-facing change, not the underlying agent tool —
    ``update_product_listing`` (services/agent/tools/product_write.py) can
    carry a title/description change, an image change, or both in one call;
    the caller (the future daily impact-reader beat task, #1044) is
    responsible for deciding which ``MutationKind`` value(s) a given
    ``ToolExecution`` maps to. This module only owns the kind → metric
    mapping, not that classification.
    """

    SEO_KEYWORDS_TITLE = "seo_keywords_title"
    DESCRIPTION = "description"
    IMAGE = "image"
    PRICE = "price"


@dataclass(frozen=True, slots=True)
class RawDailyRecord:
    """One product's one day of ``analytics_performance_intervals`` columns,
    normalized to ``Decimal`` (including the integer-typed columns —
    ``impressions``, ``items_sold``, ``sku_orders`` — so every metric series
    handled by this package is uniformly ``Mapping[date, Decimal | None]``).

    Building these from real ORM rows is deliberately out of this module's
    scope (no I/O in the compute path) — the caller reads
    ``AnalyticsPerformanceInterval`` rows and converts.
    """

    impressions: Decimal | None = None
    ctr: Decimal | None = None
    conversion_rate: Decimal | None = None
    items_sold: Decimal | None = None
    gmv: Decimal | None = None
    sku_orders: Decimal | None = None


def _extract_gmv_per_order(day: RawDailyRecord) -> Decimal | None:
    """``gmv`` ÷ ``sku_orders`` for one day. ``None`` (not zero) when either
    input is missing or ``sku_orders`` is zero — a day with zero orders has
    no defined average order value, it is not a zero one."""
    if day.gmv is None or day.sku_orders is None or day.sku_orders == 0:
        return None
    return day.gmv / day.sku_orders


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One target-metric definition: how to pull its daily value out of a
    ``RawDailyRecord``, and whether it is a *rate* metric.

    ``is_rate`` exists purely for documentation/introspection in this v1: per
    ADR-077 decision 2, rate metrics (``ctr``, ``conversion_rate``,
    ``gmv_per_order``) are averaged as the **arithmetic mean of daily rate
    values** — the same ``mean_over_window`` as count/currency metrics use.
    This is a documented, deliberate approximation: the mathematically
    correct treatment is a *pooled* rate (sum of numerator days ÷ sum of
    denominator days), which is not available in v1 because the raw daily
    click/visit counts behind ``ctr``/``conversion_rate`` are not stored —
    only the pre-computed ratio column is. The pooled-rate upgrade is
    recorded here as the named future work; this module does not silently
    approximate it as anything other than an arithmetic mean.
    """

    key: str
    label: str
    extractor: Callable[[RawDailyRecord], Decimal | None]
    is_rate: bool


IMPRESSIONS = MetricSpec(
    key="impressions",
    label="Impressions",
    extractor=lambda day: day.impressions,
    is_rate=False,
)
CTR = MetricSpec(
    key="ctr",
    label="Click-through rate",
    extractor=lambda day: day.ctr,
    is_rate=True,
)
CONVERSION_RATE = MetricSpec(
    key="conversion_rate",
    label="Conversion rate",
    extractor=lambda day: day.conversion_rate,
    is_rate=True,
)
ITEMS_SOLD = MetricSpec(
    key="items_sold",
    label="Items sold",
    extractor=lambda day: day.items_sold,
    is_rate=False,
)
GMV = MetricSpec(
    key="gmv",
    label="GMV",
    extractor=lambda day: day.gmv,
    is_rate=False,
)
SKU_ORDERS = MetricSpec(
    key="sku_orders",
    label="SKU orders",
    extractor=lambda day: day.sku_orders,
    is_rate=False,
)
GMV_PER_ORDER = MetricSpec(
    key="gmv_per_order",
    label="GMV per order",
    extractor=_extract_gmv_per_order,
    is_rate=True,
)

#: Every metric this package knows how to read, keyed by its column/derived
#: name — used to resolve the ActionCard's ``expected_impact.metric`` string
#: (an arbitrary metric key chosen by the scoring layer) for the run-level
#: rollup reading.
ALL_METRICS: dict[str, MetricSpec] = {
    spec.key: spec
    for spec in (IMPRESSIONS, CTR, CONVERSION_RATE, ITEMS_SOLD, GMV, SKU_ORDERS, GMV_PER_ORDER)
}


@dataclass(frozen=True, slots=True)
class MutationMetrics:
    """Primary + secondary metric specs for one mutation kind."""

    primary: MetricSpec
    secondary: tuple[MetricSpec, ...]


#: The metric map itself — data, not branching logic (ADR-077 decision 1 /
#: acceptance criterion). Covers all four mutation kinds with both a primary
#: and at least one secondary metric.
METRIC_MAP: dict[MutationKind, MutationMetrics] = {
    MutationKind.SEO_KEYWORDS_TITLE: MutationMetrics(primary=IMPRESSIONS, secondary=(CTR,)),
    MutationKind.DESCRIPTION: MutationMetrics(primary=CONVERSION_RATE, secondary=(ITEMS_SOLD,)),
    MutationKind.IMAGE: MutationMetrics(primary=CTR, secondary=(CONVERSION_RATE,)),
    MutationKind.PRICE: MutationMetrics(primary=GMV, secondary=(SKU_ORDERS, GMV_PER_ORDER)),
}


def resolve_metric(metric_key: str) -> MetricSpec:
    """Resolve an arbitrary metric key (e.g. an ActionCard's
    ``expected_impact.metric``) against :data:`ALL_METRICS`.

    Raises ``KeyError`` naming the unresolved key rather than returning
    ``None`` — an ActionCard rollup metric that this package does not know
    how to compute is a caller bug worth failing loudly on, not silently
    skipping.
    """
    try:
        return ALL_METRICS[metric_key]
    except KeyError:
        raise KeyError(
            f"unknown impact metric key {metric_key!r}; known keys: {sorted(ALL_METRICS)}"
        ) from None
