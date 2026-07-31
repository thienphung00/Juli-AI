"""CDP batch layer — fleet throughput reconcile (Phase 3.5-A2)."""

from juli_backend.services.cdp_batch.partition_checkpoints import (
    BATCH_RECONCILE_INGEST_SOURCE,
    BatchPartitionCheckpointsRepo,
    BatchPartitionReconcileResult,
    PartitionPageCheckpoint,
    reconcile_partition_with_checkpoints,
)
from juli_backend.services.cdp_batch.partner_budget import (
    DEFER_REASON,
    PartnerApiBudgetGovernor,
    PartnerBudgetStopReason,
    begin_partner_budget_run,
)
from juli_backend.services.cdp_batch.postgres_io_budget import (
    DEFER_REASON as POSTGRES_IO_DEFER_REASON,
)
from juli_backend.services.cdp_batch.postgres_io_budget import (
    PostgresIoBudgetGovernor,
    PostgresIoBudgetStopReason,
    begin_postgres_io_budget_run,
)
from juli_backend.services.cdp_batch.shop_compute_mutex import (
    COMPUTE_MUTEX_TTL_SECONDS,
    BatchComputeEntryResult,
    ComputeOwner,
    InMemoryShopComputeMutex,
    RedisShopComputeMutex,
    ShopComputeMutex,
    compute_mutex_key,
    try_begin_batch_compute,
)
from juli_backend.services.cdp_batch.shop_compute_mutex import (
    DEFER_REASON as SPEED_MUTEX_DEFER_REASON,
)
from juli_backend.services.cdp_batch.stagger_scheduler import (
    MINUTES_PER_UTC_DAY,
    ReconcileWindow,
    StaggerScheduler,
    assign_window,
    window_minute_for_shop,
)

__all__ = [
    "BATCH_RECONCILE_INGEST_SOURCE",
    "BatchComputeEntryResult",
    "BatchPartitionCheckpointsRepo",
    "BatchPartitionReconcileResult",
    "COMPUTE_MUTEX_TTL_SECONDS",
    "ComputeOwner",
    "DEFER_REASON",
    "PartitionPageCheckpoint",
    "InMemoryShopComputeMutex",
    "MINUTES_PER_UTC_DAY",
    "POSTGRES_IO_DEFER_REASON",
    "PartnerApiBudgetGovernor",
    "PartnerBudgetStopReason",
    "PostgresIoBudgetGovernor",
    "PostgresIoBudgetStopReason",
    "RedisShopComputeMutex",
    "ReconcileWindow",
    "SPEED_MUTEX_DEFER_REASON",
    "ShopComputeMutex",
    "StaggerScheduler",
    "assign_window",
    "begin_partner_budget_run",
    "begin_postgres_io_budget_run",
    "compute_mutex_key",
    "reconcile_partition_with_checkpoints",
    "try_begin_batch_compute",
    "window_minute_for_shop",
]
