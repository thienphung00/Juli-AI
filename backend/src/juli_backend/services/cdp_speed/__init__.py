"""CDP Speed layer — targeted Partner fetch planning (#626) and Shared Compute (#627)."""

from juli_backend.services.cdp_speed.enqueue_reason import webhook_catalog_enqueue_reason
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
    SharedComputeResult,
    run_shared_compute_job,
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
    "SharedComputeJob",
    "SharedComputeOrchestrator",
    "SharedComputeResult",
    "TargetedFetchExecutor",
    "TargetedFetchPlan",
    "execute_targeted_fetch_to_bronze",
    "job_correlation_token",
    "make_targeted_fetch_bronze_handoff",
    "plan_targeted_fetch",
    "run_shared_compute_job",
    "webhook_catalog_enqueue_reason",
]
