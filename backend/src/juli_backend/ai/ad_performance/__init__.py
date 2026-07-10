"""Ad performance analyzer training and inference."""

from juli_backend.ai.ad_performance.fixtures import GOLDEN_AD_FIXTURES
from juli_backend.ai.ad_performance.inference import predict_ad_action
from juli_backend.ai.ad_performance.thresholds import (
    AD_ACTIONS,
    HOLD_CONFIDENCE_THRESHOLD,
    SPARSE_MAX_CONFIDENCE,
)
from juli_backend.ai.ad_performance.train import (
    CLASS_IMBALANCE_STRATEGY,
    build_ad_training_frame,
    train_ad_performance,
)
from juli_backend.ai.ad_performance.types import AdPerformanceModel, InferenceResult, TrainResult

__all__ = [
    "AD_ACTIONS",
    "AdPerformanceModel",
    "CLASS_IMBALANCE_STRATEGY",
    "GOLDEN_AD_FIXTURES",
    "HOLD_CONFIDENCE_THRESHOLD",
    "InferenceResult",
    "SPARSE_MAX_CONFIDENCE",
    "TrainResult",
    "build_ad_training_frame",
    "predict_ad_action",
    "train_ad_performance",
]
