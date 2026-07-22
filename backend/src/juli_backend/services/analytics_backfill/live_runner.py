"""Live operator wiring for analytics historical backfill CLI (#472).

Resolves Fujiwa production-read credentials, refreshes OAuth tokens, builds
Section-A read resources, and dispatches partition runners into the orchestrator.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
)
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import CallBudgetGovernor, begin_run
from juli_backend.services.analytics_backfill.catalog_partition import run_catalog_partition
from juli_backend.services.analytics_backfill.live_partition import run_live_partition
from juli_backend.services.analytics_backfill.orchestrator import (
    OrchestratorResult,
    PartitionRunner,
    backfill_analytics_history,
)
from juli_backend.services.analytics_backfill.product_partition import backfill_product_partition
from juli_backend.services.analytics_backfill.revenue_partition import backfill_revenue_partition

logger = logging.getLogger(__name__)

ResolveCredentialFn = Callable[[AsyncSession], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], ProductionReadResources]

DEFAULT_API_BASE_URL = "https://open-api.tiktokglobalshop.com"


class BackfillBudgetPause(Exception):
    """Raised when a partition pauses mid-flight due to call-budget exhaustion."""


class BackfillPartitionFailed(Exception):
    """Raised when a partition runner reports a hard failure."""


@dataclass(frozen=True)
class BackfillCliConfig:
    """TikTok app credentials required for Fujiwa production-read backfill."""

    app_key: str
    app_secret: str
    redirect_uri: str
    api_base_url: str


@dataclass(frozen=True)
class BackfillRunSummary:
    """Operator-facing result of one live backfill invocation."""

    result: OrchestratorResult
    dry_run: bool = False


def load_backfill_cli_config() -> BackfillCliConfig:
    """Load required TikTok env vars for credential refresh and client factory."""
    return BackfillCliConfig(
        app_key=require_env("TIKTOK_APP_KEY"),
        app_secret=require_env("TIKTOK_APP_SECRET"),
        redirect_uri=require_env("TIKTOK_REDIRECT_URI"),
        api_base_url=os.getenv("TIKTOK_API_BASE_URL", DEFAULT_API_BASE_URL).strip()
        or DEFAULT_API_BASE_URL,
    )


def _assert_fujiwa_credential(credential: TikTokCredential) -> None:
    if credential.merchant_authorization_id != PRODUCTION_AUTH_ID:
        raise SystemExit(
            "Analytics backfill requires Fujiwa production-read credentials; "
            f"got merchant {credential.merchant_authorization_id}"
        )
    if credential.capability != TikTokCapability.PRODUCTION_READ.value:
        raise SystemExit(
            "Analytics backfill requires production_read capability; "
            f"got {credential.capability}"
        )


def assert_shop_matches_credential(
    shop_id: uuid.UUID,
    credential: TikTokCredential,
) -> None:
    """Guard against backfilling the wrong shop when multiple credentials exist."""
    if credential.shop_id != shop_id:
        raise SystemExit(
            f"--shop-id {shop_id} does not match Fujiwa credential shop_id "
            f"{credential.shop_id}"
        )


def _factory_config(
    config: BackfillCliConfig,
    credential: TikTokCredential,
) -> ClientFactoryConfig:
    return ClientFactoryConfig(
        app_key=config.app_key,
        app_secret=config.app_secret,
        access_token=credential.access_token,
        merchant_auth_id=PRODUCTION_AUTH_ID,
        shop_cipher=credential.shop_cipher,
        base_url=config.api_base_url,
    )


def build_oauth_service(
    session: AsyncSession,
    config: BackfillCliConfig,
) -> TikTokOAuthService:
    tiktok_auth = TikTokAuth(
        app_key=config.app_key,
        app_secret=config.app_secret,
        base_url=config.api_base_url,
    )
    return TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=config.redirect_uri,
        app_secret=config.app_secret,
    )


def build_partition_dispatcher(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    resources: ProductionReadResources,
    budget: CallBudgetGovernor,
    synced_at: int,
) -> PartitionRunner:
    """Map orchestrator bucket keys to one-day partition runners."""
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)
    performance_repo = AnalyticsPerformanceRepo(session)

    async def run_partition(bucket: str, partition_date: date) -> None:
        if bucket == "revenue":
            status = await backfill_revenue_partition(
                shop_id=shop_id,
                partition_date=partition_date,
                analytics_resource=resources.analytics,
                partitions_repo=partitions_repo,
                performance_repo=performance_repo,
                budget=budget,
                synced_at=synced_at,
            )
            if status == "failed":
                raise BackfillPartitionFailed(
                    f"revenue partition failed for {partition_date.isoformat()}"
                )
            return

        if bucket == "live":
            live_result = await run_live_partition(
                shop_id=shop_id,
                partition_date=partition_date,
                analytics=resources.analytics,
                budget=budget,
                partitions_repo=partitions_repo,
                performance_repo=performance_repo,
                synced_at=synced_at,
            )
            if live_result.status == "paused":
                raise BackfillBudgetPause()
            if live_result.status == "failed":
                raise BackfillPartitionFailed(
                    f"live partition failed for {partition_date.isoformat()}"
                )
            return

        if bucket == "product":
            product_result = await backfill_product_partition(
                session,
                shop_id=shop_id,
                partition_date=partition_date,
                resource=resources.analytics,
                budget=budget,
                synced_at=synced_at,
            )
            if product_result.skipped or product_result.complete:
                return
            if product_result.error and "budget exhausted" in product_result.error.lower():
                raise BackfillBudgetPause()
            raise BackfillPartitionFailed(
                product_result.error or f"product partition failed for {partition_date.isoformat()}"
            )

        if bucket == "catalog":
            catalog_result = await run_catalog_partition(
                session=session,
                shop_id=shop_id,
                partition_date=partition_date,
                products=resources.products,
                budget=budget,
            )
            if catalog_result.status in {"completed", "skipped"}:
                return
            raise BackfillPartitionFailed(
                catalog_result.error or f"catalog partition failed for {partition_date.isoformat()}"
            )

        raise BackfillPartitionFailed(f"unknown backfill bucket {bucket!r}")

    return run_partition


def orchestrator_result_to_exit_code(result: OrchestratorResult) -> int:
    """Exit 0 on clean complete or budget pause; 1 on hard error."""
    return 0 if result.stopped_reason in {"complete", "budget"} else 1


def summary_to_text(summary: BackfillRunSummary) -> str:
    """Structured operator summary without secrets."""
    result = summary.result
    prefix = "dry_run_validated" if summary.dry_run else "analytics_backfill_summary"
    return (
        f"{prefix} "
        f"shop_id={result.shop_id} "
        f"start={result.start_date} end={result.end_date} "
        f"buckets={','.join(result.buckets)} "
        f"stopped_reason={result.stopped_reason} "
        f"skipped={result.skipped_partitions} "
        f"completed={result.completed_partitions} "
        f"attempts={result.budget_fields.get('attempts')} "
        f"successes={result.budget_fields.get('successes')} "
        f"failures={result.budget_fields.get('failures')} "
        f"rate_limited={result.budget_fields.get('rate_limited')}"
    )


async def execute_live_backfill(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date,
    end_date: date,
    buckets: tuple[str, ...],
    dry_run: bool = False,
    resolve_credential: ResolveCredentialFn | None = None,
    oauth_service: TikTokOAuthService | None = None,
    factory: ProductionReadClientFactory | None = None,
    create_resources: CreateResourcesFn | None = None,
) -> BackfillRunSummary:
    """Run one budgeted analytics backfill pass for Fujiwa production-read."""
    config = load_backfill_cli_config()
    resolve = resolve_credential or resolve_production_read_credential
    credential = await resolve(session)
    _assert_fujiwa_credential(credential)
    assert_shop_matches_credential(shop_id, credential)

    oauth = oauth_service or build_oauth_service(session, config)
    credential = await oauth.refresh_merchant_tokens(
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )

    if dry_run:
        budget = begin_run()
        budget.finish("complete")
        return BackfillRunSummary(
            dry_run=True,
            result=OrchestratorResult(
                stopped_reason="complete",
                skipped_partitions=0,
                completed_partitions=0,
                budget_fields=budget.structured_log_fields(),
                shop_id=shop_id,
                start_date=start_date,
                end_date=end_date,
                buckets=buckets,
            ),
        )

    client_factory = factory or ProductionReadClientFactory()
    build_resources = create_resources or client_factory.create_resources
    resources = build_resources(_factory_config(config, credential))
    budget = begin_run()
    synced_at = int(time.time())
    run_partition = build_partition_dispatcher(
        session,
        shop_id=shop_id,
        resources=resources,
        budget=budget,
        synced_at=synced_at,
    )

    try:
        result = await backfill_analytics_history(
            session,
            shop_id=shop_id,
            start_date=start_date,
            end_date=end_date,
            buckets=buckets,
            budget=budget,
            run_partition=run_partition,
        )
    except BackfillBudgetPause:
        budget.finish("budget")
        result = OrchestratorResult(
            stopped_reason="budget",
            skipped_partitions=0,
            completed_partitions=0,
            budget_fields=budget.structured_log_fields(),
            shop_id=shop_id,
            start_date=start_date,
            end_date=end_date,
            buckets=buckets,
        )

    await session.commit()
    logger.info(
        "analytics_backfill_cli_finished",
        extra={
            "shop_id": str(shop_id),
            "stopped_reason": result.stopped_reason,
            "completed_partitions": result.completed_partitions,
            "skipped_partitions": result.skipped_partitions,
            **result.budget_fields,
        },
    )
    return BackfillRunSummary(result=result)
