"""Shop diagnosis as a product (fast track P7-A, ADR-108, D21).

The I/O half of the ADR-108 report; the analysis itself stays in the pure
``services/shop_diagnosis`` package, unchanged.

- :mod:`.fetch` -- the read-only TikTok fetch of a 60-day shop snapshot (moved
  from ``scripts/shop_diagnosis_fetch.py``, which now wraps it), 429 backoff.
- :mod:`.pacing` -- gates each fetch read on the poll path's Redis per-endpoint
  rate-limit window (same keys), waiting instead of bursting.
- :mod:`.job` -- the daily per-shop job: per-shop read credential, fetch into
  a temporary directory, build both rankings, store aggregates only.
- :mod:`.read` -- the latest stored report for ``GET /v1/demo/analysis``.
"""

from juli_backend.services.shop_diagnosis_daily.fetch import fetch_snapshot, yesterday_local
from juli_backend.services.shop_diagnosis_daily.job import (
    DEFAULT_RANKING,
    RANKINGS,
    DiagnosisBuildResult,
    assert_read_credential_for,
    build_and_store_shop_diagnosis,
    json_safe,
    report_end_date,
)
from juli_backend.services.shop_diagnosis_daily.pacing import shared_rate_limiter
from juli_backend.services.shop_diagnosis_daily.read import (
    StoredDiagnosis,
    latest_shop_diagnosis,
)

__all__ = [
    "DEFAULT_RANKING",
    "RANKINGS",
    "DiagnosisBuildResult",
    "StoredDiagnosis",
    "assert_read_credential_for",
    "build_and_store_shop_diagnosis",
    "fetch_snapshot",
    "json_safe",
    "latest_shop_diagnosis",
    "report_end_date",
    "shared_rate_limiter",
    "yesterday_local",
]
