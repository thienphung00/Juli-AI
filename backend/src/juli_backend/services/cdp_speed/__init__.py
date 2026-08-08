"""CDP Speed layer — fetch planning, shared compute, quota guards."""

from juli_backend.services.cdp_speed.enqueue_reason import webhook_catalog_enqueue_reason
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.quota_guard import (
    QUOTA_GUARDED_RESOURCE_NAMES,
    is_quota_guarded,
    quota_guard_reason,
)
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
    SharedComputeResult,
    run_shared_compute_job,
    scoring_stage_enabled,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    TargetedFetchExecutor,
    execute_targeted_fetch_to_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FUJIWA_POLL_RESOURCE_NAMES,
    FULL_SYNC_ANALYTICS_RESOURCE_NAMES,
    FetchResource,
    TargetedFetchPlan,
    plan_targeted_fetch,
)

__all__ = [
    "BronzeAppendTracker",
    "FetchResource",
    "FUJIWA_POLL_RESOURCE_NAMES",
    "FULL_SYNC_ANALYTICS_RESOURCE_NAMES",
    "QUOTA_GUARDED_RESOURCE_NAMES",
    "SharedComputeJob",
    "SharedComputeOrchestrator",
    "SharedComputeResult",
    "TargetedFetchExecutor",
    "TargetedFetchPlan",
    "execute_targeted_fetch_to_bronze",
    "is_quota_guarded",
    "job_correlation_token",
    "make_targeted_fetch_bronze_handoff",
    "plan_targeted_fetch",
    "quota_guard_reason",
    "run_shared_compute_job",
    "scoring_stage_enabled",
    "webhook_catalog_enqueue_reason",
]
