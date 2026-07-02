"""Stable inference signature for ad performance analyzer."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.ai.features.schema import AD_FEATURE_COLUMNS
from backend.ai.ad_performance.rules import is_sparse_ad_history
from backend.ai.ad_performance.thresholds import HOLD_CONFIDENCE_THRESHOLD, SPARSE_MAX_CONFIDENCE
from backend.ai.ad_performance.types import AdPerformanceModel, InferenceResult


def _feature_row(features: dict[str, Any]) -> pd.DataFrame:
    values: list[float] = []
    for column in AD_FEATURE_COLUMNS:
        value = features.get(column)
        values.append(0.0 if value is None else float(value))
    return pd.DataFrame([values], columns=list(AD_FEATURE_COLUMNS))


def predict_ad_action(
    model: AdPerformanceModel,
    features: dict[str, Any],
    *,
    hold_threshold: float = HOLD_CONFIDENCE_THRESHOLD,
) -> InferenceResult:
    """Map campaign feature vector to scale/cut/hold action with confidence."""
    if is_sparse_ad_history(features):
        return InferenceResult(action="hold", confidence=SPARSE_MAX_CONFIDENCE, predicted_roas=0.0)

    row = _feature_row(features)
    predicted_roas = float(model.roas_regressor.predict(row)[0])
    action = str(model.action_classifier.predict(row)[0])
    probabilities = model.action_classifier.predict_proba(row)[0]
    classes = [str(label) for label in model.action_classifier.classes_]
    class_probability = dict(zip(classes, probabilities, strict=True))
    confidence = float(class_probability.get(action, float(np.max(probabilities))))
    confidence = max(0.0, min(1.0, confidence))

    if action == "hold" and confidence >= hold_threshold:
        confidence = min(confidence, hold_threshold - 0.01)

    return InferenceResult(
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        predicted_roas=predicted_roas,
    )
