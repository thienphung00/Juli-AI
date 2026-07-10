"""Phase 1.5 feature builders — parquet to per-model feature matrices."""

from juli_backend.ai.features.ad import build_ad_features
from juli_backend.ai.features.anomaly import build_anomaly_features
from juli_backend.ai.features.exceptions import FeatureValidationError
from juli_backend.ai.features.schema import (
    AD_FEATURE_COLUMNS,
    ANOMALY_FEATURE_COLUMNS,
    SELLER_STAGE_FEATURE_COLUMNS,
)
from juli_backend.ai.features.seller_stage import build_seller_stage_features
from juli_backend.ai.features.types import FeatureMatrix

__all__ = [
    "AD_FEATURE_COLUMNS",
    "ANOMALY_FEATURE_COLUMNS",
    "FeatureMatrix",
    "FeatureValidationError",
    "SELLER_STAGE_FEATURE_COLUMNS",
    "build_ad_features",
    "build_anomaly_features",
    "build_seller_stage_features",
]
