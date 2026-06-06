"""Public result types for seller stage training and inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sklearn.base import BaseEstimator

from src.modules.ml.seller_stage.rules import SellerStage


@dataclass(frozen=True)
class InferenceResult:
    stage: SellerStage
    confidence: float


@dataclass(frozen=True)
class TrainResult:
    model: BaseEstimator
    metrics: dict[str, Any]
    metrics_path: str
    training_log_path: str
    class_imbalance_strategy: str


@dataclass(frozen=True)
class ComparisonReport:
    agreement_rate: float
    total_profiles: int
    agreements: int
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreement_rate": self.agreement_rate,
            "total_profiles": self.total_profiles,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
        }
