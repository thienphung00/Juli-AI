"""Serving gold.kpi_envelopes payload contract helpers (#606 / ADR-046 Q3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

# ADR-044 Demo Main KPI metric_ids — unavailable shell only in A0 (no precompute).
DEMO_MAIN_KPI_METRIC_IDS: tuple[str, ...] = (
    "gmv_tiktok",
    "aov",
    "ctor",
    "live_hours",
    "cancellation_rate",
)

_DEMO_MAIN_KPI_LABELS: dict[str, str] = {
    "gmv_tiktok": "GMV (TikTok)",
    "aov": "AOV",
    "ctor": "CTOR (click→đơn)",
    "live_hours": "LIVE hours",
    "cancellation_rate": "Cancellation rate",
}

ENVELOPE_VERSION = 1


def build_honest_unavailable_shell_payload(
    *,
    shop_id: uuid.UUID,
    computed_at: datetime,
    currency: str = "VND",
) -> dict[str, Any]:
    """Honest-unavailable envelope shell with ADR-044 five KPI keys in payload.kpis."""
    kpis = {
        metric_id: {
            "availability": "unavailable",
            "label": _DEMO_MAIN_KPI_LABELS[metric_id],
        }
        for metric_id in DEMO_MAIN_KPI_METRIC_IDS
    }
    return {
        "envelope_version": ENVELOPE_VERSION,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": currency,
        "kpis": kpis,
        "meta": {"source_partitions": [], "notes": ["A0 unavailable shell (#606)"]},
    }
