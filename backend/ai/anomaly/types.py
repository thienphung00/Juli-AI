"""Public result types for anomaly training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.base import BaseEstimator


@dataclass(frozen=True)
class InferenceResult:
    """Inference output schema for Phase 2 UI evidence."""

    anomaly_class: str | None
    confidence: float
    feature_summary: dict[str, float]
    is_anomaly: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_class": self.anomaly_class,
            "confidence": float(self.confidence),
            "feature_summary": {key: float(value) for key, value in self.feature_summary.items()},
            "is_anomaly": bool(self.is_anomaly),
        }


@dataclass(frozen=True)
class TrainResult:
    model: BaseEstimator
    metrics: dict[str, Any]
    metrics_path: str
    training_log_path: str
    class_imbalance_strategy: str
