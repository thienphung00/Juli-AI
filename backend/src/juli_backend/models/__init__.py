"""SQLAlchemy ORM models."""

from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import *  # noqa: F403
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue, ShopRule
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport, ShopMetricRanking

#: Imported for their side effect: register `shop_ingestion_state`,
#: `shop_diagnosis_reports`, `shop_metric_rankings`, the P8-C tables and P10-A's
#: `decision_reasons` on `Base.metadata`.
_REGISTERED_OUTSIDE_MODELS_PY = (
    ShopIngestionState,
    ShopDiagnosisReport,
    ShopMetricRanking,
    RunWriteValue,
    ShopRule,
    RunRevertQuestion,
    DecisionReason,
)
