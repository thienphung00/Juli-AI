"""Serving gold.kpi_envelopes payload contract helpers (#606 / ADR-046 Q3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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

# How long a source may go without advancing before it counts as stale. Per-source,
# because the two feeds have different natural cadences and a single threshold is
# wrong for one of them:
#
#   silver.orders  — refreshed by the hourly reconcile. Three hours leaves room for a
#                    slow run (the slowest observed took 2244.9s) without tolerating a
#                    dead one. Matches the envelope-age alarm (#853) so the two signals
#                    cannot disagree about what "stale" means.
#   intervals      — daily-grain rows keyed by the day measured, so the newest row is
#                    up to 24h old the moment it lands. Anything under ~2 days would
#                    flag a perfectly healthy backfill every single afternoon.
_ORDERS_STALE_AFTER_SECONDS = 3 * 60 * 60
_INTERVALS_STALE_AFTER_SECONDS = 48 * 60 * 60

SOURCE_STALE_AFTER_SECONDS: dict[str, int] = {
    "silver.orders": _ORDERS_STALE_AFTER_SECONDS,
    "analytics_performance_intervals": _INTERVALS_STALE_AFTER_SECONDS,
}

# Which source each KPI is derived from, so a consumer can tell which numbers a
# stalled upstream actually affects. ctor and live_hours read local interval rows and
# are unaffected by a TikTok orders outage; the other three are not.
KPI_SOURCE: dict[str, str] = {
    "gmv_tiktok": "silver.orders",
    "aov": "silver.orders",
    "cancellation_rate": "silver.orders",
    "ctor": "analytics_performance_intervals",
    "live_hours": "analytics_performance_intervals",
}


def _as_utc(value: datetime | None) -> datetime | None:
    """Treat a naive timestamp as UTC.

    Order.update_time and the interval dates are stored as `timestamp without time
    zone` holding UTC, so they arrive naive from both Postgres and the SQLite test
    engine while computed_at is aware. Comparing the two directly raises.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def build_source_freshness(
    *,
    source: str,
    as_of: datetime | None,
    computed_at: datetime,
    row_count: int,
) -> dict[str, Any]:
    """Describe how old the newest record behind a KPI source is.

    ``computed_at`` answers "when did gold last run", which stays fresh even when the
    upstream fetch has been failing for days. This answers the different and more
    useful question: how old is the data those numbers were computed from.
    """
    as_of = _as_utc(as_of)
    computed_at = _as_utc(computed_at) or computed_at
    stale_after = SOURCE_STALE_AFTER_SECONDS[source]
    entry: dict[str, Any] = {"row_count": row_count, "stale_after_seconds": stale_after}
    if as_of is None:
        entry["as_of"] = None
        entry["age_seconds"] = None
        # No rows at all is a distinct condition from rows that stopped advancing;
        # the KPI reads unavailable in that case and staleness is not the story.
        entry["stale"] = False
        return entry
    age = max(0, int((computed_at - as_of).total_seconds()))
    entry["as_of"] = as_of.isoformat()
    entry["age_seconds"] = age
    entry["stale"] = age > stale_after
    return entry


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
