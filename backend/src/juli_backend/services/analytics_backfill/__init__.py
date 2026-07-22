"""Analytics historical backfill services (Phase 2.9)."""

from juli_backend.services.analytics_backfill.budget import (
    BudgetExhaustedError,
    CallBudgetGovernor,
    begin_run,
)
from juli_backend.services.analytics_backfill.catalog_partition import (
    ACTIVE_PRODUCT_STATUSES,
    BACKFILL_WINDOW_START,
    CATALOG_BUCKET,
    CatalogCounts,
    CatalogCountStrategy,
    CatalogPartitionResult,
    compute_catalog_counts,
    run_catalog_partition,
)
from juli_backend.services.analytics_backfill.coverage import (
    PRODUCT_COVERAGE_THRESHOLD,
    REVENUE_LIVE_COVERAGE_THRESHOLD,
    BucketCoverageResult,
    CoverageReport,
    coverage_ratio,
    coverage_report_to_json,
    coverage_report_to_markdown,
    generate_coverage_report,
    meets_coverage_threshold,
)
from juli_backend.services.analytics_backfill.live_partition import (
    LivePartitionResult,
    run_live_partition,
)
from juli_backend.services.analytics_backfill.orchestrator import (
    ALLOWED_BUCKETS,
    DEFAULT_BUCKET_ORDER,
    OrchestratorResult,
    backfill_analytics_history,
    validate_buckets,
)
from juli_backend.services.analytics_backfill.product_partition import (
    ProductPartitionResult,
    backfill_product_partition,
)
from juli_backend.services.analytics_backfill.revenue_partition import (
    backfill_revenue_partition,
)

__all__ = [
    "ACTIVE_PRODUCT_STATUSES",
    "ALLOWED_BUCKETS",
    "BACKFILL_WINDOW_START",
    "BudgetExhaustedError",
    "BucketCoverageResult",
    "CATALOG_BUCKET",
    "CallBudgetGovernor",
    "CoverageReport",
    "PRODUCT_COVERAGE_THRESHOLD",
    "REVENUE_LIVE_COVERAGE_THRESHOLD",
    "CatalogCountStrategy",
    "CatalogCounts",
    "CatalogPartitionResult",
    "DEFAULT_BUCKET_ORDER",
    "LivePartitionResult",
    "OrchestratorResult",
    "ProductPartitionResult",
    "backfill_analytics_history",
    "backfill_product_partition",
    "backfill_revenue_partition",
    "begin_run",
    "compute_catalog_counts",
    "coverage_ratio",
    "coverage_report_to_json",
    "coverage_report_to_markdown",
    "generate_coverage_report",
    "meets_coverage_threshold",
    "run_catalog_partition",
    "run_live_partition",
    "validate_buckets",
]
