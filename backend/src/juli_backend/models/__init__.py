"""SQLAlchemy ORM models."""

from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import *  # noqa: F403
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue, ShopRule
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport

#: Imported for their side effect: register `shop_ingestion_state` and
#: `shop_diagnosis_reports` on `Base.metadata`.
_REGISTERED_OUTSIDE_MODELS_PY = (
    ShopIngestionState,
    ShopDiagnosisReport,
    RunWriteValue,
    ShopRule,
    RunRevertQuestion,
)
