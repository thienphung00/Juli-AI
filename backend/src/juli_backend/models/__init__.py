"""SQLAlchemy ORM models."""

from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import *  # noqa: F403
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport, ShopMetricRanking

#: Imported for their side effect: register `shop_ingestion_state`,
#: `shop_diagnosis_reports` and `shop_metric_rankings` on `Base.metadata`.
_REGISTERED_OUTSIDE_MODELS_PY = (ShopIngestionState, ShopDiagnosisReport, ShopMetricRanking)
