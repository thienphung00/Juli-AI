"""Model artifact publisher — serialize, load, and smoke-test trained models."""

from src.modules.ml.artifacts.exceptions import ArtifactError, ArtifactLoadError, ArtifactPublishError
from src.modules.ml.artifacts.load import load_metadata, load_model
from src.modules.ml.artifacts.promotion import evaluate_promotion_status
from src.modules.ml.artifacts.publish import publish_model
from src.modules.ml.artifacts.schema import feature_columns_for_suite, feature_schema_hash
from src.modules.ml.artifacts.smoke import run_all_smoke_tests, run_smoke_test
from src.modules.ml.artifacts.types import MODEL_SUITES, ArtifactBundle, LoadedModel, ModelSuite, PromotionStatus

__all__ = [
    "MODEL_SUITES",
    "ArtifactBundle",
    "ArtifactError",
    "ArtifactLoadError",
    "ArtifactPublishError",
    "LoadedModel",
    "ModelSuite",
    "PromotionStatus",
    "evaluate_promotion_status",
    "feature_columns_for_suite",
    "feature_schema_hash",
    "load_metadata",
    "load_model",
    "publish_model",
    "run_all_smoke_tests",
    "run_smoke_test",
]
