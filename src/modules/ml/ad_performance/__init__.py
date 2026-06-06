"""Ad performance analyzer training and inference."""

from src.modules.ml.ad_performance.fixtures import GOLDEN_AD_FIXTURES
from src.modules.ml.ad_performance.inference import predict_ad_action
from src.modules.ml.ad_performance.thresholds import (
    AD_ACTIONS,
    HOLD_CONFIDENCE_THRESHOLD,
    SPARSE_MAX_CONFIDENCE,
)
from src.modules.ml.ad_performance.train import (
    CLASS_IMBALANCE_STRATEGY,
    build_ad_training_frame,
    train_ad_performance,
)
from src.modules.ml.ad_performance.types import AdPerformanceModel, InferenceResult, TrainResult

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
