"""Public types for model artifact publishing and loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ModelSuite = Literal["seller_stage", "anomaly", "ad_performance"]
PromotionStatus = Literal["promoted", "experimental"]

MODEL_SUITES: tuple[ModelSuite, ...] = ("seller_stage", "anomaly", "ad_performance")


@dataclass(frozen=True)
class ArtifactBundle:
    suite: ModelSuite
    version: str
    model_path: Path
    metadata_path: Path
    metrics_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LoadedModel:
    suite: ModelSuite
    version: str
    model: Any
    metadata: dict[str, Any]
