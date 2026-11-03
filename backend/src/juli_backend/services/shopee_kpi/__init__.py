"""Shopee contract KPIs, expected move and the CTR / CTOR flow model (ADR-117 step 3, G6).

The backend port of ``juli-client-ops/tools/{kpi.py, expected_move.py, flow_model.py}``
(the references; their numbers are the acceptance check). The dashboards (Juli Ops "Mô
phỏng") only read what this job stores.

- :mod:`.rules` -- Phụ lục 01: baseline, ±D, stability windows, data sufficiency,
  acceptance. Pure.
- :mod:`.expected_move` -- milestone forecasts from history drift and the lever plan,
  P(pass), flow GMV. Pure.
- :mod:`.flow_glm` -- quasi-binomial GLM per flow x rate, numpy only (no statsmodels /
  patsy in the backend). Pure.
- :mod:`.exclusions` -- the contract's excluded days, for other readers of the daily metrics.
- :mod:`.job` -- reads ``kpi_*`` / ``lever_plans`` (Ops role) and
  ``platform_daily_metrics`` (shop scope), writes ``kpi_forecasts`` (and a contract
  version's first ``kpi_targets``). ``api/routes/ops_shopee_kpi.py`` and
  ``scripts/shopee_kpi_run.py`` call it.

Everything here is internal: contract terms and forecasts are never shown to a seller
(D42 G4).
"""

from __future__ import annotations

from juli_backend.services.shopee_kpi.exclusions import contract_excluded_days
from juli_backend.services.shopee_kpi.job import (
    FLOW_SOURCES,
    MeasureStartMissing,
    NoKpiContract,
    NoMetrics,
    RunResult,
    current_report,
    forecast_json,
    latest_forecasts,
    run_shop_kpi,
)
from juli_backend.services.shopee_kpi.rules import ContractTermsError

__all__ = [
    "FLOW_SOURCES",
    "ContractTermsError",
    "MeasureStartMissing",
    "NoKpiContract",
    "NoMetrics",
    "RunResult",
    "current_report",
    "forecast_json",
    "latest_forecasts",
    "contract_excluded_days",
    "run_shop_kpi",
]
