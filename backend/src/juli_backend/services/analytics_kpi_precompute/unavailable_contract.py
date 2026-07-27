"""Phase 2.10-A unavailable KPI envelope contract (#528).

Documents Ads, Shop Status, and T1 forecast overlays as ``unavailable`` until
dedicated data sources are wired in a later phase.

KPI keys (``kpis`` dict):
- ``roas`` — ROAS (Ads)
- ``cac`` — CAC (Ads)
- ``ctr`` — CTR (Ads)
- ``sps`` — Shop Performance Score (SPS)
- ``ahr`` — Account Health Rating (AHR)
- ``violation_points`` — Violation Points (VP)

Overlay keys (``overlays`` dict):
- ``t1_forecast`` — T1 forecast overlay
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.analytics_kpi_precompute.product_live import KpiEnvelopeEntry

ADS_KPI_KEYS = ("roas", "cac", "ctr")
SHOP_STATUS_KPI_KEYS = ("sps", "ahr", "violation_points")
PHASE_210A_UNAVAILABLE_KPI_KEYS = ADS_KPI_KEYS + SHOP_STATUS_KPI_KEYS

_KPI_LABELS: dict[str, str] = {
    "roas": "ROAS (Ads)",
    "cac": "CAC (Ads)",
    "ctr": "CTR (Ads)",
    "sps": "Shop Performance Score (SPS)",
    "ahr": "Account Health Rating (AHR)",
    "violation_points": "Violation Points (VP)",
}

_T1_FORECAST_OVERLAY_LABEL = "T1 forecast overlay"


def build_unavailable_kpi_entry(kpi_id: str) -> KpiEnvelopeEntry:
    """Return an unavailable ``KpiEnvelopeEntry`` for a known phase-2.10-A KPI key."""
    label = _KPI_LABELS[kpi_id]
    return KpiEnvelopeEntry(availability="unavailable", label=label, series=[])


def build_phase_210a_unavailable_kpis() -> dict[str, KpiEnvelopeEntry]:
    """All Ads + Shop Status KPIs marked unavailable for phase 2.10-A."""
    return {key: build_unavailable_kpi_entry(key) for key in PHASE_210A_UNAVAILABLE_KPI_KEYS}


def build_t1_forecast_overlay() -> dict[str, Any]:
    """T1 forecast overlay — unavailable until forecast pipeline is wired."""
    return {"availability": "unavailable", "label": _T1_FORECAST_OVERLAY_LABEL}
