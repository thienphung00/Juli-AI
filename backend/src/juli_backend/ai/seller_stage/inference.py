"""Stable inference signature for seller stage classifier."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator

from juli_backend.ai.features.schema import SELLER_STAGE_FEATURE_COLUMNS
from juli_backend.ai.seller_stage.types import InferenceResult


def _feature_row(features: dict[str, Any]) -> pd.DataFrame:
    values: list[float] = []
    for column in SELLER_STAGE_FEATURE_COLUMNS:
        value = features.get(column)
        values.append(0.0 if value is None else float(value))
    return pd.DataFrame([values], columns=list(SELLER_STAGE_FEATURE_COLUMNS))


def predict_seller_stage(model: BaseEstimator, features: dict[str, Any]) -> InferenceResult:
    """Map a shop feature vector to lifecycle stage and confidence in [0, 1]."""
    row = _feature_row(features)
    stage = str(model.predict(row)[0])
    probabilities = model.predict_proba(row)[0]
    confidence = float(np.max(probabilities))
    confidence = max(0.0, min(1.0, confidence))
    return InferenceResult(stage=stage, confidence=confidence)  # type: ignore[arg-type]
