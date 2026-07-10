"""Stable inference signature for buyer-behavior anomaly detector."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator

from juli_backend.ai.anomaly.thresholds import ANOMALY_CLASSES, ANOMALY_CONFIDENCE_THRESHOLD
from juli_backend.ai.anomaly.types import InferenceResult
from juli_backend.ai.features.schema import ANOMALY_FEATURE_COLUMNS


def _feature_row(features: dict[str, Any]) -> pd.DataFrame:
    values: list[float] = []
    for column in ANOMALY_FEATURE_COLUMNS:
        value = features.get(column)
        values.append(0.0 if value is None else float(value))
    return pd.DataFrame([values], columns=list(ANOMALY_FEATURE_COLUMNS))


def _build_feature_summary(features: dict[str, Any]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for column in ANOMALY_FEATURE_COLUMNS:
        value = features.get(column)
        if value is None:
            continue
        numeric = float(value)
        if numeric != 0.0:
            summary[column] = numeric
    return summary


def predict_anomaly(
    model: BaseEstimator,
    features: dict[str, Any],
    *,
    threshold: float = ANOMALY_CONFIDENCE_THRESHOLD,
) -> InferenceResult:
    """Map buyer feature vector to anomaly class, confidence, and feature summary."""
    row = _feature_row(features)
    probabilities = model.predict_proba(row)[0]
    classes = [str(label) for label in model.classes_]
    class_probability = dict(zip(classes, probabilities, strict=True))
    predicted = str(model.predict(row)[0])
    confidence = float(class_probability.get(predicted, np.max(probabilities)))
    confidence = max(0.0, min(1.0, confidence))

    anomaly_probability = max(
        class_probability.get("item_swap", 0.0),
        class_probability.get("empty_return", 0.0),
    )
    best_anomaly_class = (
        "item_swap"
        if class_probability.get("item_swap", 0.0) >= class_probability.get("empty_return", 0.0)
        else "empty_return"
    )

    if predicted in ANOMALY_CLASSES and class_probability.get(predicted, 0.0) >= threshold:
        is_anomaly = True
        anomaly_class = predicted
        confidence = float(class_probability[predicted])
    elif anomaly_probability >= threshold:
        is_anomaly = True
        anomaly_class = best_anomaly_class
        confidence = float(anomaly_probability)
    else:
        is_anomaly = False
        anomaly_class = None

    return InferenceResult(
        anomaly_class=anomaly_class,
        confidence=confidence,
        feature_summary=_build_feature_summary(features),
        is_anomaly=bool(is_anomaly),
    )
