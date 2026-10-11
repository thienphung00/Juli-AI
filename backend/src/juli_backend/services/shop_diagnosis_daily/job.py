"""Build and store one shop's ADR-108 diagnosis report (fast track P7-A, AC-7.1).

The daily worker job behind ``juli_backend.build_shop_diagnosis``:

1. **Resolve** the shop's own read credential with
   ``resolve_read_credential_for_shop`` under that shop's plain scope, and
   refuse anything that is not a read credential owned by the shop (same
   checks as the poll path's ``_assert_pollable_read_credential``). Decide the
   report end date: the shop's last fully-fetched analytics day, never later
   than yesterday in UTC+7. If the 60-day report for that date is already
   stored, stop (idempotent per shop and end date) -- no TikTok call.
2. **Fetch** the 60-day snapshot read-only (``fetch.fetch_snapshot``, 429
   backoff) into a temporary directory, with no database session open. With a
   ``rate_limiter`` (production), every read first takes a token from the
   poll path's Redis per-endpoint window (``pacing.RateLimitedResources``).
3. **Build** the report for both hero rankings from that one snapshot (pure
   ``shop_diagnosis`` package, no extra calls), then delete the directory:
   orders carry buyer data and are never kept.
   From the same snapshot it builds the ADR-109 d.5 metric rankings
   (``shop_diagnosis.rankings``; P8-A, AC-8.1): one table per stream ×
   clickable metric, videos only when a ``video_metrics`` callable supplies
   per-video window counts. Production passes :func:`fetch_ranking_videos`
   (the worker task), which reads the per-video last-30 / prior-30 windows
   (``video_windows``, P8-B; ≤ 2 list walks + 40 details calls) with the SAME
   rate-limited resources, in the same thread, right after the snapshot. A
   video failure is logged and only drops the two video tables; a ranking
   failure is logged and never blocks the report.
4. **Store** each report's ``to_dict()`` (aggregates only) under the shop's
   scope, replacing a row for the same (shop, end date, ranking), and each
   metric ranking the same way per (shop, end date, stream, metric).

TikTok is only ever read here: the resources come from
``ProductionReadClientFactory``, whose transport refuses non-read methods.
"""

from __future__ import annotations

import asyncio
import logging
import math
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import resolve_read_credential_for_shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    SANDBOX_AUTH_ID,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    is_read_capability,
)
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories import (
    ShopDiagnosisReportsRepo,
    ShopIngestionStateRepo,
    ShopMetricRankingsRepo,
    utc_now_naive,
)
from juli_backend.services.shop_diagnosis import Ranking, Snapshot, build_report, load_snapshot
from juli_backend.services.shop_diagnosis.rankings import (
    MetricRanking,
    VideoWindowCounts,
    build_rankings,
)
from juli_backend.services.shop_diagnosis_daily.fetch import fetch_snapshot, yesterday_local
from juli_backend.services.shop_diagnosis_daily.pacing import (
    RateLimitedResources,
    SharedWindowGate,
)
from juli_backend.services.shop_diagnosis_daily.video_windows import (
    fetch_video_windows,
    ranking_videos,
)

logger = logging.getLogger(__name__)

ResolveCredentialFn = Callable[[AsyncSession, uuid.UUID], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], Any]
SessionFactory = Callable[[], Any]
#: Per-video last-30 / prior-30 counts for the video rankings, called in the
#: fetch thread with the snapshot's own (rate-limited) resources and the loaded
#: snapshot; ``None`` (or no callable) skips the video rankings.
VideoMetricsFn = Callable[[Any, Snapshot], Sequence[VideoWindowCounts] | None]

#: Both rankings are stored; the default one decides idempotency.
RANKINGS: tuple[Ranking, ...] = (Ranking.COMBINED_60D, Ranking.LAST_30D)
DEFAULT_RANKING = Ranking.COMBINED_60D


@dataclass
class DiagnosisBuildResult:
    shop_id: uuid.UUID
    end_date: date | None = None
    built: bool = False
    skipped_reason: str | None = None
    rankings: list[str] = field(default_factory=list)
    #: ``"<stream>/<metric>"`` of every stored ADR-109 metric ranking.
    metric_rankings: list[str] = field(default_factory=list)
    new_daily_files: int = 0


def assert_read_credential_for(credential: TikTokCredential, shop_id: uuid.UUID) -> None:
    """Refuse a credential that is not a read credential owned by ``shop_id``."""
    capability = credential.capability
    if capability is None or not is_read_capability(capability):
        raise ValueError(
            f"shop diagnosis requires a read-capable credential; got capability {capability!r}"
        )
    merchant = credential.merchant_authorization_id
    if not merchant:
        raise ValueError("shop diagnosis requires a credential carrying a merchant id")
    if not SANDBOX_AUTH_ID or merchant == SANDBOX_AUTH_ID:
        raise ValueError("shop diagnosis refuses the sandbox write merchant")
    if credential.shop_id != shop_id:
        raise ValueError(
            f"shop diagnosis for shop {shop_id} resolved a credential owned by {credential.shop_id}"
        )


def report_end_date(analytics_through: date | None, *, now: datetime | None = None) -> date:
    """The last fully-fetched analytics day, capped at yesterday (UTC+7)."""
    cap = yesterday_local(now)
    if analytics_through is None:
        return cap
    return min(analytics_through, cap)


def json_safe(value: Any) -> Any:
    """Replace NaN / infinity (invalid JSON, refused by Postgres) with ``None``."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


@dataclass(frozen=True)
class _Plan:
    shop_name: str
    end: date
    config: ClientFactoryConfig
    #: The rate-limit key the poll uses for this shop (``_ShopRun.shop_key``).
    shop_key: str


async def _plan(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    app_key: str,
    app_secret: str,
    resolve: ResolveCredentialFn,
    now: datetime | None,
    force: bool,
) -> _Plan | str:
    """Resolve, check and date the run; a string is the reason to skip."""
    async with with_shop_scope(session, shop_id):
        credential = await resolve(session, shop_id)
        assert_read_credential_for(credential, shop_id)
        shop = await session.get(Shop, shop_id)
        if shop is None:
            raise ValueError(f"shop diagnosis: shop {shop_id} not found")
        state = await ShopIngestionStateRepo(session).find(shop_id)
        end = report_end_date(state.analytics_through_date if state else None, now=now)
        existing = await ShopDiagnosisReportsRepo(session).find(shop_id, end, DEFAULT_RANKING)
        config = ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=str(credential.merchant_authorization_id),
            shop_cipher=credential.shop_cipher,
        )
        shop_name = shop.shop_name or ""
        shop_key = shop.tiktok_shop_id or str(shop_id)
    # Close the read transaction before the long fetch.
    await session.commit()
    if existing is not None and not force:
        return "already_built"
    return _Plan(shop_name=shop_name, end=end, config=config, shop_key=shop_key)


def fetch_ranking_videos(
    resources: Any,
    snapshot: Snapshot,
    *,
    sleep_s: float = 0.4,
    backoff_sleep: Callable[[float], Any] = time.sleep,
) -> list[VideoWindowCounts] | None:
    """Production ``video_metrics``: P8-B's per-video windows as the ranking's input.

    ``None`` when the windows were skipped for a 429 (P17): no video tables.

    ``resources`` are the snapshot fetch's own (rate-limited, read-only) ones, so
    no credential is resolved again; the call budget is ``fetch_video_windows``'
    (2 list walks + at most 20 details calls per window).
    """
    windows = fetch_video_windows(resources, snapshot, sleep_s=sleep_s, backoff_sleep=backoff_sleep)
    if windows.skipped_reason is not None:
        # P17 (D25.12): still throttled -- the video tables are skipped this
        # cycle; the other streams' tables are built and stored as usual.
        return None
    videos = ranking_videos(windows)
    logger.info(
        "shop_video_windows_fetched",
        extra={
            "end_date": snapshot.end.isoformat(),
            "basis": windows.basis,
            "calls": windows.calls,
            "videos": len(videos),
            "failed_videos": len(windows.failed_video_ids),
        },
    )
    return videos


def _metric_rankings(
    resources: Any, snapshot: Snapshot, video_metrics: VideoMetricsFn | None, shop_id: str
) -> list[MetricRanking]:
    """ADR-109 d.5 rankings from the same snapshot; a failure is logged, not raised.

    A failing video fetch (or a ranking that fails only with videos) drops the
    two video tables and keeps every other stream's.
    """
    videos: Sequence[VideoWindowCounts] | None = None
    if video_metrics is not None:
        try:
            videos = video_metrics(resources, snapshot)
        except Exception:
            logger.exception("shop_video_windows_failed", extra={"shop_id": shop_id})
    attempts = [videos, None] if videos is not None else [None]
    for attempt in attempts:
        try:
            return [
                MetricRanking(r.stream, r.metric, json_safe(r.payload))
                for r in build_rankings(snapshot, attempt)
            ]
        except Exception:
            event = "shop_metric_rankings_failed"
            if attempt is not None:
                event = "shop_video_rankings_failed"
            logger.exception(event, extra={"shop_id": shop_id})
    return []


def _fetch_and_build(
    resources: Any,
    plan: _Plan,
    *,
    tmp_root: Path | None,
    fetch_kwargs: dict[str, Any],
    video_metrics: VideoMetricsFn | None = None,
    shop_id: str = "",
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[MetricRanking]]:
    """Fetch into a temp dir, build every report and ranking, delete the dir. In a thread."""
    with tempfile.TemporaryDirectory(prefix="juli-shop-diagnosis-", dir=tmp_root) as tmp:
        folder = Path(tmp)
        meta = fetch_snapshot(resources, folder, plan.end, plan.shop_name, **fetch_kwargs)
        snapshot = load_snapshot(folder, plan.end)
        reports = {
            ranking.value: json_safe(build_report(snapshot, ranking).to_dict())
            for ranking in RANKINGS
        }
        metric_rankings = _metric_rankings(resources, snapshot, video_metrics, shop_id)
    return meta, reports, metric_rankings


async def build_and_store_shop_diagnosis(
    *,
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    app_key: str,
    app_secret: str,
    resolve_credential: ResolveCredentialFn | None = None,
    create_resources: CreateResourcesFn | None = None,
    now: datetime | None = None,
    force: bool = False,
    tmp_root: Path | None = None,
    sleep_s: float = 0.4,
    backoff_sleep: Callable[[float], Any] = time.sleep,
    rate_limiter: Any | None = None,
    rate_limit_sleep: Callable[[float], Any] = time.sleep,
    video_metrics: VideoMetricsFn | None = None,
) -> DiagnosisBuildResult:
    """Build the shop's report for its latest analytics day and store it. See module doc."""
    result = DiagnosisBuildResult(shop_id=shop_id)
    resolve = resolve_credential or resolve_read_credential_for_shop
    async with session_factory() as session:
        plan = await _plan(
            session,
            shop_id,
            app_key=app_key,
            app_secret=app_secret,
            resolve=resolve,
            now=now,
            force=force,
        )
    if isinstance(plan, str):
        result.skipped_reason = plan
        logger.info("shop_diagnosis_skipped", extra={"shop_id": str(shop_id), "reason": plan})
        return result
    result.end_date = plan.end

    build = create_resources or ProductionReadClientFactory().create_resources
    resources = build(plan.config)
    if rate_limiter is not None:
        resources = RateLimitedResources(
            resources,
            SharedWindowGate(
                rate_limiter,
                app_id=app_key,
                shop_key=plan.shop_key,
                sleep=rate_limit_sleep,
            ),
        )
    meta, reports, metric_rankings = await asyncio.to_thread(
        _fetch_and_build,
        resources,
        plan,
        tmp_root=tmp_root,
        fetch_kwargs={"sleep_s": sleep_s, "backoff_sleep": backoff_sleep},
        video_metrics=video_metrics,
        shop_id=str(shop_id),
    )
    result.new_daily_files = int(meta.get("new_daily_files") or 0)

    built_at = utc_now_naive()
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            repo = ShopDiagnosisReportsRepo(session)
            for ranking, report in reports.items():
                await repo.save(
                    shop_id, end_date=plan.end, ranking=ranking, report=report, built_at=built_at
                )
            rankings_repo = ShopMetricRankingsRepo(session)
            for table in metric_rankings:
                await rankings_repo.save(
                    shop_id,
                    end_date=plan.end,
                    stream=table.stream.value,
                    metric=table.metric.value,
                    ranking=table.payload,
                    built_at=built_at,
                )
        await session.commit()
    result.built = True
    result.rankings = list(reports)
    result.metric_rankings = [f"{t.stream.value}/{t.metric.value}" for t in metric_rankings]
    logger.info(
        "shop_diagnosis_built",
        extra={
            "shop_id": str(shop_id),
            "end_date": plan.end.isoformat(),
            "rankings": result.rankings,
            "metric_rankings": len(result.metric_rankings),
            "new_daily_files": result.new_daily_files,
            "orders_fetch_status": (meta.get("orders_fetch") or {}).get("status"),
        },
    )
    return result


__all__ = [
    "DEFAULT_RANKING",
    "RANKINGS",
    "DiagnosisBuildResult",
    "VideoMetricsFn",
    "assert_read_credential_for",
    "build_and_store_shop_diagnosis",
    "fetch_ranking_videos",
    "json_safe",
    "report_end_date",
]
