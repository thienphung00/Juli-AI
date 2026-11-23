"""TikTok raw landing -> canonical rows, on every path that lands TikTok orders (P101 W2 t1).

Layer 1 (raw) is what TikTok returned, stored as today: the order search / detail payloads the
poll and the webhook's targeted fetch hand to the ETL (``silver.orders`` / ``order_items``; the
targeted fetch also keeps the payload in ``bronze.order_raw_payloads``), the returns
(``silver.returns``) and the finance transactions ``services/order_costs`` reads
(``order_finance_transactions``). Layer 2 is the pure mapper (:mod:`.tiktok_mapper`), layer 3 the
canonical tables, written only through :class:`~.canonical_writer.DbCanonicalWriter` (the same
upserts as the Shopee gateway: one writer, one precedence rule, ``rank_guard.ranked_set``).

Who calls what:

- the poll (``workers/services/polling``: ``run_shop_cycle``, the bootstrap fast phase, the manual
  ``_poll``) and the webhook's targeted fetch (``services/cdp_speed``) build one
  :class:`TikTokCanonicalSync` per job: ``on_orders`` maps the orders the job just fetched, in the
  same job; ``on_returns`` re-maps the orders whose lines a return changed; ``finish`` re-fetches
  by id (Get Order Detail, at most :data:`ORDER_DETAIL_MAX_IDS` ids a call) only the ids queued
  before the job (the nightly reconcile's gaps, a previous job's returned orders), queues the
  returned orders this job did not fetch for the next job, and maps the settlements of the
  finance rows read since the job started;
- the nightly reconcile (:func:`reconcile_shop`) compares, per VN day, the raw order count with
  the canonical one, re-maps a gap from its bronze payload when one exists and queues the rest
  (:class:`RefetchQueue`) for the next poll cycle. Lines are never built from ``silver`` alone:
  it lacks the discounts, the SKU names and the per-unit line items.

Idempotent: a re-run for the same window writes nothing (the writer counts only rows it changes,
S-3) and touches no day. A changed row marks its VN day (and the stored day, if the order moved)
for rebuild: :func:`record_touched_days` calls the analytics hook ``after_ingest`` per run of
consecutive days (W3: it rebuilds the TikTok layer-4 rows of those days) and logs
``tiktok_canonical_days_touched``. No buyer field is read or stored (the mapper reads none).

A failed canonical write never fails the raw path that called it: it runs in a savepoint, is
logged (``tiktok_canonical_apply_failed``, class + vendor code only) and the reconcile repairs it.
``TIKTOK_CANONICAL_SYNC=0`` turns the whole wiring off (kill switch, contract §4).
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import ORDER_DETAIL_PATH, RateLimiter, TikTokAPIError
from juli_backend.models.models import BronzeOrderRawPayload, Order, Return
from juli_backend.models.order_costs import ORDER_LEVEL, OrderFinanceTransaction
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest.canonical import DAY_ZONE, OrderLine, OrderSettlement, day_of
from juli_backend.services.ingest.canonical_writer import DbCanonicalWriter, WriteResult
from juli_backend.services.ingest.tiktok_canonical_throttle import noted_call
from juli_backend.services.ingest.tiktok_mapper import PLATFORM, map_order, map_statement

logger = logging.getLogger(__name__)

ENABLED_ENV = "TIKTOK_CANONICAL_SYNC"
REFETCH_PER_CYCLE_ENV = "TIKTOK_CANONICAL_REFETCH_PER_CYCLE"
#: Get Order Detail (``GET /order/202309/orders`` and ``/order/202507/orders``), query ``ids``:
#: "A list of TikTok Shop order ID values. Max count: 50" (tts-openapi-guide, order.json).
ORDER_DETAIL_MAX_IDS = 50
DEFAULT_REFETCH_PER_CYCLE = 100
#: Ids per ``IN (...)`` read.
_READ_CHUNK = 500
#: The dataset name the day hook is called with.
HOOK_DATASET = "order_lines"
#: W3: the dataset name for days whose daily product analytics just landed.
ANALYTICS_DATASET = "analytics"


def enabled() -> bool:
    """The kill switch: ``TIKTOK_CANONICAL_SYNC=0`` turns raw -> canonical off."""
    return os.getenv(ENABLED_ENV, "1").strip() != "0"


def refetch_per_cycle() -> int:
    try:
        value = int(os.getenv(REFETCH_PER_CYCLE_ENV, str(DEFAULT_REFETCH_PER_CYCLE)))
    except ValueError:
        value = DEFAULT_REFETCH_PER_CYCLE
    return max(0, value)


def connect_window_start(days: int, now: datetime | None = None) -> datetime:
    """The first instant of the connect window: VN midnight ``days - 1`` days before today (so
    the window is ``days`` VN calendar days including today), as aware UTC."""
    today = (now or datetime.now(UTC)).astimezone(DAY_ZONE).date()
    first = today - timedelta(days=max(1, days) - 1)
    return datetime(first.year, first.month, first.day, tzinfo=DAY_ZONE).astimezone(UTC)


def backfill_create_time_from(now: datetime | None = None) -> int:
    """Unix seconds of the first VN day of the connect window (B-1): a shop's first order read
    takes the orders CREATED in the last ``connect_days()`` (90) VN days, so the canonical
    tables hold those 90 days after connect and the read stays bounded."""
    from juli_backend.services.onboarding.history import connect_days

    return int(connect_window_start(connect_days(), now).timestamp())


def order_search_kwargs(update_from: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """The order search filter of the poll and the targeted fetch: incremental by
    ``update_time``, or (the first read, no watermark) the connect window by ``create_time``."""
    if update_from is None:
        return {"update_time_from": None, "create_time_from": backfill_create_time_from(now)}
    return {"update_time_from": update_from}


# -- results --------------------------------------------------------------------------------


@dataclass
class CanonicalApplyResult:
    """What one apply wrote: orders mapped, rows changed, VN days touched, warning codes."""

    orders: int = 0
    lines_written: int = 0
    settlements_written: int = 0
    failed: int = 0
    days: set[date] = field(default_factory=set)
    warnings: Counter[str] = field(default_factory=Counter)

    def add(self, other: CanonicalApplyResult) -> CanonicalApplyResult:
        self.orders += other.orders
        self.lines_written += other.lines_written
        self.settlements_written += other.settlements_written
        self.failed += other.failed
        self.days |= other.days
        self.warnings.update(other.warnings)
        return self


DaysTouchedFn = Callable[[AsyncSession, uuid.UUID, frozenset[date]], Awaitable[None]]


def _day_runs(days: Iterable[date]) -> list[tuple[date, date]]:
    runs: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        if runs and day == runs[-1][1] + timedelta(days=1):
            runs[-1] = (runs[-1][0], day)
        else:
            runs.append((day, day))
    return runs


async def record_touched_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    days: frozenset[date],
    *,
    dataset: str = HOOK_DATASET,
) -> None:
    """Mark the VN days whose canonical rows changed for rebuild (S-4).

    Calls the analytics after-ingest hook once per run of consecutive days, so a late cancel on
    day D asks for day D only; the hook rebuilds TikTok's layer-4 rows for those days (W3).
    ``dataset`` = :data:`ANALYTICS_DATASET` when the days are the ones the analytics pass (or
    the A-34 blocks re-read) just landed (W3: the poll calls it after its analytics step)."""
    if not days:
        return
    from juli_backend.services.shopee_analytics.materialize import after_ingest

    ordered = sorted(days)
    logger.info(
        "tiktok_canonical_days_touched",
        extra={
            "shop_id": str(shop_id),
            "days": len(ordered),
            "first_day": ordered[0].isoformat(),
            "last_day": ordered[-1].isoformat(),
        },
    )
    for start, end in _day_runs(ordered):
        await after_ingest(
            session, shop_id, platform=PLATFORM, dataset=dataset, start=start, end=end
        )


# -- refetch queue --------------------------------------------------------------------------


class RefetchQueue(Protocol):
    """Order ids the next poll cycle re-fetches by id (the reconcile's gaps)."""

    def push(self, shop_id: uuid.UUID, order_ids: Iterable[str]) -> int: ...

    def pop(self, shop_id: uuid.UUID, limit: int) -> list[str]: ...


class InMemoryRefetchQueue:
    """A per-process queue (tests, and a caller that has no Redis)."""

    def __init__(self) -> None:
        self.ids: dict[uuid.UUID, set[str]] = {}

    def push(self, shop_id: uuid.UUID, order_ids: Iterable[str]) -> int:
        bucket = self.ids.setdefault(shop_id, set())
        before = len(bucket)
        bucket.update(str(i) for i in order_ids if i)
        return len(bucket) - before

    def pop(self, shop_id: uuid.UUID, limit: int) -> list[str]:
        bucket = self.ids.get(shop_id, set())
        out = sorted(bucket)[: max(0, limit)]
        bucket.difference_update(out)
        return out


class RedisRefetchQueue:
    """A Redis set per shop (``SADD`` / ``SPOP``), kept 7 days: the reconcile runs nightly, so a
    lost set is rebuilt the next night."""

    TTL_SECONDS = 7 * 24 * 3600

    def __init__(self, client: Any) -> None:
        self._redis = client

    @staticmethod
    def key(shop_id: uuid.UUID) -> str:
        return f"juli:tiktok_canonical_refetch:{shop_id}"

    def push(self, shop_id: uuid.UUID, order_ids: Iterable[str]) -> int:
        ids = sorted({str(i) for i in order_ids if i})
        if not ids:
            return 0
        key = self.key(shop_id)
        added = int(self._redis.sadd(key, *ids) or 0)
        self._redis.expire(key, self.TTL_SECONDS)
        return added

    def pop(self, shop_id: uuid.UUID, limit: int) -> list[str]:
        if limit <= 0:
            return []
        popped = self._redis.spop(self.key(shop_id), limit) or []
        return sorted(v.decode() if isinstance(v, bytes) else str(v) for v in popped)


# -- raw readers ----------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def order_id_of(order: Mapping[str, Any]) -> str | None:
    return _text(order.get("id") or order.get("order_id"))


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    return [list(values[i : i + size]) for i in range(0, len(values), size)]


ReturnStatuses = dict[str, dict[str, str]]


def return_statuses_of(returns: Iterable[Mapping[str, Any]]) -> ReturnStatuses:
    """``order id -> {line item id or SKU id: return_status}`` from return search payloads
    (``return_line_items[].order_line_item_id`` / ``sku_id``; the latest ``update_time`` wins)."""
    latest: dict[tuple[str, str], tuple[int, str]] = {}
    for ret in returns:
        if not isinstance(ret, Mapping):
            continue
        order_id = _text(ret.get("order_id") or ret.get("tiktok_order_id"))
        status = _text(ret.get("return_status") or ret.get("status"))
        if order_id is None or status is None:
            continue
        at = _int(ret.get("update_time") or ret.get("create_time"))
        keys: list[str] = []
        for item in ret.get("return_line_items") or []:
            if isinstance(item, Mapping):
                keys += [
                    k
                    for k in (_text(item.get("order_line_item_id")), _text(item.get("sku_id")))
                    if k
                ]
        if not keys and (sku := _text(ret.get("sku_id"))):
            keys.append(sku)
        for key in keys:
            stored = latest.get((order_id, key))
            if stored is None or at >= stored[0]:
                latest[(order_id, key)] = (at, status)
    out: ReturnStatuses = {}
    for (order_id, key), (_, status) in sorted(latest.items()):
        out.setdefault(order_id, {})[key] = status
    return out


def _merge_statuses(base: ReturnStatuses, extra: ReturnStatuses) -> ReturnStatuses:
    merged = {k: dict(v) for k, v in base.items()}
    for order_id, statuses in extra.items():
        merged.setdefault(order_id, {}).update(statuses)
    return merged


async def stored_return_statuses(
    session: AsyncSession, shop_id: uuid.UUID, order_ids: Sequence[str]
) -> ReturnStatuses:
    """The returns already landed (``silver.returns``): order id -> {SKU id: status}."""
    latest: dict[tuple[str, str], tuple[datetime, str]] = {}
    for part in _chunks(sorted(set(order_ids)), _READ_CHUNK):
        rows = await session.execute(
            select(
                Return.tiktok_order_id, Return.tiktok_sku_id, Return.status, Return.update_time
            ).where(Return.shop_id == shop_id, Return.tiktok_order_id.in_(part))
        )
        for order_id, sku_id, status, at in rows:
            if not sku_id or not status:
                continue
            key = (str(order_id), str(sku_id))
            if key not in latest or at >= latest[key][0]:
                latest[key] = (at, str(status))
    out: ReturnStatuses = {}
    for (order_id, sku_id), (_, status) in sorted(latest.items()):
        out.setdefault(order_id, {})[sku_id] = status
    return out


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _unflatten(flat: Mapping[str, Any] | None) -> dict[str, Any]:
    """``{"fee.a": "1"}`` -> ``{"fee": {"a": "1"}}`` (``services/order_costs/parse._flat_amounts``
    stored the breakdowns flattened)."""
    out: dict[str, Any] = {}
    for name, value in (flat or {}).items():
        node = out
        *parents, leaf = str(name).split(".")
        for parent in parents:
            child = node.get(parent)
            if not isinstance(child, dict):
                child = node[parent] = {}
            node = child
        node[leaf] = value
    return out


def statement_data(rows: Sequence[OrderFinanceTransaction]) -> dict[str, Any]:
    """One order's stored finance rows back in the ``statement_transactions`` shape the mapper
    reads: the order-level row's totals and one SKU transaction per (SKU, statement) row."""
    order_row = next(
        (r for r in rows if r.tiktok_sku_id == ORDER_LEVEL and r.statement_id == ORDER_LEVEL),
        None,
    )
    created = next((r.order_create_time for r in rows if r.order_create_time is not None), None)
    data: dict[str, Any] = {
        "currency": next((r.currency for r in rows if r.currency), None),
        "order_create_time": int(created.replace(tzinfo=UTC).timestamp()) if created else None,
        "sku_transactions": [],
    }
    if order_row is not None:
        data.update(
            {
                "revenue_amount": _amount(order_row.revenue_amount),
                "settlement_amount": _amount(order_row.settlement_amount),
                "fee_and_tax_amount": _amount(order_row.fee_tax_amount),
                "shipping_cost_amount": _amount(order_row.shipping_cost_amount),
            }
        )
    for row in sorted(rows, key=lambda r: (r.tiktok_sku_id, r.statement_id)):
        if row.tiktok_sku_id == ORDER_LEVEL:
            continue
        data["sku_transactions"].append(
            {
                "sku_id": row.tiktok_sku_id,
                "statement_id": row.statement_id or None,
                "quantity": row.quantity,
                "revenue_amount": _amount(row.revenue_amount),
                "settlement_amount": _amount(row.settlement_amount),
                "fee_tax_amount": _amount(row.fee_tax_amount),
                "shipping_cost_amount": _amount(row.shipping_cost_amount),
                "revenue_breakdown": {
                    "subtotal_before_discount_amount": _amount(row.subtotal_before_discount_amount),
                    "seller_discount_amount": _amount(row.seller_discount_amount),
                    "refund_subtotal_before_discount_amount": _amount(
                        row.refund_subtotal_before_discount_amount
                    ),
                    "seller_discount_refund_amount": _amount(row.seller_discount_refund_amount),
                },
                "fee_tax_breakdown": _unflatten(row.fee_breakdown),
                "shipping_cost_breakdown": _unflatten(row.shipping_breakdown),
            }
        )
    return {k: v for k, v in data.items() if v is not None}


async def stored_statements(
    session: AsyncSession, shop_id: uuid.UUID, order_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """order id -> its statement data, for the orders that have finance rows."""
    grouped: dict[str, list[OrderFinanceTransaction]] = {}
    for part in _chunks(sorted(set(order_ids)), _READ_CHUNK):
        rows = await session.execute(
            select(OrderFinanceTransaction).where(
                OrderFinanceTransaction.shop_id == shop_id,
                OrderFinanceTransaction.tiktok_order_id.in_(part),
            )
        )
        for row in rows.scalars():
            grouped.setdefault(row.tiktok_order_id, []).append(row)
    return {order_id: statement_data(rows) for order_id, rows in grouped.items()}


async def latest_bronze_orders(
    session: AsyncSession, shop_id: uuid.UUID, order_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """The latest full order payload (one carrying ``line_items``) per order in bronze. A
    webhook's own payload names only the order and its status, so it is never used."""
    found: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for part in _chunks(sorted(set(order_ids)), _READ_CHUNK):
        rows = await session.execute(
            select(
                BronzeOrderRawPayload.tiktok_order_id,
                BronzeOrderRawPayload.received_at,
                BronzeOrderRawPayload.payload,
            ).where(
                BronzeOrderRawPayload.shop_id == shop_id,
                BronzeOrderRawPayload.tiktok_order_id.in_(part),
            )
        )
        for order_id, received_at, payload in rows:
            if not isinstance(payload, dict) or not payload.get("line_items"):
                continue
            key = str(order_id)
            if key not in found or received_at >= found[key][0]:
                found[key] = (received_at, payload)
    return {k: v for k, (_, v) in found.items()}


# -- apply ----------------------------------------------------------------------------------


def _error_label(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    return f"{type(exc).__name__}{f' code={code}' if code is not None else ''}"


_WRITE_ERRORS = (SQLAlchemyError, ArithmeticError, LookupError, TypeError, ValueError)


@asynccontextmanager
async def _guarded(
    session: AsyncSession, shop_id: uuid.UUID, result: CanonicalApplyResult
) -> AsyncIterator[bool]:
    """One savepoint around an apply's reads and writes: a failure rolls back the canonical part
    only, is logged and counted, and never reaches the raw path (the reconcile repairs it)."""
    try:
        async with session.begin_nested():
            yield True
    except _WRITE_ERRORS as exc:
        result.failed += max(1, result.orders)
        result.lines_written = result.settlements_written = 0
        result.days.clear()
        logger.warning(
            "tiktok_canonical_apply_failed",
            extra={"shop_id": str(shop_id), "error": _error_label(exc), "orders": result.orders},
        )


def _count(result: CanonicalApplyResult, lines: WriteResult, settlements: WriteResult) -> None:
    result.lines_written += lines.written
    result.settlements_written += settlements.written
    result.days |= lines.days | settlements.days


async def _map_and_write_orders(
    session: AsyncSession,
    shop_id: uuid.UUID,
    payloads: Mapping[str, Mapping[str, Any]],
    return_statuses: ReturnStatuses,
    writer: DbCanonicalWriter,
    result: CanonicalApplyResult,
) -> None:
    ids = sorted(payloads)
    statuses = _merge_statuses(await stored_return_statuses(session, shop_id, ids), return_statuses)
    statements = await stored_statements(session, shop_id, ids)
    lines: list[OrderLine] = []
    settlements: list[OrderSettlement] = []
    for order_id in ids:
        mapped = map_order(
            payloads[order_id],
            shop_id=shop_id,
            statement=statements.get(order_id),
            return_statuses=statuses.get(order_id),
        )
        result.warnings.update(w.split(":", 1)[0] for w in mapped.warnings)
        lines.extend(mapped.lines)
        if mapped.settlement is not None:
            settlements.append(mapped.settlement)
    _count(
        result,
        await writer.write_order_lines(shop_id, PLATFORM, lines),
        await writer.write_settlements(shop_id, PLATFORM, settlements),
    )


async def apply_orders(
    session: AsyncSession,
    shop_id: uuid.UUID,
    orders: Iterable[Mapping[str, Any]],
    *,
    return_statuses: ReturnStatuses | None = None,
    writer: DbCanonicalWriter | None = None,
    days_fn: DaysTouchedFn = record_touched_days,
) -> CanonicalApplyResult:
    """Map TikTok order payloads (search or detail, 202309 shape) to canonical lines (+ the
    settlement, when the order's finance rows are stored) and write them.

    Return statuses: the landed ``silver.returns`` of these orders, overridden per line by
    ``return_statuses`` (the job's own return payloads). The caller holds the shop scope."""
    payloads: dict[str, Mapping[str, Any]] = {}
    for order in orders:
        if isinstance(order, Mapping) and (order_id := order_id_of(order)):
            payloads[order_id] = order
    result = CanonicalApplyResult(orders=len(payloads))
    if not payloads:
        return result
    async with _guarded(session, shop_id, result):
        await _map_and_write_orders(
            session,
            shop_id,
            payloads,
            return_statuses or {},
            writer or DbCanonicalWriter(session),
            result,
        )
    await days_fn(session, shop_id, frozenset(result.days))
    return result


async def _finance_order_ids(
    session: AsyncSession, shop_id: uuid.UUID, fetched_since: datetime
) -> list[str]:
    since = (
        fetched_since.astimezone(UTC).replace(tzinfo=None)
        if fetched_since.tzinfo
        else fetched_since
    )
    rows = await session.execute(
        select(OrderFinanceTransaction.tiktok_order_id)
        .where(
            OrderFinanceTransaction.shop_id == shop_id,
            OrderFinanceTransaction.fetched_at >= since,
        )
        .distinct()
    )
    return [str(r) for r in rows.scalars()]


async def apply_settlements(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    order_ids: Sequence[str] | None = None,
    fetched_since: datetime | None = None,
    writer: DbCanonicalWriter | None = None,
    days_fn: DaysTouchedFn = record_touched_days,
) -> CanonicalApplyResult:
    """Map stored finance transactions to ``order_settlements``: for ``order_ids``, or for every
    order whose finance rows were read at or after ``fetched_since`` (naive or aware UTC)."""
    result = CanonicalApplyResult()
    if order_ids is None and fetched_since is None:
        return result
    async with _guarded(session, shop_id, result):
        ids: list[str] = list(order_ids or [])
        if order_ids is None and fetched_since is not None:
            ids = await _finance_order_ids(session, shop_id, fetched_since)
        result.orders = len(set(ids))
        statements = await stored_statements(session, shop_id, ids) if ids else {}
        settlements: list[OrderSettlement] = []
        for order_id in sorted(statements):
            mapped = map_statement(statements[order_id], shop_id=shop_id, order_ref=order_id)
            result.warnings.update(w.split(":", 1)[0] for w in mapped.warnings)
            if mapped.settlement is not None:
                settlements.append(mapped.settlement)
        used = writer or DbCanonicalWriter(session)
        _count(result, WriteResult(), await used.write_settlements(shop_id, PLATFORM, settlements))
    await days_fn(session, shop_id, frozenset(result.days))
    return result


class OrderRefetchRateLimitedError(RuntimeError):
    """The Get Order Detail bucket is empty: the canonical re-fetch stops for this cycle."""


#: The errors that end a canonical re-fetch for this cycle (the ids are queued again).
ORDER_REFETCH_ERRORS: tuple[type[BaseException], ...] = (
    TikTokAPIError,
    OrderRefetchRateLimitedError,
    OSError,
)


def order_details_fetcher(
    resource: Any, *, rate_limiter: RateLimiter, app_id: str, shop_id: str
) -> Callable[[list[str]], list[dict[str, Any]]]:
    """Get Order Detail by ids for the canonical re-fetch (P101 W2): one call per at most
    ``ORDER_DETAIL_MAX_IDS`` (50, the documented ``ids`` limit) ids, each taking a token from
    the shared rate limiter (the poll steps' 10-per-60 s window) without waiting."""

    def fetch(order_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for start in range(0, len(order_ids), ORDER_DETAIL_MAX_IDS):
            if not rate_limiter.acquire(
                app_id, shop_id, ORDER_DETAIL_PATH, max_requests=10, window_seconds=60
            ):
                raise OrderRefetchRateLimitedError(ORDER_DETAIL_PATH)
            data = noted_call(
                rate_limiter,
                app_id,
                shop_id,
                resource.get_details,
                order_ids[start : start + ORDER_DETAIL_MAX_IDS],
            )
            out.extend(o for o in (data or {}).get("orders") or [] if isinstance(o, dict))
        return out

    return fetch


# -- one job --------------------------------------------------------------------------------

FetchDetailsFn = Callable[[list[str]], Sequence[Mapping[str, Any]]]


class TikTokCanonicalSync:
    """Raw -> canonical for one job (a poll cycle or a webhook's targeted fetch) of one shop.

    The poll holds its sticky shop scope around every call. ``scope_each_call=True`` (the
    webhook's targeted fetch, whose scope does not survive the vendor fetch) enters
    ``with_shop_scope`` around each call itself."""

    def __init__(
        self,
        session: AsyncSession,
        shop_id: uuid.UUID,
        *,
        writer: DbCanonicalWriter | None = None,
        days_fn: DaysTouchedFn = record_touched_days,
        scope_each_call: bool = False,
    ) -> None:
        self.session = session
        self.shop_id = shop_id
        self._scope_each_call = scope_each_call
        self._writer = writer or DbCanonicalWriter(session)
        self._days_fn = days_fn
        self._seen: dict[str, Mapping[str, Any]] = {}
        self._returns: ReturnStatuses = {}
        self._pending: set[str] = set()
        self.result = CanonicalApplyResult()

    def _scope(self) -> AbstractAsyncContextManager[Any]:
        if not self._scope_each_call:
            return nullcontext()
        from juli_backend.database.tenant_context import with_shop_scope

        return with_shop_scope(self.session, self.shop_id)

    async def on_orders(self, orders: Sequence[Mapping[str, Any]]) -> CanonicalApplyResult:
        """The orders this job fetched: mapped now (S-1, the same job as the raw landing)."""
        async with self._scope():
            return await self._on_orders(orders)

    async def _on_orders(self, orders: Sequence[Mapping[str, Any]]) -> CanonicalApplyResult:
        batch = [o for o in orders if isinstance(o, Mapping) and order_id_of(o)]
        for order in batch:
            self._seen[order_id_of(order) or ""] = order
            self._pending.discard(order_id_of(order) or "")
        applied = await apply_orders(
            self.session,
            self.shop_id,
            batch,
            return_statuses=self._returns,
            writer=self._writer,
            days_fn=self._days_fn,
        )
        self.result.add(applied)
        return applied

    async def on_returns(self, returns: Sequence[Mapping[str, Any]]) -> CanonicalApplyResult:
        """Returns this job fetched: the orders it already holds are re-mapped now; the others
        are re-fetched by id in :meth:`finish`."""
        async with self._scope():
            return await self._on_returns(returns)

    async def _on_returns(self, returns: Sequence[Mapping[str, Any]]) -> CanonicalApplyResult:
        statuses = return_statuses_of(returns)
        self._returns = _merge_statuses(self._returns, statuses)
        held = [self._seen[i] for i in sorted(statuses) if i in self._seen]
        self._pending.update(i for i in statuses if i not in self._seen)
        if not held:
            return CanonicalApplyResult()
        applied = await apply_orders(
            self.session,
            self.shop_id,
            held,
            return_statuses=self._returns,
            writer=self._writer,
            days_fn=self._days_fn,
        )
        self.result.add(applied)
        return applied

    async def finish(
        self,
        *,
        fetch_details: FetchDetailsFn | None = None,
        queue: RefetchQueue | None = None,
        settled_since: datetime | None = None,
        refetch_limit: int | None = None,
        fetch_errors: tuple[type[BaseException], ...] = (Exception,),
        pop_queued: bool = True,
    ) -> CanonicalApplyResult:
        """End of the job. The ids queued BEFORE this job (the reconcile's gaps, a previous
        job's returned orders) are re-mapped from bronze or re-fetched by id
        (:data:`ORDER_DETAIL_MAX_IDS` per call); the returned orders this job did not hold are
        re-mapped from bronze or queued for the NEXT job (never fetched by id in this one).
        Then the settlements of the finance rows read since ``settled_since``.
        ``pop_queued=False`` (the webhook's job) only queues, leaving the queue to the poll."""
        async with self._scope():
            return await self._finish(
                fetch_details=fetch_details,
                queue=queue,
                settled_since=settled_since,
                refetch_limit=refetch_limit,
                fetch_errors=fetch_errors,
                pop_queued=pop_queued,
            )

    async def _finish(
        self,
        *,
        fetch_details: FetchDetailsFn | None,
        queue: RefetchQueue | None,
        settled_since: datetime | None,
        refetch_limit: int | None,
        fetch_errors: tuple[type[BaseException], ...],
        pop_queued: bool,
    ) -> CanonicalApplyResult:
        limit = refetch_per_cycle() if refetch_limit is None else refetch_limit
        # Only ids queued BEFORE this job are fetched by id now (decision 3: "re-fetch in the
        # NEXT poll cycle"): pop them first, then queue this job's own returned orders.
        queued = (
            sorted(set(queue.pop(self.shop_id, limit)) - set(self._seen))
            if queue is not None and pop_queued
            else []
        )
        pending = sorted(self._pending - set(self._seen))
        if pending:
            rest = await self._remap_from_bronze(pending)
            if rest and queue is not None:
                queue.push(self.shop_id, rest)
            elif rest:
                logger.info(
                    "tiktok_canonical_refetch_not_queued",
                    extra={"shop_id": str(self.shop_id), "orders": len(rest)},
                )
        if queued:
            missing = await self._remap_from_bronze(queued)
            if missing and fetch_details is not None:
                await self._refetch(missing, fetch_details, queue, fetch_errors)
            elif missing and queue is not None:
                queue.push(self.shop_id, missing)
        self._pending.clear()
        if settled_since is not None:
            self.result.add(
                await apply_settlements(
                    self.session,
                    self.shop_id,
                    fetched_since=settled_since,
                    writer=self._writer,
                    days_fn=self._days_fn,
                )
            )
        return self.result

    async def _remap_from_bronze(self, ids: list[str]) -> list[str]:
        """Re-map the orders whose full payload is in bronze; return the ids that are not."""
        bronze = await latest_bronze_orders(self.session, self.shop_id, ids)
        if bronze:
            await self._on_orders(list(bronze.values()))
        return [i for i in ids if i not in bronze]

    async def _refetch(
        self,
        ids: list[str],
        fetch_details: FetchDetailsFn,
        queue: RefetchQueue | None,
        fetch_errors: tuple[type[BaseException], ...],
    ) -> None:
        batches = _chunks(ids, ORDER_DETAIL_MAX_IDS)
        for position, batch in enumerate(batches):
            try:
                orders = list(fetch_details(batch))
            except fetch_errors as exc:
                logger.warning(
                    "tiktok_canonical_refetch_failed",
                    extra={"shop_id": str(self.shop_id), "error": _error_label(exc)},
                )
                if queue is not None:
                    queue.push(self.shop_id, [i for b in batches[position:] for i in b])
                return
            await self._on_orders(orders)


# -- nightly reconcile ----------------------------------------------------------------------


@dataclass
class ReconcileResult:
    shop_id: uuid.UUID
    raw_orders: int = 0
    canonical_orders: int = 0
    #: VN day -> (raw orders, canonical orders) for every day the two differ.
    gap_days: dict[date, tuple[int, int]] = field(default_factory=dict)
    remapped: int = 0
    queued: int = 0
    settlements_written: int = 0
    applied: CanonicalApplyResult = field(default_factory=CanonicalApplyResult)


def _naive_utc(day: date) -> datetime:
    return (
        datetime(day.year, day.month, day.day, tzinfo=DAY_ZONE).astimezone(UTC).replace(tzinfo=None)
    )


async def reconcile_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    start: date,
    end: date,
    queue: RefetchQueue | None,
    writer: DbCanonicalWriter | None = None,
    days_fn: DaysTouchedFn = record_touched_days,
) -> ReconcileResult:
    """Raw vs canonical, per VN day of ``start..end``: a raw order (VND, with a create time) with
    no canonical line is re-mapped from its bronze payload, else queued for re-fetch by id; a
    stored finance transaction with no ``order_settlements`` row is re-mapped. The caller holds
    the shop scope."""
    result = ReconcileResult(shop_id=shop_id)
    lo, hi = _naive_utc(start), _naive_utc(end + timedelta(days=1))
    raw_rows = await session.execute(
        select(Order.tiktok_order_id, Order.tiktok_created_at, Order.currency).where(
            Order.shop_id == shop_id,
            Order.tiktok_created_at >= lo,
            Order.tiktok_created_at < hi,
        )
    )
    raw: dict[str, date] = {}
    for order_id, created, currency in raw_rows:
        if created is None or (currency and str(currency).upper() != "VND"):
            continue
        raw[str(order_id)] = day_of(created.replace(tzinfo=UTC))
    canonical_rows = await session.execute(
        select(ShopeeOrderLine.order_ref, ShopeeOrderLine.day)
        .where(
            ShopeeOrderLine.shop_id == shop_id,
            ShopeeOrderLine.platform == PLATFORM,
            ShopeeOrderLine.day >= start - timedelta(days=1),
            ShopeeOrderLine.day <= end + timedelta(days=1),
        )
        .distinct()
    )
    canonical: dict[str, date] = {str(ref): day for ref, day in canonical_rows}
    raw_per_day = Counter(raw.values())
    canonical_per_day = Counter(d for d in canonical.values() if start <= d <= end)
    result.raw_orders = sum(raw_per_day.values())
    result.canonical_orders = sum(canonical_per_day.values())
    for day in sorted(set(raw_per_day) | set(canonical_per_day)):
        if raw_per_day[day] != canonical_per_day[day]:
            result.gap_days[day] = (raw_per_day[day], canonical_per_day[day])

    gaps = sorted(set(raw) - set(canonical))
    used_writer = writer or DbCanonicalWriter(session)
    if gaps:
        bronze = await latest_bronze_orders(session, shop_id, gaps)
        if bronze:
            applied = await apply_orders(
                session, shop_id, list(bronze.values()), writer=used_writer, days_fn=days_fn
            )
            result.applied.add(applied)
            result.remapped = len(bronze)
        rest = [i for i in gaps if i not in bronze]
        if rest and queue is not None:
            queue.push(shop_id, rest)
            result.queued = len(rest)

    finance = await session.execute(
        select(OrderFinanceTransaction.tiktok_order_id)
        .where(
            OrderFinanceTransaction.shop_id == shop_id,
            OrderFinanceTransaction.tiktok_sku_id != ORDER_LEVEL,
        )
        .distinct()
    )
    settled = await session.execute(
        select(ShopeeOrderIncome.order_ref).where(
            ShopeeOrderIncome.shop_id == shop_id, ShopeeOrderIncome.platform == PLATFORM
        )
    )
    unsettled = sorted({str(r) for r in finance.scalars()} - {str(r) for r in settled.scalars()})
    if unsettled:
        applied = await apply_settlements(
            session, shop_id, order_ids=unsettled, writer=used_writer, days_fn=days_fn
        )
        result.applied.add(applied)
        result.settlements_written = applied.settlements_written
    logger.info(
        "tiktok_canonical_reconcile",
        extra={
            "shop_id": str(shop_id),
            "raw_orders": result.raw_orders,
            "canonical_orders": result.canonical_orders,
            "gap_days": len(result.gap_days),
            "remapped": result.remapped,
            "queued": result.queued,
            "settlements_written": result.settlements_written,
        },
    )
    return result


__all__ = [
    "DEFAULT_REFETCH_PER_CYCLE",
    "ENABLED_ENV",
    "HOOK_DATASET",
    "ORDER_DETAIL_MAX_IDS",
    "ORDER_REFETCH_ERRORS",
    "REFETCH_PER_CYCLE_ENV",
    "CanonicalApplyResult",
    "DaysTouchedFn",
    "FetchDetailsFn",
    "InMemoryRefetchQueue",
    "OrderRefetchRateLimitedError",
    "ReconcileResult",
    "RedisRefetchQueue",
    "RefetchQueue",
    "TikTokCanonicalSync",
    "apply_orders",
    "apply_settlements",
    "backfill_create_time_from",
    "connect_window_start",
    "enabled",
    "latest_bronze_orders",
    "order_details_fetcher",
    "order_id_of",
    "order_search_kwargs",
    "reconcile_shop",
    "record_touched_days",
    "refetch_per_cycle",
    "return_statuses_of",
    "statement_data",
    "stored_return_statuses",
    "stored_statements",
]
