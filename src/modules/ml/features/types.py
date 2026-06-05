"""Feature matrix types for Phase 1.5 ML training."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FeatureMatrix:
    """Tabular feature output for a model suite."""

    grain: str
    feature_columns: tuple[str, ...]
    frame: pd.DataFrame
    metadata: dict[str, Any]
