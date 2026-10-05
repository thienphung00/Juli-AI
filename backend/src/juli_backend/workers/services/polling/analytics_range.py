"""Date-range analytics with bounded-parallel detail calls (fast track SPEC §3.3–3.5).

``sync.py::sync_analytics`` fetches one fixed day, ``[yesterday, today)``,
every fifteen minutes, with one serial detail call per SKU and per product.
This module is the range-shaped replacement the per-shop scheduler, the
bootstrap fast phase and the history phase share:

- **date range** (§3.4): A-31 SKU detail, A-33 product detail and A-36 shop
  performance take ``start_date_ge`` / ``end_date_lt`` and answer with daily
  ``intervals[]`` -- one call per product per range, not per day. A range
  longer than ``TIKTOK_ANALYTICS_MAX_RANGE_DAYS`` is split into windows.
- **bounded parallelism** (§3.5): the per-product / per-SKU detail calls run
  ``TIKTOK_ANALYTICS_DETAIL_CONCURRENCY`` at a time (default 5). The vendor
  client is synchronous ``requests``, so each call runs in a worker thread via
  ``asyncio.to_thread`` (which copies the context, so the enclosing
  ``pagination_scope`` budget travels with it). Everything that touches the
  database -- the ETL handoff -- runs back on the event loop, one row at a
  time, in the consuming coroutine: the ``AsyncSession`` is never shared across
  threads or used concurrently.
- **rate limiter**: every vendor call still goes through ``_acquire`` (the
  per-endpoint Redis window), called on the event loop before the call is
  dispatched to a thread. When the window is exhausted the caller either backs
  off until it resets (``wait_on_rate_limit=True``) or stops issuing detail
  calls for that endpoint group, as ``sync_analytics`` always has.
- **cycle budget**: ``deadline.check`` runs before every detail call, so an
  exhausted budget stops new calls and raises ``PollCycleTimeoutError``; calls
  already in a thread finish (``requests`` cannot be preempted) and their
  results are discarded.

ROWS THAT ARE NOT DAILY ARE NEVER STORED. If the vendor answers a multi-day
request with one aggregate interval instead of daily ones, writing it would put
a 30-day total into a column every reader treats as one day. Such rows are
dropped and counted (``non_daily_rows_dropped``, logged at ERROR); for A-36 the
window is then re-fetched one day at a time, which is cheap (one call per day).
The A-32 / A-34 list rows (aggregates over the requested window by definition)
are handed off only for single-day windows, preserving ``sync_analytics``'s
fallback semantics there.

PRODUCT LIST ROW (A-34) MERGE HOOK. P1-A adds
``merge_product_analytics_rows(detail_rows, list_row)`` in
``integrations/tiktok/mapping.py`` so ``conversion_rate`` (from the list row's
``click_order_rate``) lands on the same product-grain row as the detail
metrics. The list row covers the WHOLE requested window, so it can only be
merged into a detail row when the window is a single day; multi-day windows
(fast phase, history, a catch-up after a gap) leave CVR to the daily
incremental pass. ``_merge_product_list_row`` resolves that function at call
time and is a no-op until it exists on this branch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Protocol

from juli_backend.integrations.tiktok import (
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    AuthenticationError,
    PermissionDeniedError,
    RateLimiter,
    RateLimitError,
    TikTokAPIError,
    TikTokSystemError,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    expand_analytics_live_session,
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    expand_analytics_shop_performance,
    expand_analytics_shop_performance_per_hour,
    expand_analytics_sku_detail,
    expand_analytics_sku_list_item,
)
from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.workers.services.polling.sync import (
    SyncOutcome,
    _acquire,
    _handoff_analytics_rows,
    _StepRun,
)

logger = logging.getLogger(__name__)

DETAIL_CONCURRENCY_ENV = "TIKTOK_ANALYTICS_DETAIL_CONCURRENCY"
_DEFAULT_DETAIL_CONCURRENCY = 5
MAX_RANGE_DAYS_ENV = "TIKTOK_ANALYTICS_MAX_RANGE_DAYS"
_DEFAULT_MAX_RANGE_DAYS = 30
#: How many backoff waits one call may spend on an exhausted window before the
#: caller gives up on it. Bounds a limiter whose TTL never resets.
_MAX_RATE_LIMIT_WAITS = 30

SleepFn = Callable[[float], Awaitable[None]]
MergeListRowFn = Callable[[list[dict[str, Any]], dict[str, Any] | None], list[dict[str, Any]]]

_DAILY_GRAINS = frozenset({"shop", "product", "sku"})
_ACTIVITY_METRICS = ("gmv", "orders_count", "items_sold", "sku_orders", "visitors", "customers")


def detail_concurrency() -> int:
    """Bounded pool size for per-product / per-SKU detail calls."""
    try:
        value = int(os.getenv(DETAIL_CONCURRENCY_ENV, str(_DEFAULT_DETAIL_CONCURRENCY)))
    except ValueError:
        value = _DEFAULT_DETAIL_CONCURRENCY
    return max(1, value)


def max_range_days() -> int:
    """The longest window one detail call is asked for."""
    try:
        value = int(os.getenv(MAX_RANGE_DAYS_ENV, str(_DEFAULT_MAX_RANGE_DAYS)))
    except ValueError:
        value = _DEFAULT_MAX_RANGE_DAYS
    return max(1, value)


class DeadlineLike(Protocol):
    """The slice of ``orchestrate._CycleDeadline`` this module needs."""

    def check(self, *, stage: str) -> float: ...


def parse_vendor_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _merge_product_list_row(
    detail_rows: list[dict[str, Any]], list_row: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Merge the A-34 list row into the A-33 detail rows (P1-A hook).

    Resolved at call time so this branch neither copies nor depends on P1-A's
    function: until ``merge_product_analytics_rows`` exists in
    ``integrations/tiktok/mapping.py`` this returns ``detail_rows`` unchanged.
    """
    if list_row is None or not detail_rows:
        return detail_rows
    from juli_backend.integrations.tiktok import mapping as _mapping

    merge = getattr(_mapping, "merge_product_analytics_rows", None)
    if merge is None:
        return detail_rows
    return list(merge(detail_rows, list_row))


@dataclass
class AnalyticsRangeResult:
    """What one range pass did, beyond the step's outcome triple."""

    outcome: SyncOutcome
    start: date
    end_exclusive: date
    latest_available_date: date | None = None
    detail_calls: int = 0
    list_calls: int = 0
    listed_products: int = 0
    listed_skus: int = 0
    shop_activity: bool = False
    rate_limited: bool = False
    list_failed: bool = False
    out_of_range: bool = False
    non_daily_rows_dropped: int = 0
    days_with_rows: set[str] = field(default_factory=set)

    @property
    def has_data(self) -> bool:
        """Did TikTok return anything for this range at all?"""
        return bool(self.listed_products or self.listed_skus or self.shop_activity)

    @property
    def complete(self) -> bool:
        """Every list endpoint answered and no detail call was refused.

        A detail call that failed with a vendor error for one product is not
        incompleteness -- it is logged and the product falls back -- but a
        rate-limit refusal is: a cursor must not advance past a window whose
        calls were never made.
        """
        return not (self.rate_limited or self.list_failed or self.out_of_range)


@dataclass
class _Counters:
    detail_calls: int = 0
    list_calls: int = 0
    rate_limited: bool = False
    non_daily: int = 0
    latest: date | None = None
    days: set[str] = field(default_factory=set)
    last_error: BaseException | None = None

    def see_latest(self, response: Any) -> None:
        if isinstance(response, dict):
            seen = parse_vendor_date(response.get("latest_available_date"))
            if seen is not None and (self.latest is None or seen > self.latest):
                self.latest = seen


def _is_daily(row: dict[str, Any]) -> bool:
    if row.get("grain") not in _DAILY_GRAINS or row.get("hour_index") is not None:
        return True
    start = parse_vendor_date(row.get("start_date"))
    end = parse_vendor_date(row.get("end_date"))
    if start is None or end is None:
        return True
    return (end - start).days == 1


def _daily_only(rows: Iterable[dict[str, Any]], counters: _Counters, *, source: str) -> list[dict]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        if _is_daily(row):
            kept.append(row)
            if row.get("grain") in _DAILY_GRAINS and row.get("start_date"):
                counters.days.add(str(row["start_date"])[:10])
        else:
            counters.non_daily += 1
            logger.error(
                "analytics_range_non_daily_row_dropped",
                extra={
                    "source": source,
                    "grain": row.get("grain"),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                },
            )
    return kept


def _has_activity(rows: Iterable[dict[str, Any]]) -> bool:
    for row in rows:
        for key in _ACTIVITY_METRICS:
            value = row.get(key)
            try:
                if value is not None and float(value) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


async def acquire_or_wait(
    rate_limiter: RateLimiter,
    *,
    app_id: str,
    shop_id: str,
    endpoint: str,
    sleep: SleepFn,
    wait: bool,
    deadline: DeadlineLike | None = None,
    stage: str = "analytics",
) -> bool:
    """``_acquire``, optionally backing off until the window resets.

    Returns False when the window stays exhausted (``wait=False``, or the
    backoff allowance is spent). Raises ``PollCycleTimeoutError`` through
    ``deadline.check`` if the cycle budget runs out while waiting.
    """
    waits = 0
    while True:
        if _acquire(rate_limiter, app_id=app_id, shop_id=shop_id, endpoint=endpoint):
            return True
        if not wait or waits >= _MAX_RATE_LIMIT_WAITS:
            logger.info(
                "analytics_range_rate_limited",
                extra={"shop_id": shop_id, "endpoint": endpoint, "waits": waits},
            )
            return False
        if deadline is not None:
            deadline.check(stage=stage)
        try:
            ttl = float(rate_limiter.time_until_reset(app_id, shop_id, endpoint))
        except Exception:
            ttl = 1.0
        waits += 1
        logger.info(
            "rate_limit_backoff",
            extra={"shop_id": shop_id, "endpoint": endpoint, "seconds": max(ttl, 1.0)},
        )
        await sleep(max(ttl, 1.0))


async def _run_bounded(
    items: list[Any],
    worker: Callable[[Any], Awaitable[Any]],
    handle: Callable[[Any], Awaitable[None]],
    *,
    concurrency: int,
) -> None:
    """Run ``worker`` over ``items`` at most ``concurrency`` at a time.

    ``handle`` is awaited for each result in completion order, sequentially, in
    THIS coroutine -- the only place results reach the database. Any exception
    (a budget timeout, a non-vendor error) cancels everything not yet started.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(item: Any) -> Any:
        async with semaphore:
            return await worker(item)

    tasks = [asyncio.ensure_future(guarded(item)) for item in items]
    try:
        for next_done in asyncio.as_completed(tasks):
            await handle(await next_done)
    finally:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # Mark every finished task's exception as retrieved: after the first
        # failure the rest are siblings of an error already propagating, and
        # asyncio would otherwise log each as "never retrieved".
        for task in tasks:
            if task.done() and not task.cancelled():
                task.exception()


_SKIPPED = object()


async def _detail_fan_out(
    listed: list[dict[str, Any]],
    *,
    kind: str,
    path_for: Callable[[str], str],
    call: Callable[[str], Any],
    on_result: Callable[[str, dict[str, Any], Any], Awaitable[None]],
    rate_limiter: RateLimiter,
    app_id: str,
    shop_id: str,
    sleep: SleepFn,
    wait_on_rate_limit: bool,
    deadline: DeadlineLike | None,
    concurrency: int,
    counters: _Counters,
) -> None:
    """Fetch one detail per listed item, bounded, and hand each result back."""
    stopped = False

    async def worker(item: dict[str, Any]) -> tuple[str, dict[str, Any], Any]:
        nonlocal stopped
        item_id = str(item["id"])
        if stopped:
            return item_id, item, _SKIPPED
        if deadline is not None:
            deadline.check(stage="analytics")
        acquired = await acquire_or_wait(
            rate_limiter,
            app_id=app_id,
            shop_id=shop_id,
            endpoint=path_for(item_id),
            sleep=sleep,
            wait=wait_on_rate_limit,
            deadline=deadline,
        )
        if not acquired:
            stopped = True
            counters.rate_limited = True
            return item_id, item, _SKIPPED
        counters.detail_calls += 1
        try:
            return item_id, item, await asyncio.to_thread(call, item_id)
        except TikTokAPIError as exc:
            return item_id, item, exc

    async def handle(result: tuple[str, dict[str, Any], Any]) -> None:
        item_id, item, response = result
        if isinstance(response, TikTokAPIError):
            logger.warning(
                f"sync_analytics_{kind}_detail_failed",
                extra={"shop_id": shop_id, f"{kind}_id": item_id, "error": str(response)[:200]},
            )
        else:
            counters.see_latest(response)
        await on_result(item_id, item, response)

    eligible = [item for item in listed if isinstance(item, dict) and item.get("id")]
    await _run_bounded(eligible, worker, handle, concurrency=concurrency)


async def _list_call(
    fetch: Callable[[], Any],
    *,
    endpoint: str,
    label: str,
    rate_limiter: RateLimiter,
    app_id: str,
    shop_id: str,
    sleep: SleepFn,
    wait_on_rate_limit: bool,
    deadline: DeadlineLike | None,
    counters: _Counters,
) -> tuple[Any, BaseException | None, bool]:
    """One list / shop-level call. Returns (response, vendor_error, refused)."""
    if deadline is not None:
        deadline.check(stage="analytics")
    acquired = await acquire_or_wait(
        rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        endpoint=endpoint,
        sleep=sleep,
        wait=wait_on_rate_limit,
        deadline=deadline,
    )
    if not acquired:
        counters.rate_limited = True
        return None, None, True
    counters.list_calls += 1
    try:
        response = await asyncio.to_thread(fetch)
    except TikTokAPIError as exc:
        logger.warning(
            f"sync_analytics_{label}_failed",
            extra={"shop_id": shop_id, "error": str(exc)[:200]},
        )
        counters.last_error = exc
        return None, exc, False
    counters.see_latest(response)
    return response, None, False


def _by_id(
    method: Callable[..., Any], id_param: str, start_ge: str, end_lt: str
) -> Callable[[str], Any]:
    """A one-argument detail call for one window, bound without a lambda."""

    def call(item_id: str) -> Any:
        return method(**{id_param: item_id, "start_date_ge": start_ge, "end_date_lt": end_lt})

    return call


def _window_strings(start: date, end_exclusive: date) -> tuple[str, str]:
    return start.isoformat(), end_exclusive.isoformat()


def iter_windows(start: date, end_exclusive: date, span_days: int) -> list[tuple[date, date]]:
    """Split ``[start, end_exclusive)`` into windows no longer than ``span_days``."""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor < end_exclusive:
        window_end = min(cursor + timedelta(days=span_days), end_exclusive)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


async def sync_analytics_range(
    *,
    resource: Any,
    rate_limiter: RateLimiter,
    handoff_fn: HandoffFn,
    app_id: str,
    shop_id: str,
    start: date,
    end_exclusive: date,
    sleep: SleepFn = asyncio.sleep,
    deadline: DeadlineLike | None = None,
    concurrency: int | None = None,
    wait_on_rate_limit: bool = True,
    include_per_day_extras: bool = False,
    out_of_range_is_end: bool = False,
    synced_at: int | None = None,
    raise_on_dropped: bool = True,
) -> AnalyticsRangeResult:
    """Fetch SKU, product and shop analytics for ``[start, end_exclusive)``.

    ``include_per_day_extras`` adds the per-day endpoints (A-28 LIVE sessions
    and A-37 per-hour) for every day in the range -- the daily cadence wants
    them, the fast and history phases do not.

    ``out_of_range_is_end`` (history phase): a non-transient, non-auth vendor
    error on a list / shop-level call means "TikTok will not serve this far
    back", recorded as ``out_of_range`` rather than a failure.
    """
    pool = concurrency or detail_concurrency()
    stamp = synced_at if synced_at is not None else int(time.time())
    counters = _Counters()
    listed_products = 0
    listed_skus = 0
    shop_activity = False
    list_failed = False
    out_of_range = False

    with _StepRun("analytics", shop_id, backfill=False, handoff_fn=handoff_fn) as step:
        handoff = step.handoff

        for window_start, window_end in iter_windows(start, end_exclusive, max_range_days()):
            start_ge, end_lt = _window_strings(window_start, window_end)
            single_day = (window_end - window_start).days == 1

            # -- A-32 SKU list -> A-31 SKU detail ---------------------------------
            skus, error, refused = await _list_call(
                partial(
                    resource.list_sku_performance_all, start_date_ge=start_ge, end_date_lt=end_lt
                ),
                endpoint=ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
                label="sku_list",
                rate_limiter=rate_limiter,
                app_id=app_id,
                shop_id=shop_id,
                sleep=sleep,
                wait_on_rate_limit=wait_on_rate_limit,
                deadline=deadline,
                counters=counters,
            )
            if error is not None and out_of_range_is_end and _is_out_of_range(error):
                out_of_range = True
                break
            if error is not None or refused:
                list_failed = list_failed or error is not None
            if isinstance(skus, list):
                listed_skus += len(skus)

                async def on_sku(
                    sku_id: str,
                    item: dict[str, Any],
                    response: Any,
                    s: str = start_ge,
                    e: str = end_lt,
                    one_day: bool = single_day,
                ) -> None:
                    if isinstance(response, dict):
                        rows = _daily_only(
                            expand_analytics_sku_detail(response, synced_at=stamp),
                            counters,
                            source="sku_detail",
                        )
                        await _handoff_analytics_rows(handoff, shop_id, rows)
                        return
                    if one_day:
                        list_row = expand_analytics_sku_list_item(
                            item, start_date=s, end_date=e, synced_at=stamp
                        )
                        if list_row is not None:
                            await _handoff_analytics_rows(handoff, shop_id, [list_row])

                await _detail_fan_out(
                    skus,
                    kind="sku",
                    path_for=analytics_shop_sku_performance_path,
                    call=_by_id(resource.get_sku_performance, "sku_id", start_ge, end_lt),
                    on_result=on_sku,
                    rate_limiter=rate_limiter,
                    app_id=app_id,
                    shop_id=shop_id,
                    sleep=sleep,
                    wait_on_rate_limit=wait_on_rate_limit,
                    deadline=deadline,
                    concurrency=pool,
                    counters=counters,
                )

            # -- A-34 product list -> A-33 product detail -----------------------
            products, error, refused = await _list_call(
                partial(
                    resource.list_product_performance_all,
                    start_date_ge=start_ge,
                    end_date_lt=end_lt,
                ),
                endpoint=ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
                label="product_list",
                rate_limiter=rate_limiter,
                app_id=app_id,
                shop_id=shop_id,
                sleep=sleep,
                wait_on_rate_limit=wait_on_rate_limit,
                deadline=deadline,
                counters=counters,
            )
            if error is not None and out_of_range_is_end and _is_out_of_range(error):
                out_of_range = True
                break
            if error is not None:
                list_failed = True
            if isinstance(products, list):
                listed_products += len(products)

                async def on_product(
                    product_id: str,
                    item: dict[str, Any],
                    response: Any,
                    s: str = start_ge,
                    e: str = end_lt,
                    one_day: bool = single_day,
                ) -> None:
                    list_row = (
                        expand_analytics_product_list_item(
                            item, start_date=s, end_date=e, synced_at=stamp
                        )
                        if one_day
                        else None
                    )
                    if isinstance(response, dict):
                        rows = _daily_only(
                            expand_analytics_product_detail(
                                response, synced_at=stamp, product_id=product_id
                            ),
                            counters,
                            source="product_detail",
                        )
                        # One handoff per product per window: the detail rows,
                        # with the single-day list row merged in -- never the two
                        # handed off separately under the same `synced_at`, which
                        # the upsert's newer-only rule would collapse.
                        rows = _merge_product_list_row(rows, list_row)
                        await _handoff_analytics_rows(handoff, shop_id, rows)
                        return
                    if list_row is not None:
                        await _handoff_analytics_rows(handoff, shop_id, [list_row])

                await _detail_fan_out(
                    products,
                    kind="product",
                    path_for=analytics_shop_product_performance_path,
                    call=_by_id(resource.get_product_performance, "product_id", start_ge, end_lt),
                    on_result=on_product,
                    rate_limiter=rate_limiter,
                    app_id=app_id,
                    shop_id=shop_id,
                    sleep=sleep,
                    wait_on_rate_limit=wait_on_rate_limit,
                    deadline=deadline,
                    concurrency=pool,
                    counters=counters,
                )

            # -- A-36 shop performance -------------------------------------------
            shop_rows = await _shop_performance_rows(
                resource,
                window_start=window_start,
                window_end=window_end,
                stamp=stamp,
                rate_limiter=rate_limiter,
                app_id=app_id,
                shop_id=shop_id,
                sleep=sleep,
                wait_on_rate_limit=wait_on_rate_limit,
                deadline=deadline,
                counters=counters,
            )
            if shop_rows is None:
                shop_error = counters.last_error
                if out_of_range_is_end and shop_error is not None and _is_out_of_range(shop_error):
                    out_of_range = True
                    break
                list_failed = True
            else:
                shop_activity = shop_activity or _has_activity(shop_rows)
                await _handoff_analytics_rows(handoff, shop_id, shop_rows)

            # -- per-day extras (daily cadence only) -----------------------------
            if include_per_day_extras:
                await _per_day_extras(
                    resource,
                    window_start=window_start,
                    window_end=window_end,
                    stamp=stamp,
                    handoff=handoff,
                    rate_limiter=rate_limiter,
                    app_id=app_id,
                    shop_id=shop_id,
                    sleep=sleep,
                    deadline=deadline,
                    counters=counters,
                )

        step.fetched = step.handoff.offered
        outcome = step.report() if raise_on_dropped else step._report()

    result = AnalyticsRangeResult(
        outcome=outcome,
        start=start,
        end_exclusive=end_exclusive,
        latest_available_date=counters.latest,
        detail_calls=counters.detail_calls,
        list_calls=counters.list_calls,
        listed_products=listed_products,
        listed_skus=listed_skus,
        shop_activity=shop_activity,
        rate_limited=counters.rate_limited,
        list_failed=list_failed,
        out_of_range=out_of_range,
        non_daily_rows_dropped=counters.non_daily,
        days_with_rows=counters.days,
    )
    logger.info(
        "analytics_range_synced",
        extra={
            "shop_id": shop_id,
            "start_date_ge": start.isoformat(),
            "end_date_lt": end_exclusive.isoformat(),
            "detail_calls": result.detail_calls,
            "list_calls": result.list_calls,
            "listed_products": listed_products,
            "listed_skus": listed_skus,
            "days_with_rows": len(result.days_with_rows),
            "rate_limited": result.rate_limited,
            "out_of_range": out_of_range,
            "non_daily_rows_dropped": result.non_daily_rows_dropped,
            "persisted": outcome.persisted,
        },
    )
    return result


#: Vendor codes the client itself treats as transient (`client.py`
#: `_RETRYABLE_APP_CODES`). Restated rather than deep-imported: a transient
#: error must never be read as "TikTok has no data this far back".
_TRANSIENT_CODES = frozenset({100005, 100006, 36009003})


def _is_out_of_range(error: BaseException) -> bool:
    """A non-transient, non-auth vendor refusal: TikTok will not serve this far back.

    Auth and permission failures are real failures, and rate-limit / system
    errors are transient -- none of them may end the history walk.
    """
    if not isinstance(error, TikTokAPIError):
        return False
    if isinstance(
        error, (RateLimitError, TikTokSystemError, AuthenticationError, PermissionDeniedError)
    ):
        return False
    return error.code not in _TRANSIENT_CODES


async def _shop_performance_rows(
    resource: Any,
    *,
    window_start: date,
    window_end: date,
    stamp: int,
    rate_limiter: RateLimiter,
    app_id: str,
    shop_id: str,
    sleep: SleepFn,
    wait_on_rate_limit: bool,
    deadline: DeadlineLike | None,
    counters: _Counters,
) -> list[dict[str, Any]] | None:
    """A-36 over the window as daily rows, or ``None`` if a call failed.

    If the range answer is not daily (one aggregate interval), the window is
    re-fetched one day at a time.
    """
    start_ge, end_lt = _window_strings(window_start, window_end)
    response, error, refused = await _list_call(
        lambda: resource.get_shop_performance(start_date_ge=start_ge, end_date_lt=end_lt),
        endpoint=ANALYTICS_SHOP_PERFORMANCE_PATH,
        label="shop_performance",
        rate_limiter=rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        sleep=sleep,
        wait_on_rate_limit=wait_on_rate_limit,
        deadline=deadline,
        counters=counters,
    )
    if error is not None or refused:
        return None
    if not isinstance(response, dict):
        return []
    rows = expand_analytics_shop_performance(response, synced_at=stamp)
    if all(_is_daily(row) for row in rows):
        return _daily_only(rows, counters, source="shop_performance")
    if (window_end - window_start).days <= 1:
        return _daily_only(rows, counters, source="shop_performance")

    logger.warning(
        "analytics_range_shop_performance_not_daily",
        extra={"shop_id": shop_id, "start_date_ge": start_ge, "end_date_lt": end_lt},
    )
    daily: list[dict[str, Any]] = []
    for day_start, day_end in iter_windows(window_start, window_end, 1):
        day_rows = await _shop_performance_rows(
            resource,
            window_start=day_start,
            window_end=day_end,
            stamp=stamp,
            rate_limiter=rate_limiter,
            app_id=app_id,
            shop_id=shop_id,
            sleep=sleep,
            wait_on_rate_limit=wait_on_rate_limit,
            deadline=deadline,
            counters=counters,
        )
        if day_rows is None:
            return None
        daily.extend(day_rows)
    return daily


async def _per_day_extras(
    resource: Any,
    *,
    window_start: date,
    window_end: date,
    stamp: int,
    handoff: HandoffFn,
    rate_limiter: RateLimiter,
    app_id: str,
    shop_id: str,
    sleep: SleepFn,
    deadline: DeadlineLike | None,
    counters: _Counters,
) -> None:
    """A-28 LIVE sessions and A-37 per-hour, one call each per day.

    Both are labelled with the day they were requested for, so they are
    fetched per day rather than per range. Failures are logged and do not make
    the range incomplete: neither feeds the daily cursor.
    """
    for day_start, day_end in iter_windows(window_start, window_end, 1):
        start_ge, end_lt = _window_strings(day_start, day_end)
        sessions, _, _ = await _list_call(
            partial(resource.list_live_performance_all, start_date_ge=start_ge, end_date_lt=end_lt),
            endpoint=ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
            label="live_list",
            rate_limiter=rate_limiter,
            app_id=app_id,
            shop_id=shop_id,
            sleep=sleep,
            wait_on_rate_limit=False,
            deadline=deadline,
            counters=_Counters(),
        )
        if isinstance(sessions, list):
            live_rows = [
                row
                for row in (
                    expand_analytics_live_session(
                        session, start_date=start_ge, end_date=end_lt, synced_at=stamp
                    )
                    for session in sessions
                    if isinstance(session, dict)
                )
                if row is not None
            ]
            await _handoff_analytics_rows(handoff, shop_id, live_rows)

        per_hour, _, _ = await _list_call(
            partial(resource.get_shop_performance_per_hour, date=start_ge),
            endpoint=analytics_shop_performance_per_hour_path(start_ge),
            label="shop_performance_per_hour",
            rate_limiter=rate_limiter,
            app_id=app_id,
            shop_id=shop_id,
            sleep=sleep,
            wait_on_rate_limit=False,
            deadline=deadline,
            counters=_Counters(),
        )
        if isinstance(per_hour, dict):
            await _handoff_analytics_rows(
                handoff,
                shop_id,
                expand_analytics_shop_performance_per_hour(
                    per_hour, date=start_ge, synced_at=stamp
                ),
            )


async def probe_latest_available_date(
    resource: Any,
    *,
    rate_limiter: RateLimiter,
    app_id: str,
    shop_id: str,
    today: date,
    sleep: SleepFn = asyncio.sleep,
    deadline: DeadlineLike | None = None,
) -> date | None:
    """Ask TikTok which day its analytics are complete through.

    One A-36 call for ``[today - 1, today)`` -- the exact request the old
    every-15-minutes poll made, so it is known to be accepted -- read only for
    ``latest_available_date``. No detail call. ``None`` when the field is
    absent or the call fails; callers fall back to ``today - 1``.
    """
    counters = _Counters()
    start_ge, end_lt = _window_strings(today - timedelta(days=1), today)
    await _list_call(
        lambda: resource.get_shop_performance(start_date_ge=start_ge, end_date_lt=end_lt),
        endpoint=ANALYTICS_SHOP_PERFORMANCE_PATH,
        label="latest_available_probe",
        rate_limiter=rate_limiter,
        app_id=app_id,
        shop_id=shop_id,
        sleep=sleep,
        wait_on_rate_limit=True,
        deadline=deadline,
        counters=counters,
    )
    return counters.latest


def utc_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date()


__all__ = [
    "AnalyticsRangeResult",
    "DETAIL_CONCURRENCY_ENV",
    "MAX_RANGE_DAYS_ENV",
    "acquire_or_wait",
    "detail_concurrency",
    "iter_windows",
    "max_range_days",
    "parse_vendor_date",
    "probe_latest_available_date",
    "sync_analytics_range",
    "utc_today",
]
