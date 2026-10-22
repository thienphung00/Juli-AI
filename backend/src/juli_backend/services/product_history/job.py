"""Daily product snapshot + promotion sweep, and the webhook-driven refreshes (D30.1, D30.4).

TikTok is only ever READ here, through the shop's own read credential
(``resolve_read_credential_for_shop``, checked like the diagnosis job) and the
``ProductionReadClientFactory`` resources; with a ``rate_limiter`` every read
first takes a token from the poll path's shared Redis window
(``shop_diagnosis_daily.pacing``). Throttled reads back off (``with_backoff``).
No database session is open while TikTok is called.

``reconcile_products`` (daily):
    1. Search Products (all statuses, 100 per page) -- every row carries its
       ``update_time`` and SKU prices.
    2. A product is re-read (Get Product) when it has no snapshot yet, its
       ``update_time`` moved past the snapshot's, or its listed SKU prices differ
       from the snapshot's (a price change may not move ``update_time``; there is
       no price webhook). At most ``max_details`` reads per run; the rest are
       still "changed" tomorrow.
    3. Each read is stored when its state changed (``store.record_read``), and
       what changed is recorded in ``external_changes`` (``juli_write`` when it
       matched Juli's own write). The shop's first run is the full baseline: one
       snapshot per product, no change rows.

``sweep_promotions`` (daily, after the products):
    Search Activities for every status, upsert them, and read the products of
    the ones never read or updated since (Get Activity). The shop's first sweep
    is the one-time backfill (a larger detail budget). An activity first seen on
    a later sweep, or newly DEACTIVATED, is recorded as a ``promotion`` change
    (the webhook 63 / 39 path usually got there first: same dedup key).

``refresh_product`` / ``refresh_activity`` (webhooks 15 / 16 / 18, 63 / 39):
    one Get Product / Get Activity, then the same recording.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import resolve_read_credential_for_shop
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    is_own_shop_sandbox_read,
)
from juli_backend.models.history import (
    KIND_CREATION,
    KIND_PROMOTION,
    SOURCE_RECONCILE,
    ProductSnapshot,
    PromotionActivity,
)
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories import utc_now_naive
from juli_backend.services.product_history import promotions as promo
from juli_backend.services.product_history.normalize import (
    epoch_to_naive_utc,
    list_prices,
    normalize_detail,
    prices_moved,
    snapshot_prices,
)
from juli_backend.services.product_history.store import (
    latest_snapshots,
    record_change,
    record_read,
)
from juli_backend.services.shop_diagnosis_daily.fetch import with_backoff
from juli_backend.services.shop_diagnosis_daily.job import assert_read_credential_for
from juli_backend.services.shop_diagnosis_daily.pacing import (
    RateLimitedResources,
    SharedWindowGate,
)

logger = logging.getLogger(__name__)

ResolveCredentialFn = Callable[[AsyncSession, uuid.UUID], Awaitable[TikTokCredential]]
CreateResourcesFn = Callable[[ClientFactoryConfig], Any]
SessionFactory = Callable[[], Any]
Sleep = Callable[[float], Any]

SEARCH_PAGE_SIZE = 100
#: Get Product reads per daily run (the first run's baseline uses the larger one).
MAX_DETAIL_READS = 150
BASELINE_MAX_DETAIL_READS = 600
#: Get Activity reads per daily sweep (the one-time backfill uses the larger one).
MAX_ACTIVITY_DETAILS = 100
BACKFILL_MAX_ACTIVITY_DETAILS = 400


@dataclass(frozen=True)
class ReadPlan:
    config: ClientFactoryConfig
    #: The rate-limit key the poll uses for this shop.
    shop_key: str


async def plan_reads(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    *,
    app_key: str,
    app_secret: str,
    resolve: ResolveCredentialFn | None = None,
) -> ReadPlan:
    """Resolve and check the shop's read credential (``ValueError`` when unusable)."""
    resolver = resolve or resolve_read_credential_for_shop
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            credential = await resolver(session, shop_id)
            assert_read_credential_for(credential, shop_id)
            shop = await session.get(Shop, shop_id)
            if shop is None:
                raise ValueError(f"product history: shop {shop_id} not found")
            plan = ReadPlan(
                config=ClientFactoryConfig(
                    app_key=app_key,
                    app_secret=app_secret,
                    access_token=credential.access_token,
                    merchant_auth_id=str(credential.merchant_authorization_id),
                    shop_cipher=credential.shop_cipher,
                    credential_capability=credential.capability,
                    own_shop_sandbox_read=is_own_shop_sandbox_read(
                        credential.capability,
                        credential_shop_id=credential.shop_id,
                        shop_id=shop_id,
                    ),
                ),
                shop_key=shop.tiktok_shop_id or str(shop_id),
            )
        await session.commit()
    return plan


def build_resources(
    plan: ReadPlan,
    *,
    app_key: str,
    create_resources: CreateResourcesFn | None = None,
    rate_limiter: Any | None = None,
    rate_limit_sleep: Sleep = time.sleep,
) -> Any:
    build = create_resources or ProductionReadClientFactory().create_resources
    resources = build(plan.config)
    if rate_limiter is None:
        return resources
    return RateLimitedResources(
        resources,
        SharedWindowGate(
            rate_limiter, app_id=app_key, shop_key=plan.shop_key, sleep=rate_limit_sleep
        ),
    )


# -- products ------------------------------------------------------------------------------


@dataclass
class ProductsResult:
    listed: int = 0
    to_read: int = 0
    read: int = 0
    failed: int = 0
    snapshots: int = 0
    changes: int = 0
    baseline: bool = False
    deferred: int = 0


def _changed(item: Mapping[str, Any], previous: ProductSnapshot | None) -> bool:
    if previous is None:
        return True
    try:
        listed_update = int(str(item.get("update_time") or 0))
    except ValueError:
        listed_update = 0
    if previous.tiktok_update_time is None or listed_update > previous.tiktok_update_time:
        return True
    return prices_moved(list_prices(item), snapshot_prices(previous.skus))


def _read_details(
    resources: Any, product_ids: Sequence[str], backoff_sleep: Sleep
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    details: dict[str, dict[str, Any]] = {}
    failed: dict[str, str] = {}
    for pid in product_ids:
        try:
            body = with_backoff(partial(resources.products.get_details, pid), backoff_sleep)
        except Exception as exc:
            failed[pid] = type(exc).__name__
            continue
        if isinstance(body, Mapping):
            details[pid] = dict(body)
    return details, failed


async def _first_snapshot_at(session: AsyncSession, shop_id: uuid.UUID) -> datetime | None:
    result = await session.execute(
        select(func.min(ProductSnapshot.taken_at)).where(ProductSnapshot.shop_id == shop_id)
    )
    value = result.scalar_one_or_none()
    return value if isinstance(value, datetime) else None


async def reconcile_products(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    resources: Any,
    *,
    now: datetime | None = None,
    max_details: int | None = None,
    backoff_sleep: Sleep = time.sleep,
) -> ProductsResult:
    """The daily ``update_time`` / price reconciliation (see module doc)."""
    result = ProductsResult()
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            latest = await latest_snapshots(session, shop_id)
            first_at = await _first_snapshot_at(session, shop_id)
        await session.commit()
    result.baseline = not latest

    listed: list[dict[str, Any]] = await asyncio.to_thread(
        with_backoff,
        partial(resources.products.search_all, page_size=SEARCH_PAGE_SIZE),
        backoff_sleep,
    )
    result.listed = len(listed)
    by_id = {str(item.get("id")): item for item in listed if isinstance(item, Mapping)}
    changed = [pid for pid, item in by_id.items() if pid and _changed(item, latest.get(pid))]
    budget = max_details or (BASELINE_MAX_DETAIL_READS if result.baseline else MAX_DETAIL_READS)
    result.to_read = len(changed)
    result.deferred = max(0, len(changed) - budget)
    to_read = changed[:budget]

    details, failed = await asyncio.to_thread(_read_details, resources, to_read, backoff_sleep)
    result.read, result.failed = len(details), len(failed)
    if failed:
        logger.warning(
            "product_history_detail_failed",
            extra={"shop_id": str(shop_id), "failed": len(failed)},
        )

    moment = now or utc_now_naive()
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            for pid, body in details.items():
                try:
                    new = normalize_detail(body, product_id=pid)
                except ValueError:
                    continue
                previous = latest.get(pid)
                created = epoch_to_naive_utc(by_id.get(pid, {}).get("create_time"))
                # No snapshot yet: part of the baseline unless the product was
                # created after the shop's baseline (then it is a "creation").
                baseline = previous is None and (
                    result.baseline or first_at is None or created is None or created < first_at
                )
                outcome = await record_read(
                    session,
                    shop_id=shop_id,
                    new=new,
                    previous=previous,
                    source=SOURCE_RECONCILE,
                    now=moment,
                    baseline=baseline,
                    hint_kind=KIND_CREATION,
                )
                result.snapshots += 1 if outcome.snapshot is not None else 0
                result.changes += len(outcome.changes)
        await session.commit()
    logger.info(
        "product_history_reconciled",
        extra={"shop_id": str(shop_id), **result.__dict__},
    )
    return result


async def refresh_product(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    resources: Any,
    *,
    product_id: str,
    source: str,
    hint_kind: str,
    hint_fields: Sequence[str] = (),
    now: datetime | None = None,
    backoff_sleep: Sleep = time.sleep,
) -> int:
    """Webhook 15 / 16 / 18: re-read one product and record what changed. Returns changes."""
    details, failed = await asyncio.to_thread(_read_details, resources, [product_id], backoff_sleep)
    body = details.get(product_id)
    if body is None:
        logger.warning(
            "product_history_refresh_failed",
            extra={"shop_id": str(shop_id), "product_id": product_id, "error": failed},
        )
        return 0
    new = normalize_detail(body, product_id=product_id)
    moment = now or utc_now_naive()
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            previous = (await latest_snapshots(session, shop_id, [product_id])).get(product_id)
            outcome = await record_read(
                session,
                shop_id=shop_id,
                new=new,
                previous=previous,
                source=source,
                now=moment,
                hint_kind=hint_kind,
                hint_fields=hint_fields,
            )
        await session.commit()
    return len(outcome.changes)


# -- promotions ----------------------------------------------------------------------------


@dataclass
class PromotionsResult:
    activities: int = 0
    details_read: int = 0
    details_failed: int = 0
    changes: int = 0
    backfill: bool = False
    status_errors: list[str] = field(default_factory=list)
    #: Activity ids whose row could not be stored (logged, skipped; P58-A).
    skipped: list[str] = field(default_factory=list)


def _search_every_status(
    resources: Any, backoff_sleep: Sleep
) -> tuple[list[dict[str, Any]], list[str]]:
    seen: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for status in promo.ACTIVITY_STATUSES:
        try:
            found = with_backoff(
                partial(resources.promotion.search_activities_all, status=status), backoff_sleep
            )
        except Exception:
            errors.append(status)
            continue
        for activity in found or []:
            if isinstance(activity, Mapping) and promo.activity_id_of(activity):
                seen.setdefault(promo.activity_id_of(activity), dict(activity))
    return list(seen.values()), errors


def _read_activities(
    resources: Any, activity_ids: Sequence[str], backoff_sleep: Sleep
) -> tuple[dict[str, dict[str, Any]], int]:
    details: dict[str, dict[str, Any]] = {}
    failed = 0
    for activity_id in activity_ids:
        try:
            body = with_backoff(
                partial(resources.promotion.get_activity, activity_id), backoff_sleep
            )
        except Exception:
            failed += 1
            continue
        if isinstance(body, Mapping):
            details[activity_id] = dict(body)
    return details, failed


async def _record_promotion_change(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    activity_id: str,
    change_type: str,
    product_ids: Sequence[str],
    occurred_at: datetime,
    now: datetime,
    source: str,
    details: Mapping[str, Any],
) -> int:
    """One ``promotion`` row per affected product (one shop-level row when none is known)."""
    juli = await promo.is_juli_activity(session, shop_id, activity_id)
    fields = promo.change_fields(details.get("activity_type"), change_type, details.get("status"))
    epoch = calendar.timegm(occurred_at.timetuple()) if change_type == promo.CHANGE_UPDATE else 0
    count = 0
    targets: list[str | None] = list(product_ids) or [None]
    for pid in targets:
        row = await record_change(
            session,
            shop_id=shop_id,
            tiktok_product_id=pid,
            kind=KIND_PROMOTION,
            fields=fields,
            occurred_at=occurred_at,
            detected_at=now,
            source=source,
            juli_write=juli,
            details={"activity_id": activity_id, **details},
            dedup_key=f"promo:{activity_id}:{change_type}:{epoch}:{pid or 'shop'}",
        )
        count += 1 if row is not None else 0
    return count


async def _record_listed_change(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    activity_id: str,
    change_type: str,
    product_ids: Sequence[str],
    now: datetime,
) -> int:
    """The daily sweep's CREATE / DEACTIVATE row(s) for one activity it stored."""
    row = (
        await session.execute(
            select(PromotionActivity).where(
                PromotionActivity.shop_id == shop_id,
                PromotionActivity.activity_id == activity_id,
            )
        )
    ).scalar_one()
    occurred = (
        row.tiktok_update_time if change_type == promo.CHANGE_DEACTIVATE else row.tiktok_create_time
    ) or now
    return await _record_promotion_change(
        session,
        shop_id,
        activity_id=activity_id,
        change_type=change_type,
        product_ids=product_ids,
        occurred_at=occurred,
        now=now,
        source=SOURCE_RECONCILE,
        details={"activity_type": row.activity_type, "status": row.status},
    )


def _skip_activity(
    result: PromotionsResult, shop_id: uuid.UUID, activity_id: str, stage: str, exc: Exception
) -> None:
    if activity_id not in result.skipped:
        result.skipped.append(activity_id)
    logger.warning(
        "product_history_promotion_skipped",
        extra={
            "shop_id": str(shop_id),
            "activity_id": activity_id,
            "stage": stage,
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        },
    )


async def sweep_promotions(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    resources: Any,
    *,
    now: datetime | None = None,
    backoff_sleep: Sleep = time.sleep,
    force_backfill: bool = False,
) -> PromotionsResult:
    """The daily activity sweep; the shop's first one is the one-time backfill."""
    result = PromotionsResult()
    activities, result.status_errors = await asyncio.to_thread(
        _search_every_status, resources, backoff_sleep
    )
    result.activities = len(activities)
    moment = now or utc_now_naive()

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            stored = {
                row.activity_id: row
                for row in (
                    await session.execute(
                        select(PromotionActivity).where(PromotionActivity.shop_id == shop_id)
                    )
                ).scalars()
            }
            result.backfill = force_backfill or not stored
            new_ids: list[str] = []
            deactivated_ids: list[str] = []
            wanted: list[str] = []
            for raw in activities:
                activity_id = promo.activity_id_of(raw)
                before = stored.get(activity_id)
                was_deactivated = before is not None and before.status == promo.DEACTIVATED
                listed_update = epoch_to_naive_utc(raw.get("update_time"))
                try:
                    # One bad activity must not lose the shop's whole sweep (P58-A).
                    async with session.begin_nested():
                        row = await promo.upsert_activity(session, shop_id, raw, now=moment)
                except Exception as exc:
                    _skip_activity(result, shop_id, activity_id, "listed", exc)
                    continue
                if row is None:
                    continue
                if before is None:
                    new_ids.append(activity_id)
                elif not was_deactivated and row.status == promo.DEACTIVATED:
                    deactivated_ids.append(activity_id)
                if before is None or promo.needs_detail(before, listed_update=listed_update):
                    wanted.append(activity_id)
        await session.commit()

    budget = BACKFILL_MAX_ACTIVITY_DETAILS if result.backfill else MAX_ACTIVITY_DETAILS
    details, result.details_failed = await asyncio.to_thread(
        _read_activities, resources, wanted[:budget], backoff_sleep
    )
    result.details_read = len(details)

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            products: dict[str, list[str]] = {}
            for activity_id, body in details.items():
                try:
                    async with session.begin_nested():
                        await promo.upsert_activity(
                            session, shop_id, {"id": activity_id, **body}, now=moment
                        )
                        products[activity_id] = await promo.upsert_activity_products(
                            session, shop_id, activity_id, body, now=moment
                        )
                except Exception as exc:
                    _skip_activity(result, shop_id, activity_id, "detail", exc)
            if not result.backfill:
                for change_type, ids in (
                    (promo.CHANGE_CREATE, new_ids),
                    (promo.CHANGE_DEACTIVATE, deactivated_ids),
                ):
                    for activity_id in ids:
                        try:
                            async with session.begin_nested():
                                result.changes += await _record_listed_change(
                                    session,
                                    shop_id,
                                    activity_id=activity_id,
                                    change_type=change_type,
                                    product_ids=products.get(activity_id, []),
                                    now=moment,
                                )
                        except Exception as exc:
                            _skip_activity(result, shop_id, activity_id, "change", exc)
        await session.commit()
    logger.info(
        "product_history_promotions_swept",
        extra={"shop_id": str(shop_id), **result.__dict__},
    )
    return result


async def refresh_activity(
    session_factory: SessionFactory,
    shop_id: uuid.UUID,
    resources: Any,
    *,
    change: promo.ActivityChange,
    source: str,
    now: datetime | None = None,
    backoff_sleep: Sleep = time.sleep,
) -> int:
    """Webhook 63 / 39: re-read the activity, upsert it, record the change. Returns rows."""
    details, _ = await asyncio.to_thread(
        _read_activities, resources, [change.activity_id], backoff_sleep
    )
    body = details.get(change.activity_id)
    moment = now or utc_now_naive()
    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            listed: list[str] = []
            raw: dict[str, Any] = {"id": change.activity_id, **(body or {})}
            if change.status and not raw.get("status"):
                raw["status"] = change.status
            if change.change_type == promo.CHANGE_DEACTIVATE and not raw.get("status"):
                raw["status"] = promo.DEACTIVATED
            row = await promo.upsert_activity(session, shop_id, raw, now=moment)
            if body is not None:
                listed = await promo.upsert_activity_products(
                    session, shop_id, change.activity_id, body, now=moment
                )
            await promo.mark_products_removed(
                session, shop_id, change.activity_id, change.removed_products, now=moment
            )
            affected = list(dict.fromkeys(change.updated_products + change.removed_products))
            if not affected and change.change_type == promo.CHANGE_CREATE:
                affected = listed
            occurred = (
                change.occurred_at
                or (row.tiktok_update_time if row is not None else None)
                or moment
            )
            count = await _record_promotion_change(
                session,
                shop_id,
                activity_id=change.activity_id,
                change_type=change.change_type,
                product_ids=affected,
                occurred_at=occurred,
                now=moment,
                source=source,
                details={
                    "activity_type": row.activity_type if row is not None else None,
                    "status": row.status if row is not None else change.status,
                    "products_updated": change.updated_products,
                    "products_removed": change.removed_products,
                },
            )
        await session.commit()
    return count


__all__ = [
    "BACKFILL_MAX_ACTIVITY_DETAILS",
    "MAX_ACTIVITY_DETAILS",
    "MAX_DETAIL_READS",
    "ProductsResult",
    "PromotionsResult",
    "ReadPlan",
    "build_resources",
    "plan_reads",
    "reconcile_products",
    "refresh_activity",
    "refresh_product",
    "sweep_promotions",
]
