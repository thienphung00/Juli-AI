"""Feature schema hashing for artifact metadata."""

from __future__ import annotations

import hashlib

from src.modules.ml.artifacts.types import MODEL_SUITES, ModelSuite
from src.modules.ml.features.schema import (
    AD_FEATURE_COLUMNS,
    ANOMALY_FEATURE_COLUMNS,
    SELLER_STAGE_FEATURE_COLUMNS,
)

_SUITE_COLUMNS: dict[ModelSuite, tuple[str, ...]] = {
    "seller_stage": SELLER_STAGE_FEATURE_COLUMNS,
    "anomaly": ANOMALY_FEATURE_COLUMNS,
    "ad_performance": AD_FEATURE_COLUMNS,
}


def feature_columns_for_suite(suite: ModelSuite) -> tuple[str, ...]:
    """Return authoritative feature column tuple for a model suite."""
    if suite not in MODEL_SUITES:
        raise ValueError(f"unknown model suite: {suite}")
    return _SUITE_COLUMNS[suite]


def feature_schema_hash(suite: ModelSuite) -> str:
    """Stable hash of feature column names for lineage tracking."""
    columns = feature_columns_for_suite(suite)
    payload = "|".join(columns)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
