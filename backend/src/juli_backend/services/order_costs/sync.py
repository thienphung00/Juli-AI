"""Cost data, read-only, a few orders per poll cycle (fast track P14-C, D24.13).

``sync_order_costs`` runs inside the poll cycle (``workers/services/polling``'
``run_shop_cycle``) after the commerce steps, so the orders it reads were just
synced, under that cycle's per-shop lock and sticky shop scope. Two passes, each
bounded per cycle:

1. **Price detail** -- ``GET /order/202407/orders/{id}/price_detail`` for orders
   of the last 60 days never read, or changed since read (``update_time``). The
   line items are mapped to SKUs with one ``GET /order/202507/orders?ids=``
   per 50 orders (ids only are read from it). ``ORDER_COSTS_PRICE_PER_CYCLE``
   orders per cycle (default 10).
2. **Finance transactions** -- ``GET /finance/202501/orders/{id}/
   statement_transactions`` for delivered orders not yet settled, asked again at
   most once a day. ``ORDER_COSTS_FINANCE_PER_CYCLE`` per cycle (default 10).

RATE LIMITS. Every call takes a token from the shared Redis ``RateLimiter``
(the same 10-per-60 s window the poll steps use) under its endpoint TEMPLATE
(one bucket per endpoint, not per order), without waiting: when the bucket is
empty the pass stops and the next cycle (15 min) continues. A vendor
``RateLimitError`` (429) also ends the pass for this cycle; a
``PermissionDeniedError`` (the app lacks ``seller.finance.info``, say) ends it
and is reported, so it is visible rather than retried per order. Any other
vendor error is counted on that order (``order_cost_fetches``) and retried on
later cycles up to ``MAX_ATTEMPTS`` times.

FAILURE ISOLATION. This is an extra: it never fails the cycle. Each order's rows
and bookkeeping commit together; an unexpected error rolls back that one order,
is logged, and ends the run.

``ORDER_COSTS_SYNC=0`` turns the whole step off.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok import (
    FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE,
    ORDER_PRICE_DETAIL_PATH_TEMPLATE,
    PermissionDeniedError,
    RateLimiter,
    RateLimitError,
    TikTokAPIError,
)
from juli_backend.services.order_costs import parse as order_costs_parse
from juli_backend.services.order_costs import store as order_costs_store

logger = logging.getLogger(__name__)

ENABLED_ENV = "ORDER_COSTS_SYNC"
PRICE_PER_CYCLE_ENV = "ORDER_COSTS_PRICE_PER_CYCLE"
FINANCE_PER_CYCLE_ENV = "ORDER_COSTS_FINANCE_PER_CYCLE"
DEFAULT_PER_CYCLE = 10
#: ``GET /order/202507/orders`` takes at most 50 ids.
ORDER_DETAIL_BATCH = 50
#: Rate-limit bucket of the line-item -> SKU lookup (its own endpoint).
ORDER_DETAIL_ENDPOINT = "/order/202507/orders"
STAGE = "order_costs"

#: The poll steps' window (``workers/services/polling/sync._acquire``).
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60


class DeadlineLike(Protocol):
    """The slice of the poll cycle's deadline this step needs."""

    def check(self, *, stage: str) -> float: ...


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _per_cycle(name: str) -> int:
    try:
        return max(0, int(os.environ.get(name, str(DEFAULT_PER_CYCLE))))
    except ValueError:
        return DEFAULT_PER_CYCLE


def price_per_cycle() -> int:
    return _per_cycle(PRICE_PER_CYCLE_ENV)


def finance_per_cycle() -> int:
    return _per_cycle(FINANCE_PER_CYCLE_ENV)


@dataclass
class PassResult:
    candidates: int = 0
    fetched: int = 0
    rows: int = 0
    errors: int = 0
    rate_limited: bool = False
    permission_denied: bool = False
    out_of_time: bool = False


@dataclass
class OrderCostsResult:
    price: PassResult = field(default_factory=PassResult)
    finance: PassResult = field(default_factory=PassResult)
    skipped_reason: str | None = None


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)


def _error_label(exc: BaseException) -> str:
    """Class and vendor code only -- a message can echo request data."""
    code = getattr(exc, "code", None)
    return f"{type(exc).__name__}{f' code={code}' if code is not None else ''}"


class _Pass:
    """The shared mechanics of one pass: time, tokens, one vendor call."""

    def __init__(
        self,
        *,
        result: PassResult,
        rate_limiter: RateLimiter,
        app_id: str,
        shop_key: str,
        deadline: DeadlineLike | None,
        label: str,
    ) -> None:
        self.result = result
        self._limiter = rate_limiter
        self._app_id = app_id
        self._shop_key = shop_key
        self._deadline = deadline
        self._label = label

    def stopped(self) -> bool:
        r = self.result
        return r.rate_limited or r.permission_denied or r.out_of_time

    async def call(
        self, endpoint: str, fetch: Callable[[], Any]
    ) -> tuple[Any, BaseException | None]:
        """Run ``fetch`` in a thread after a token; ``(None, None)`` means the pass must stop."""
        if self._deadline is not None:
            try:
                self._deadline.check(stage=STAGE)
            except Exception:
                self.result.out_of_time = True
                return None, None
        acquired = self._limiter.acquire(
            self._app_id,
            self._shop_key,
            endpoint,
            max_requests=RATE_LIMIT_MAX_REQUESTS,
            window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        )
        if not acquired:
            self.result.rate_limited = True
            return None, None
        try:
            return await asyncio.to_thread(fetch), None
        except RateLimitError:
            self.result.rate_limited = True
            logger.info("order_costs_vendor_rate_limited", extra={"read": self._label})
            return None, None
        except PermissionDeniedError as exc:
            self.result.permission_denied = True
            logger.warning(
                "order_costs_permission_denied",
                extra={"read": self._label, "error": _error_label(exc)},
            )
            return None, None
        except TikTokAPIError as exc:
            return None, exc


async def _sku_maps(
    step: _Pass, orders_resource: Any, order_ids: list[str]
) -> dict[str, dict[str, tuple[str, str | None]]] | None:
    """line item -> SKU for ``order_ids``; ``None`` if any lookup could not be made."""
    out: dict[str, dict[str, tuple[str, str | None]]] = {}
    for start in range(0, len(order_ids), ORDER_DETAIL_BATCH):
        batch = order_ids[start : start + ORDER_DETAIL_BATCH]
        response, error = await step.call(
            ORDER_DETAIL_ENDPOINT, partial(orders_resource.get_details, batch)
        )
        if error is not None:
            logger.warning("order_costs_order_detail_failed", extra={"error": _error_label(error)})
            return None
        if response is None:
            return None
        out.update(order_costs_parse.line_item_skus(response))
    return out


async def _commit_order(session: AsyncSession, write: Callable[[], Awaitable[int]]) -> int:
    try:
        rows = await write()
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return rows


async def _price_pass(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    resource: Any,
    orders_resource: Any,
    step: _Pass,
    now: datetime,
    limit: int,
) -> None:
    refs = await order_costs_store.orders_needing_price(session, shop_id, now=now, limit=limit)
    step.result.candidates = len(refs)
    if not refs:
        return
    skus = await _sku_maps(step, orders_resource, [ref.tiktok_order_id for ref in refs])
    if skus is None:
        return
    for ref in refs:
        if step.stopped():
            return
        order_id = ref.tiktok_order_id
        data, error = await step.call(
            ORDER_PRICE_DETAIL_PATH_TEMPLATE, partial(resource.get_price_detail, order_id)
        )
        if error is not None:
            step.result.errors += 1
            await _commit_order(
                session,
                partial(_record_error, session, shop_id, order_id, "price", error, now),
            )
            continue
        if data is None:
            return
        parsed = order_costs_parse.parse_price_detail(data, skus.get(order_id, {}))

        async def write(
            oid: str = order_id, p: Any = parsed, upd: datetime = ref.update_time
        ) -> int:
            rows = await order_costs_store.replace_price_rows(
                session, shop_id, oid, p, fetched_at=now
            )
            await order_costs_store.record_price_fetch(
                session, shop_id, oid, order_update_time=upd, fetched_at=now
            )
            return rows

        step.result.rows += await _commit_order(session, write)
        step.result.fetched += 1
        if parsed.unmapped_line_items:
            logger.info(
                "order_costs_unmapped_line_items",
                extra={"shop_id": str(shop_id), "count": parsed.unmapped_line_items},
            )


async def _record_error(
    session: AsyncSession,
    shop_id: uuid.UUID,
    order_id: str,
    read: str,
    error: BaseException,
    now: datetime,
) -> int:
    await order_costs_store.record_error(
        session, shop_id, order_id, read=read, error=_error_label(error), at=now
    )
    return 0


async def _finance_pass(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    resource: Any,
    step: _Pass,
    now: datetime,
    limit: int,
) -> None:
    refs = await order_costs_store.orders_needing_finance(session, shop_id, now=now, limit=limit)
    step.result.candidates = len(refs)
    for ref in refs:
        if step.stopped():
            return
        order_id = ref.tiktok_order_id
        data, error = await step.call(
            FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE,
            partial(resource.get_statement_transactions, order_id),
        )
        if error is not None:
            step.result.errors += 1
            await _commit_order(
                session,
                partial(_record_error, session, shop_id, order_id, "finance", error, now),
            )
            continue
        if data is None:
            return
        parsed = order_costs_parse.parse_statement_transactions(data)

        async def write(oid: str = order_id, p: Any = parsed) -> int:
            rows = await order_costs_store.replace_finance_rows(
                session, shop_id, oid, p, fetched_at=now
            )
            await order_costs_store.record_finance_fetch(
                session, shop_id, oid, settled=p.settled, fetched_at=now
            )
            return rows

        step.result.rows += await _commit_order(session, write)
        step.result.fetched += 1


async def sync_order_costs(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    resources: Any,
    rate_limiter: RateLimiter,
    app_id: str,
    shop_key: str,
    deadline: DeadlineLike | None = None,
    now: datetime | None = None,
    price_limit: int | None = None,
    finance_limit: int | None = None,
) -> OrderCostsResult:
    """Both passes for one shop. Never raises a vendor error; see the module docstring."""
    result = OrderCostsResult()
    resource = getattr(resources, "order_costs", None)
    orders_resource = getattr(resources, "orders", None)
    if not enabled():
        result.skipped_reason = "disabled"
        return result
    if resource is None or orders_resource is None:
        result.skipped_reason = "no_resource"
        return result
    stamp = _naive_utc(now)

    def make_step(pass_result: PassResult, label: str) -> _Pass:
        return _Pass(
            result=pass_result,
            rate_limiter=rate_limiter,
            app_id=app_id,
            shop_key=shop_key,
            deadline=deadline,
            label=label,
        )

    try:
        await _price_pass(
            session=session,
            shop_id=shop_id,
            resource=resource,
            orders_resource=orders_resource,
            step=make_step(result.price, "price"),
            now=stamp,
            limit=price_per_cycle() if price_limit is None else price_limit,
        )
        await _finance_pass(
            session=session,
            shop_id=shop_id,
            resource=resource,
            step=make_step(result.finance, "finance"),
            now=stamp,
            limit=finance_per_cycle() if finance_limit is None else finance_limit,
        )
    except Exception as exc:
        logger.error(
            "order_costs_failed",
            extra={"shop_id": str(shop_id), "error": _error_label(exc)},
        )
        result.skipped_reason = "error"
    logger.info(
        "order_costs_cycle",
        extra={
            "shop_id": str(shop_id),
            "price_fetched": result.price.fetched,
            "price_candidates": result.price.candidates,
            "price_errors": result.price.errors,
            "finance_fetched": result.finance.fetched,
            "finance_candidates": result.finance.candidates,
            "finance_errors": result.finance.errors,
            "rate_limited": result.price.rate_limited or result.finance.rate_limited,
            "permission_denied": result.price.permission_denied or result.finance.permission_denied,
        },
    )
    return result
