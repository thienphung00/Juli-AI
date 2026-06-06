"""Public result types for ad performance training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sklearn.base import BaseEstimator

AdAction = Literal["scale", "cut", "hold"]


@dataclass(frozen=True)
class AdPerformanceModel:
    """Composite model bundle for ROAS regression and action classification."""

    roas_regressor: BaseEstimator
    action_classifier: BaseEstimator


@dataclass(frozen=True)
class InferenceResult:
    """Inference output schema for Phase 2 Growth Copilot."""

    action: AdAction
    confidence: float
    predicted_roas: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": float(self.confidence),
            "predicted_roas": float(self.predicted_roas),
        }


@dataclass(frozen=True)
class TrainResult:
    model: AdPerformanceModel
    metrics: dict[str, Any]
    metrics_path: str
    training_log_path: str
    class_imbalance_strategy: str
