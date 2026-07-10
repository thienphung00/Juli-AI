"""Model artifact publisher — serialize, load, and smoke-test trained models."""

from juli_backend.ai.artifacts.exceptions import ArtifactError, ArtifactLoadError, ArtifactPublishError
from juli_backend.ai.artifacts.load import load_metadata, load_model
from juli_backend.ai.artifacts.promotion import evaluate_promotion_status
from juli_backend.ai.artifacts.publish import publish_model
from juli_backend.ai.artifacts.schema import feature_columns_for_suite, feature_schema_hash
from juli_backend.ai.artifacts.smoke import run_all_smoke_tests, run_smoke_test
from juli_backend.ai.artifacts.types import MODEL_SUITES, ArtifactBundle, LoadedModel, ModelSuite, PromotionStatus

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
