"""Seller stage classifier training and rules baseline."""

from src.modules.ml.seller_stage.compare import compare_to_rules_baseline
from src.modules.ml.seller_stage.fixtures import STAGE_BOUNDARY_FIXTURES
from src.modules.ml.seller_stage.inference import predict_seller_stage
from src.modules.ml.seller_stage.rules import SellerStage, SellerStageProfile, classify_seller_stage
from src.modules.ml.seller_stage.thresholds import (
    AD_SPEND_GROWTH_MIN_VND,
    ORDER_COUNT_GROWTH_MIN,
    ORDER_COUNT_NEW_MAX,
    RETURN_RATE_LEAKAGE_MIN,
    SHOP_AGE_NEW_MAX_DAYS,
)
from src.modules.ml.seller_stage.train import CLASS_IMBALANCE_STRATEGY, train_seller_stage
from src.modules.ml.seller_stage.types import ComparisonReport, InferenceResult, TrainResult

__all__ = [
    "AD_SPEND_GROWTH_MIN_VND",
    "CLASS_IMBALANCE_STRATEGY",
    "ComparisonReport",
    "InferenceResult",
    "ORDER_COUNT_GROWTH_MIN",
    "ORDER_COUNT_NEW_MAX",
    "RETURN_RATE_LEAKAGE_MIN",
    "SHOP_AGE_NEW_MAX_DAYS",
    "STAGE_BOUNDARY_FIXTURES",
    "SellerStage",
    "SellerStageProfile",
    "TrainResult",
    "classify_seller_stage",
    "compare_to_rules_baseline",
    "predict_seller_stage",
    "train_seller_stage",
]
