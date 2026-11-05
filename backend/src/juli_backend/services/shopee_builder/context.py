"""What the builder reads once per request: the recommendation environment (30-day history) plus
the 90-day view, the variations of the products the versions name and, for ads keywords, the
keyword facts."""

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
    #: keyword (folded) -> {volume, difficulty, cpc_min, cpc_max, ads: {...}} for ads keyword levers
    keyword_facts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def rows(self, item_id: str) -> list[dict[str, Any]]:
        return self.variations.get(item_id, [])

    def variation(self, item_id: str, variation_id: str) -> dict[str, Any] | None:
        for row in self.rows(item_id):
            if row["variation_id"] == variation_id:
                return row
        return None

    def sku_key(self, item_id: str, variation_id: str) -> str | None:
        """The cost key the profit engine files this variation under. ``None`` for "no variation
        named" on a listing that has several (the evaluator then takes its best seller)."""
        if not variation_id:
            rows = self.rows(item_id)
            only = rows[0] if len(rows) == 1 and rows[0]["variation_id"] == "" else None
            return None if only is None else str(only["sku_key"])
        row = self.variation(item_id, variation_id)
        if row is None:
            raise SpecRefused(f"variation_unknown:{item_id}:{variation_id}")
        return str(row["sku_key"])


__all__ = ["BuilderContext", "SpecRefused"]
