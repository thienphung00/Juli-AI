"""Buyer-behavior anomaly detector training and inference."""

from juli_backend.ai.anomaly.fixtures import GOLDEN_ANOMALY_FIXTURES
from juli_backend.ai.anomaly.inference import predict_anomaly
from juli_backend.ai.anomaly.thresholds import ANOMALY_CLASSES, ANOMALY_CONFIDENCE_THRESHOLD
from juli_backend.ai.anomaly.train import CLASS_IMBALANCE_STRATEGY, build_anomaly_training_frame, train_anomaly
from juli_backend.ai.anomaly.types import InferenceResult, TrainResult

__all__ = [
    "ANOMALY_CLASSES",
    "ANOMALY_CONFIDENCE_THRESHOLD",
    "CLASS_IMBALANCE_STRATEGY",
    "GOLDEN_ANOMALY_FIXTURES",
    "InferenceResult",
    "TrainResult",
    "build_anomaly_training_frame",
    "predict_anomaly",
    "train_anomaly",
]
