"""What the builder reads once per request: the recommendation environment (30-day history) plus
the 90-day view and the variations of the products the versions name."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_recommendations.env import RecoEnv


class SpecRefused(ValueError):
    """The version cannot be built; ``code`` is a key of ``manual`` refusals (+ ``:detail``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class BuilderContext:
    env: RecoEnv
    #: item id -> the variation rows (``variations.variation_rows``)
    variations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    view90: PeriodView | None = None
    #: items with no order in the window, evaluated on one reference order per variation
    reference_items: set[str] = field(default_factory=set)
    #: item id -> {keyword: monthly search volume} of the products whose Tiêu đề / Mô tả version is
    #: evaluated (``keyword_coverage``); an item absent / empty has no keyword data
    keyword_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    #: the environment before the reference orders were added (what freshness fingerprints)
    source_env: RecoEnv | None = None

    def rows(self, item_id: str) -> list[dict[str, Any]]:
        return self.variations.get(item_id, [])

    def variation(self, item_id: str, variation_id: str) -> dict[str, Any] | None:
        if not variation_id and len(self.rows(item_id)) == 1:
            return self.rows(item_id)[0]
        for row in self.rows(item_id):
            if row["variation_id"] == variation_id:
                return row
        return None

    def sku_key(self, item_id: str, variation_id: str) -> str | None:
        """The cost key the profit engine files this variation under. ``None`` for "no variation
        named" on a listing that has several (the evaluator then takes its best seller)."""
        if not variation_id:
            # "no variation named" is the listing's only model when it has just one (a listing
            # without variations still has one model id); several: the evaluator takes the best
            # seller
            rows = self.rows(item_id)
            return str(rows[0]["sku_key"]) if len(rows) == 1 else None
        row = self.variation(item_id, variation_id)
        if row is None:
            raise SpecRefused(f"variation_unknown:{item_id}:{variation_id}")
        return str(row["sku_key"])


__all__ = ["BuilderContext", "SpecRefused"]
