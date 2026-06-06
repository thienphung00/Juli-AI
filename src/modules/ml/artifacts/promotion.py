"""Promotion gate: promoted vs experimental based on backtest metrics."""

from __future__ import annotations

from typing import Any

from src.modules.ml.artifacts.thresholds import (
    AD_PERFORMANCE_MAX_ROAS_MAPE,
    ANOMALY_MIN_PRECISION,
    ANOMALY_MIN_RECALL,
    SELLER_STAGE_MIN_PRECISION,
    SELLER_STAGE_MIN_RECALL_MACRO,
)
from src.modules.ml.artifacts.types import ModelSuite, PromotionStatus


def evaluate_promotion_status(suite: ModelSuite, metrics: dict[str, Any]) -> PromotionStatus:
    """Return promoted when metrics meet provisional backtest thresholds."""
    if suite == "seller_stage":
        precision = float(metrics.get("precision", 0.0))
        recall_macro = float(metrics.get("recall_macro", 0.0))
        if precision >= SELLER_STAGE_MIN_PRECISION and recall_macro >= SELLER_STAGE_MIN_RECALL_MACRO:
            return "promoted"
        return "experimental"

    if suite == "anomaly":
        per_class = metrics.get("per_class", {})
        for anomaly_class in ("item_swap", "empty_return"):
            class_metrics = per_class.get(anomaly_class, {})
            precision = float(class_metrics.get("precision", 0.0))
            recall = float(class_metrics.get("recall", 0.0))
            if precision < ANOMALY_MIN_PRECISION or recall < ANOMALY_MIN_RECALL:
                return "experimental"
        return "promoted"

    if suite == "ad_performance":
        roas_mape = float(metrics.get("roas_mape", float("inf")))
        if roas_mape <= AD_PERFORMANCE_MAX_ROAS_MAPE:
            return "promoted"
        return "experimental"

    raise ValueError(f"unknown model suite: {suite}")
