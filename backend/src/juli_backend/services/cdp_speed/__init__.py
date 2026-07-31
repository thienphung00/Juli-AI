"""CDP Speed layer — targeted Partner fetch planning (#626)."""

from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FUJIWA_POLL_RESOURCE_NAMES,
    FULL_SYNC_ANALYTICS_RESOURCE_NAMES,
    FetchResource,
    TargetedFetchPlan,
    plan_targeted_fetch,
)

__all__ = [
    "FetchResource",
    "FUJIWA_POLL_RESOURCE_NAMES",
    "FULL_SYNC_ANALYTICS_RESOURCE_NAMES",
    "TargetedFetchPlan",
    "plan_targeted_fetch",
]
