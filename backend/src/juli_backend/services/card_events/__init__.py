"""The card journey log ``card_events`` (ADR-107 amended 2026-10-20, fast track P60-1a).

Live writers (``record_*``, one per event kind a code path produces today) and
the per-shop backfill. See ``MODULE.md``.
"""

from juli_backend.services.card_events.backfill import BackfillReport, backfill_shop
from juli_backend.services.card_events.writer import (
    EventSpec,
    insert_event,
    record_accepted,
    record_budget_outcome,
    record_dismissed,
    record_emissions,
    record_impact,
    record_impact_readings,
    record_measurement_final,
    record_proposed,
    record_run_outcome,
    record_superseded,
)

__all__ = [
    "BackfillReport",
    "EventSpec",
    "backfill_shop",
    "insert_event",
    "record_accepted",
    "record_budget_outcome",
    "record_dismissed",
    "record_emissions",
    "record_impact",
    "record_impact_readings",
    "record_measurement_final",
    "record_proposed",
    "record_run_outcome",
    "record_superseded",
]
