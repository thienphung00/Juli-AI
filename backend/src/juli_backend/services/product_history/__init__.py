"""Product history, promotions, external changes and run baselines (fast track P23, D30.1/D30.4).

- ``normalize`` -- pure: product detail → snapshot fields, hashes, diff.
- ``store`` -- snapshots and ``external_changes`` (per-field attribution, P60-1b).
- ``attribution`` -- pure: juli / seller_revert / seller_change per field (ADR-107 am. §8).
- ``promotions`` -- activity upserts, webhook 63 / 39 parsing.
- ``job`` -- the daily snapshot + promotion sweep and the webhook re-reads (TikTok reads).
- ``webhooks`` -- webhooks 15 / 16 / 18 / 63 / 39 → an enqueued re-read.
- ``replay`` -- replays the stored raw deliveries of those types.
- ``baselines`` -- ``run_baselines`` at approval and at execution start.
- ``overlap`` -- external changes overlapping a measurement window.
"""

from juli_backend.services.product_history.baselines import capture_for_run, capture_run_baseline
from juli_backend.services.product_history.job import (
    build_resources,
    plan_reads,
    reconcile_products,
    refresh_activity,
    refresh_product,
    sweep_promotions,
)
from juli_backend.services.product_history.promotions import ActivityChange
from juli_backend.services.product_history.replay import replay_raw_events
from juli_backend.services.product_history.webhooks import HistoryWork, set_history_enqueuer

__all__ = [
    "ActivityChange",
    "HistoryWork",
    "build_resources",
    "capture_for_run",
    "capture_run_baseline",
    "plan_reads",
    "reconcile_products",
    "refresh_activity",
    "refresh_product",
    "replay_raw_events",
    "set_history_enqueuer",
    "sweep_promotions",
]
