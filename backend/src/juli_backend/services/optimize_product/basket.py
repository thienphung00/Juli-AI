"""Basket quantities from real orders — the BMSM threshold (ADR-106 Amendment 3).

An order search payload carries ``line_items[]`` with one entry per unit; the
quantity of a product in an order is the number of its non-gift lines.
Cancelled orders are ignored. Pure: callers hand the orders in.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from juli_backend.services.optimize_product.config import StageDiagnosisConfig

CANCELLED = "CANCELLED"
HISTOGRAM = "histogram"
MEAN_FALLBACK = "mean_fallback"


def quantities_by_product(orders: list[dict]) -> dict[str, list[int]]:
    """Per product, the quantity bought in each non-cancelled order containing it."""
    out: dict[str, list[int]] = defaultdict(list)
    for order in orders:
        if not isinstance(order, dict) or str(order.get("status") or "") == CANCELLED:
            continue
        counts: dict[str, int] = defaultdict(int)
        for line in order.get("line_items") or []:
            if not isinstance(line, dict) or line.get("is_gift"):
                continue
            product_id = str(line.get("product_id") or "")
            if product_id:
                counts[product_id] += 1
        for product_id, quantity in counts.items():
            out[product_id].append(quantity)
    return dict(out)


@dataclass(frozen=True)
class BasketThreshold:
    threshold_items: int
    source: str
    orders: int
    #: Share of the product's orders with quantity >= threshold (histogram only).
    share: Decimal | None
    median_quantity: Decimal | None
    min_share: Decimal

    @property
    def reached(self) -> bool:
        """Fallback thresholds have no histogram to check; histogram ones need the share."""
        return self.source == MEAN_FALLBACK or (self.share or Decimal(0)) >= self.min_share


def basket_threshold(
    quantities: list[int] | None, mean_items: Decimal | None, config: StageDiagnosisConfig
) -> BasketThreshold:
    """Rule 1: ``median + 1`` with a share check, else ``floor(mean) + 1`` (never below 2)."""
    count = len(quantities or [])
    if quantities and count >= config.bmsm_min_orders_for_histogram:
        med = Decimal(str(median(quantities)))
        threshold = max(int(math.floor(med)) + 1, config.bmsm_min_threshold_items)
        share = Decimal(sum(1 for q in quantities if q >= threshold)) / Decimal(count)
        return BasketThreshold(
            threshold, HISTOGRAM, count, share, med, config.bmsm_min_share_at_threshold
        )
    mean = mean_items if mean_items and mean_items > 0 else Decimal(1)
    threshold = max(int(math.floor(mean)) + 1, config.bmsm_min_threshold_items)
    return BasketThreshold(
        threshold, MEAN_FALLBACK, count, None, None, config.bmsm_min_share_at_threshold
    )


def share_with_at_least(quantities: list[int] | None, items: int) -> Decimal | None:
    """Share of orders with at least ``items`` units; ``None`` without orders."""
    if not quantities:
        return None
    return Decimal(sum(1 for q in quantities if q >= items)) / Decimal(len(quantities))
