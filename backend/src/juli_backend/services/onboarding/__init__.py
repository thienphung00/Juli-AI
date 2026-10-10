"""Onboarding speed (fast track P17): quick scan, progress, history window.

- :mod:`.quick_scan` -- the "quét nhanh" (D26): 14 days + TikTok listing
  diagnosis -> 1-3 cover-image / title / description cards within minutes.
- :mod:`.status` -- ``GET /v1/shops/me/onboarding`` and
  ``history_days_available`` (read by P16's simulation).
- :mod:`.history` -- the history-window settings (D25.12: 180 days, nightly).

Contract: ``fasttrack/contracts/p17-onboarding-speed.md``.
"""

from juli_backend.services.onboarding.history import (
    connect_days,
    history_target_days,
    max_lookback_days,
    nightly_chunk_days,
    nightly_chunks,
)
from juli_backend.services.onboarding.quick_scan import QuickScanResult, run_quick_scan
from juli_backend.services.onboarding.quick_scan import enabled as quick_scan_enabled
from juli_backend.services.onboarding.status import (
    build_onboarding_status,
    history_days_available,
    history_progress,
    onboarding_status,
)

__all__ = [
    "QuickScanResult",
    "build_onboarding_status",
    "connect_days",
    "history_days_available",
    "history_progress",
    "history_target_days",
    "max_lookback_days",
    "nightly_chunk_days",
    "nightly_chunks",
    "onboarding_status",
    "quick_scan_enabled",
    "run_quick_scan",
]
