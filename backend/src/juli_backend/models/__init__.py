"""SQLAlchemy ORM models."""

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.lever_flows import (
    LeverCalibration,
    RunLeverFlow,
    RunLeverPhoto,
    RunMeasurementFinal,
)
from juli_backend.models.models import *  # noqa: F403
from juli_backend.models.ops import (
    OpsAuditLog,
    OpsShopInvite,
    OpsShopSettings,
    OpsSimScenario,
    OpsStaff,
)
from juli_backend.models.order_costs import (
    OrderCostFetch,
    OrderFinanceTransaction,
    OrderPriceDetail,
)
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue, ShopRule
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport, ShopMetricRanking

#: Imported for their side effect: register `shop_ingestion_state`,
#: `shop_diagnosis_reports`, `shop_metric_rankings`, the P8-C tables, P10-A's
#: `decision_reasons` and the P10-B tables on `Base.metadata`.
_REGISTERED_OUTSIDE_MODELS_PY = (
    ShopIngestionState,
    ShopDiagnosisReport,
    ShopMetricRanking,
    RunWriteValue,
    ShopRule,
    RunRevertQuestion,
    DecisionReason,
    RunLeverFlow,
    RunLeverPhoto,
    LeverCalibration,
    RunMeasurementFinal,
    OrderPriceDetail,
    OrderFinanceTransaction,
    OrderCostFetch,
    ContentAnalysis,
    OpsStaff,
    OpsAuditLog,
    OpsShopSettings,
    OpsSimScenario,
    OpsShopInvite,
)
