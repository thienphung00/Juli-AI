"""Inbound abuse limits for agent-run routes (ADR-075 decision 4, #1223).

Points the Redis fixed-window counter design that
`juli_backend.integrations.tiktok.rate_limiter.RateLimiter` already uses for
OUTBOUND TikTok calls INWARD, at the routes a seller's browser hits
directly: approve/run creation, confirmations, and the SSE event stream.
Keyed by shop identity, read only after `get_active_shop` has already
authenticated the caller (never before) -- an unauthenticated caller never
reaches a call site in this module at all, and one shop's traffic can never
consume another shop's bucket because every key is namespaced by `shop_id`.

## Cancel is exempt, structurally

`POST /v1/demo/runs/{run_id}/cancel` (`api/routes/agent_runs.py::cancel_run`)
never calls anything in this module. That is the whole mechanism: cancel is
the safety valve a seller needs *during* the exact storm that trips every
other limit here, so it is not "a gate this module always says yes to" --
it is a route that never asks this module the question in the first place.

## Fail-closed on a backend outage -- and why that is still safe for cancel

Deliberate decision (ADR-075 decision 4 does not fix this and the issue asks
for one, recorded here and in the PR): every gate in this module fails
CLOSED when Redis is unset or unreachable, denying the request rather than
letting it through unlimited. This mirrors the one other inbound, shop-keyed
rate limit already in this codebase,
`services.action_cards.refresh_cooldown.RedisRefreshCooldownGate`
(ADR-061 section 2b) -- see that module's own docstring for the reasoning
this repeats rather than re-litigates: two controls already went "quietly
unlimited" when a dependency was unset (`SUPABASE_JWT_SECRET`, `REDIS_URL`
in the KPI cache warm), and a third inbound abuse limit joining that list
would be a silent regression the day someone forgets to set `REDIS_URL` on a
fresh box. The asymmetry the issue flags -- "failing closed on cancel would
break the safety valve exactly when it is needed" -- is real, but it is
resolved by cancel's structural exemption above, not by making this module
fail open: a backend outage that fail-closes approve/confirmations/SSE never
touches cancel, because cancel was never wired to ask this module anything.

## Async-native, not the sync `RateLimiter` class

This module reimplements `RateLimiter`'s INCR-then-conditional-EXPIRE
fixed-window algorithm rather than importing that class directly, for the
exact reason `RedisRefreshCooldownGate` already established in this
codebase (see its own docstring, "Async by construction"): `RateLimiter.
acquire` issues a *synchronous* Redis call, and `infra/systemd/
juli-api.service` runs uvicorn with `--workers 1` -- the API has exactly one
event loop serving every shop's traffic. Calling `RateLimiter.acquire`
synchronously from an async route would block that one event loop on a slow
or hung Redis round-trip, stalling every shop's request, not just the one
being throttled -- precisely the availability failure ADR-061 section 2b
exists to prevent. Wrapping the sync call in `asyncio.to_thread` was
rejected for the same reason it was rejected there: it would need a second,
bespoke synchronous Redis connection, duplicating the process-lifetime
`redis.asyncio` client `services.analytics_kpi_cache` already warms and
closes at API lifespan boundaries (with its own explicit socket timeouts),
instead of reusing it. The bucket semantics below are identical to
`RateLimiter`'s -- INCR then, only on the first hit of a window, `EXPIRE`;
exhausted once the count exceeds `max_requests` -- just async-native and
sharing the one client this process already owns.

## SSE is concurrency, not a rate window

"10 concurrent streams" is a different mechanism from a fixed window: it
needs acquire-on-open and release-on-close, including on an abnormal client
disconnect or the run terminating mid-stream. This module only owns the
counter (`try_acquire_stream` / `release_stream`); the acquire/release
pairing around the actual stream lifetime -- proven to release on every
abnormal path, not just the clean one -- lives in
`api/routes/agent_runs.py`.

## Config-driven, not literals at call sites

Every number ADR-075 decision 4 specifies is read from an env var with a
named default below, following the same convention
`services.action_cards.refresh_cooldown.refresh_cooldown_seconds` already
uses for `ACTION_CARD_REFRESH_COOLDOWN_SECONDS`.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config -- env-var driven, named defaults, never a literal at a call site.
# ---------------------------------------------------------------------------

_APPROVE_MAX_REQUESTS_ENV = "AGENT_APPROVE_RATE_LIMIT_MAX_REQUESTS"
_APPROVE_WINDOW_SECONDS_ENV = "AGENT_APPROVE_RATE_LIMIT_WINDOW_SECONDS"
_APPROVE_BURST_MAX_REQUESTS_ENV = "AGENT_APPROVE_RATE_LIMIT_BURST_MAX_REQUESTS"
_APPROVE_BURST_WINDOW_SECONDS_ENV = "AGENT_APPROVE_RATE_LIMIT_BURST_WINDOW_SECONDS"
_CONFIRMATION_MAX_REQUESTS_ENV = "AGENT_CONFIRMATION_RATE_LIMIT_MAX_REQUESTS"
_CONFIRMATION_WINDOW_SECONDS_ENV = "AGENT_CONFIRMATION_RATE_LIMIT_WINDOW_SECONDS"
_SSE_MAX_CONCURRENT_STREAMS_ENV = "AGENT_SSE_MAX_CONCURRENT_STREAMS"
_SSE_RETRY_AFTER_SECONDS_ENV = "AGENT_SSE_RETRY_AFTER_SECONDS"

# ADR-075 decision 4's numbers, as the fallback when the env var is unset.
_DEFAULT_APPROVE_MAX_REQUESTS = 5
_DEFAULT_APPROVE_WINDOW_SECONDS = 3600
_DEFAULT_APPROVE_BURST_MAX_REQUESTS = 2
# Not specified by the ADR (which gives only "burst 2"); a short window is
# what makes "burst" mean something distinct from the hourly figure --
# without one, "burst 2" would just restate "the first two of the five".
# 10s bounds a literal double-click/retry burst without being long enough
# to matter for a seller pacing genuine, spaced-out approvals.
_DEFAULT_APPROVE_BURST_WINDOW_SECONDS = 10
_DEFAULT_CONFIRMATION_MAX_REQUESTS = 30
_DEFAULT_CONFIRMATION_WINDOW_SECONDS = 3600
_DEFAULT_SSE_MAX_CONCURRENT_STREAMS = 10
# Concurrency exhaustion has no natural window reset to report -- a slot
# frees whenever any one of the shop's existing streams closes, which is
# not a fixed clock. This is a suggested backoff, not a promise.
_DEFAULT_SSE_RETRY_AFTER_SECONDS = 5

# Belt-and-suspenders safety net on the SSE concurrency counter: the
# primary correctness mechanism is the explicit acquire/release pairing in
# `api/routes/agent_runs.py` (release on clean end, run termination, AND
# client disconnect). This TTL exists only so a slot leaked by something
# that pairing cannot reach (a killed worker process, an OOM) still
# self-heals eventually instead of permanently shrinking one shop's
# concurrent-stream budget.
_SSE_CONCURRENCY_SAFETY_TTL_SECONDS = 3600


def _int_env(name: str, default: int) -> int:
    """Read an integer from an env var, failing loudly on malformed values.

    Unset or empty returns the default (documented behavior).
    Any syntactically invalid or non-positive value raises ValueError,
    making configuration errors visible immediately rather than silent.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid integer") from e
    if value <= 0:
        raise ValueError(f"Environment variable {name}={value} must be positive")
    return value


def approve_rate_limit_max_requests() -> int:
    return _int_env(_APPROVE_MAX_REQUESTS_ENV, _DEFAULT_APPROVE_MAX_REQUESTS)


def approve_rate_limit_window_seconds() -> int:
    return _int_env(_APPROVE_WINDOW_SECONDS_ENV, _DEFAULT_APPROVE_WINDOW_SECONDS)


def approve_rate_limit_burst_max_requests() -> int:
    return _int_env(_APPROVE_BURST_MAX_REQUESTS_ENV, _DEFAULT_APPROVE_BURST_MAX_REQUESTS)


def approve_rate_limit_burst_window_seconds() -> int:
    return _int_env(_APPROVE_BURST_WINDOW_SECONDS_ENV, _DEFAULT_APPROVE_BURST_WINDOW_SECONDS)


def confirmation_rate_limit_max_requests() -> int:
    return _int_env(_CONFIRMATION_MAX_REQUESTS_ENV, _DEFAULT_CONFIRMATION_MAX_REQUESTS)


def confirmation_rate_limit_window_seconds() -> int:
    return _int_env(_CONFIRMATION_WINDOW_SECONDS_ENV, _DEFAULT_CONFIRMATION_WINDOW_SECONDS)


def sse_max_concurrent_streams() -> int:
    return _int_env(_SSE_MAX_CONCURRENT_STREAMS_ENV, _DEFAULT_SSE_MAX_CONCURRENT_STREAMS)


def sse_retry_after_seconds() -> int:
    return _int_env(_SSE_RETRY_AFTER_SECONDS_ENV, _DEFAULT_SSE_RETRY_AFTER_SECONDS)


# ---------------------------------------------------------------------------
# Security-event logging convention (#905) -- structured `logger.warning`,
# no bespoke event framework (none exists in this codebase). Routes call
# this at the exact point they raise the 429, passing their OWN module
# logger (matching `core.security.dependencies.get_current_user`'s
# `jwt_rejected` and `services.tiktok.webhook`'s
# `webhook_signature_rejected`), so `caplog.at_level(..., logger=<route
# module>)` keeps working the way every other security-event test in this
# codebase already expects.
# ---------------------------------------------------------------------------

ABUSE_LIMIT_EXCEEDED_EVENT = "agent_abuse_limit_exceeded"

OPERATION_APPROVE = "approve"
OPERATION_CONFIRMATION = "confirmation"
OPERATION_SSE = "sse"


def log_abuse_limit_exceeded(
    route_logger: logging.Logger,
    *,
    shop_id: str,
    operation: str,
    retry_after_seconds: int,
) -> None:
    """The security event this module's exhaustion paths raise (ADR-075
    decision 4). Called by the route at the point it turns a denied
    `AbuseLimitDecision` into the `429`."""
    route_logger.warning(
        ABUSE_LIMIT_EXCEEDED_EVENT,
        extra={
            "shop_id": shop_id,
            "operation": operation,
            "retry_after_seconds": retry_after_seconds,
        },
    )


# ---------------------------------------------------------------------------
# Decision shape + gate protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AbuseLimitDecision:
    """Outcome of one gate call -- the same shape
    `services.action_cards.refresh_cooldown.CooldownDecision` uses."""

    allowed: bool
    retry_after_seconds: int


class AbuseLimitGate(Protocol):
    async def try_acquire_approve(self, shop_id: str) -> AbuseLimitDecision: ...
    async def try_acquire_confirmation(self, shop_id: str) -> AbuseLimitDecision: ...
    async def try_acquire_stream(self, shop_id: str) -> AbuseLimitDecision: ...
    async def release_stream(self, shop_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Unavailable gate -- bound when REDIS_URL is unset. Fail-closed leg.
# ---------------------------------------------------------------------------


class UnavailableAbuseLimitGate:
    """Denies every rate-limited operation -- bound when no Redis backing
    store is configured. An unset `REDIS_URL` is "the backing store is
    unavailable", read exactly like a live Redis failure, never "no limit
    configured" (mirrors `refresh_cooldown.UnavailableRefreshCooldownGate`).
    """

    async def try_acquire_approve(self, shop_id: str) -> AbuseLimitDecision:
        window = approve_rate_limit_window_seconds()
        logger.warning(
            "agent_abuse_limit_store_unconfigured",
            extra={
                "shop_id": shop_id,
                "operation": OPERATION_APPROVE,
                "retry_after_seconds": window,
            },
        )
        return AbuseLimitDecision(allowed=False, retry_after_seconds=window)

    async def try_acquire_confirmation(self, shop_id: str) -> AbuseLimitDecision:
        window = confirmation_rate_limit_window_seconds()
        logger.warning(
            "agent_abuse_limit_store_unconfigured",
            extra={
                "shop_id": shop_id,
                "operation": OPERATION_CONFIRMATION,
                "retry_after_seconds": window,
            },
        )
        return AbuseLimitDecision(allowed=False, retry_after_seconds=window)

    async def try_acquire_stream(self, shop_id: str) -> AbuseLimitDecision:
        retry = sse_retry_after_seconds()
        logger.warning(
            "agent_abuse_limit_store_unconfigured",
            extra={"shop_id": shop_id, "operation": OPERATION_SSE, "retry_after_seconds": retry},
        )
        return AbuseLimitDecision(allowed=False, retry_after_seconds=retry)

    async def release_stream(self, shop_id: str) -> None:
        # Nothing was ever acquired against this gate -- release is a
        # harmless no-op, same as it would be for a shop that never opened
        # a stream.
        return None


# ---------------------------------------------------------------------------
# Redis-backed production gate
# ---------------------------------------------------------------------------

_KEY_PREFIX = "juli:agent:abuse_limit:"


def _window_key(operation: str, shop_id: str) -> str:
    return f"{_KEY_PREFIX}{operation}:{shop_id}"


def _concurrency_key(shop_id: str) -> str:
    return f"{_KEY_PREFIX}sse_concurrency:{shop_id}"


class RedisAbuseLimitGate:
    """Production gate: one shared `redis.asyncio` client (#927 -- same
    process-lifetime client `services.analytics_kpi_cache` warms and
    closes), fixed-window INCR+EXPIRE counters keyed by shop, fail-closed
    on any Redis error. See the module docstring for why this reimplements
    `RateLimiter`'s algorithm async-native rather than importing that
    class.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def _increment_window(self, key: str, window_seconds: int) -> int:
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, window_seconds)
        return int(count)

    async def _ttl_or(self, key: str, fallback_seconds: int) -> int:
        from redis.exceptions import RedisError

        try:
            ttl_raw = await self._redis.ttl(key)
        except RedisError:
            return fallback_seconds
        ttl = int(ttl_raw) if isinstance(ttl_raw, int) and ttl_raw > 0 else fallback_seconds
        return ttl

    async def try_acquire_approve(self, shop_id: str) -> AbuseLimitDecision:
        from redis.exceptions import RedisError

        max_requests = approve_rate_limit_max_requests()
        window_seconds = approve_rate_limit_window_seconds()
        burst_max = approve_rate_limit_burst_max_requests()
        burst_window = approve_rate_limit_burst_window_seconds()
        sustained_key = _window_key(OPERATION_APPROVE, shop_id)
        burst_key = _window_key("approve_burst", shop_id)

        try:
            sustained_count = await self._increment_window(sustained_key, window_seconds)
            burst_count = await self._increment_window(burst_key, burst_window)
        except RedisError as exc:
            logger.warning(
                "agent_abuse_limit_store_unavailable",
                extra={"shop_id": shop_id, "operation": OPERATION_APPROVE, "error": str(exc)},
            )
            return AbuseLimitDecision(allowed=False, retry_after_seconds=window_seconds)

        if burst_count > burst_max:
            ttl = await self._ttl_or(burst_key, burst_window)
            return AbuseLimitDecision(allowed=False, retry_after_seconds=ttl)
        if sustained_count > max_requests:
            ttl = await self._ttl_or(sustained_key, window_seconds)
            return AbuseLimitDecision(allowed=False, retry_after_seconds=ttl)
        return AbuseLimitDecision(allowed=True, retry_after_seconds=0)

    async def try_acquire_confirmation(self, shop_id: str) -> AbuseLimitDecision:
        from redis.exceptions import RedisError

        max_requests = confirmation_rate_limit_max_requests()
        window_seconds = confirmation_rate_limit_window_seconds()
        key = _window_key(OPERATION_CONFIRMATION, shop_id)

        try:
            count = await self._increment_window(key, window_seconds)
        except RedisError as exc:
            logger.warning(
                "agent_abuse_limit_store_unavailable",
                extra={"shop_id": shop_id, "operation": OPERATION_CONFIRMATION, "error": str(exc)},
            )
            return AbuseLimitDecision(allowed=False, retry_after_seconds=window_seconds)

        if count > max_requests:
            ttl = await self._ttl_or(key, window_seconds)
            return AbuseLimitDecision(allowed=False, retry_after_seconds=ttl)
        return AbuseLimitDecision(allowed=True, retry_after_seconds=0)

    async def try_acquire_stream(self, shop_id: str) -> AbuseLimitDecision:
        from redis.exceptions import RedisError

        max_streams = sse_max_concurrent_streams()
        key = _concurrency_key(shop_id)

        try:
            count = await self._redis.incr(key)
            await self._redis.expire(key, _SSE_CONCURRENCY_SAFETY_TTL_SECONDS)
        except RedisError as exc:
            logger.warning(
                "agent_abuse_limit_store_unavailable",
                extra={"shop_id": shop_id, "operation": OPERATION_SSE, "error": str(exc)},
            )
            return AbuseLimitDecision(allowed=False, retry_after_seconds=sse_retry_after_seconds())

        if int(count) > max_streams:
            try:
                await self._redis.decr(key)
            except RedisError:
                pass
            return AbuseLimitDecision(allowed=False, retry_after_seconds=sse_retry_after_seconds())
        return AbuseLimitDecision(allowed=True, retry_after_seconds=0)

    async def release_stream(self, shop_id: str) -> None:
        from redis.exceptions import RedisError

        key = _concurrency_key(shop_id)
        try:
            new_value = await self._redis.decr(key)
            if isinstance(new_value, int) and new_value < 0:
                # Defensive floor -- release must never manufacture extra
                # capacity (e.g. a double-release racing two `finally`
                # blocks for the same stream).
                await self._redis.set(key, 0)
        except RedisError as exc:
            logger.warning(
                "agent_abuse_limit_release_failed",
                extra={"shop_id": shop_id, "operation": OPERATION_SSE, "error": str(exc)},
            )


# ---------------------------------------------------------------------------
# In-memory test double -- same semantics, never used in production.
# ---------------------------------------------------------------------------


class InMemoryAbuseLimitGate:
    """Test double with the same fixed-window / concurrency-counter
    semantics as the production gate -- never used in production. Every
    limit can be overridden independently (falls back to the real config
    functions when not given), matching
    `refresh_cooldown.InMemoryRefreshCooldownGate`'s override pattern.
    """

    def __init__(
        self,
        *,
        approve_max_requests: int | None = None,
        approve_window_seconds: int | None = None,
        approve_burst_max_requests: int | None = None,
        approve_burst_window_seconds: int | None = None,
        confirmation_max_requests: int | None = None,
        confirmation_window_seconds: int | None = None,
        sse_max_concurrent: int | None = None,
        sse_retry_after_seconds_override: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._approve_max = approve_max_requests
        self._approve_window = approve_window_seconds
        self._approve_burst_max = approve_burst_max_requests
        self._approve_burst_window = approve_burst_window_seconds
        self._confirmation_max = confirmation_max_requests
        self._confirmation_window = confirmation_window_seconds
        self._sse_max = sse_max_concurrent
        self._sse_retry_after = sse_retry_after_seconds_override
        self._clock = clock
        self._windows: dict[str, tuple[int, float]] = {}
        self._concurrency: dict[str, int] = {}

    @staticmethod
    def _resolve(override: int | None, getter: Callable[[], int]) -> int:
        return override if override is not None else getter()

    def _bump_window(self, key: str, window_seconds: int) -> int:
        now = self._clock()
        count, expires_at = self._windows.get(key, (0, 0.0))
        if now >= expires_at:
            count = 0
            expires_at = now + window_seconds
        count += 1
        self._windows[key] = (count, expires_at)
        return count

    def _ttl(self, key: str, fallback_seconds: int) -> int:
        now = self._clock()
        _, expires_at = self._windows.get(key, (0, now + fallback_seconds))
        return max(int(expires_at - now), 1)

    async def try_acquire_approve(self, shop_id: str) -> AbuseLimitDecision:
        max_requests = self._resolve(self._approve_max, approve_rate_limit_max_requests)
        window_seconds = self._resolve(self._approve_window, approve_rate_limit_window_seconds)
        burst_max = self._resolve(self._approve_burst_max, approve_rate_limit_burst_max_requests)
        burst_window = self._resolve(
            self._approve_burst_window, approve_rate_limit_burst_window_seconds
        )

        sustained_key = f"approve:{shop_id}"
        burst_key = f"approve_burst:{shop_id}"
        sustained_count = self._bump_window(sustained_key, window_seconds)
        burst_count = self._bump_window(burst_key, burst_window)

        if burst_count > burst_max:
            return AbuseLimitDecision(False, self._ttl(burst_key, burst_window))
        if sustained_count > max_requests:
            return AbuseLimitDecision(False, self._ttl(sustained_key, window_seconds))
        return AbuseLimitDecision(True, 0)

    async def try_acquire_confirmation(self, shop_id: str) -> AbuseLimitDecision:
        max_requests = self._resolve(self._confirmation_max, confirmation_rate_limit_max_requests)
        window_seconds = self._resolve(
            self._confirmation_window, confirmation_rate_limit_window_seconds
        )
        key = f"confirmation:{shop_id}"
        count = self._bump_window(key, window_seconds)
        if count > max_requests:
            return AbuseLimitDecision(False, self._ttl(key, window_seconds))
        return AbuseLimitDecision(True, 0)

    async def try_acquire_stream(self, shop_id: str) -> AbuseLimitDecision:
        max_streams = self._resolve(self._sse_max, sse_max_concurrent_streams)
        retry_after = self._resolve(self._sse_retry_after, sse_retry_after_seconds)
        current = self._concurrency.get(shop_id, 0)
        if current + 1 > max_streams:
            return AbuseLimitDecision(False, retry_after)
        self._concurrency[shop_id] = current + 1
        return AbuseLimitDecision(True, 0)

    async def release_stream(self, shop_id: str) -> None:
        current = self._concurrency.get(shop_id, 0)
        self._concurrency[shop_id] = max(current - 1, 0)


# ---------------------------------------------------------------------------
# Module-level binding -- same idiom as `refresh_cooldown.get/set/bind_*`.
# ---------------------------------------------------------------------------

_gate: AbuseLimitGate | None = None


def get_agent_abuse_limit_gate() -> AbuseLimitGate:
    if _gate is None:
        raise RuntimeError(
            "Agent abuse-limit gate is not bound; call bind_agent_abuse_limit_gate() at startup"
        )
    return _gate


def set_agent_abuse_limit_gate(gate: AbuseLimitGate | None) -> None:
    global _gate
    _gate = gate


def bind_agent_abuse_limit_gate(*, redis_url: str | None = None) -> None:
    """Bind the production gate at API startup (ADR-075 decision 4, #1223).

    Mirrors `services.action_cards.refresh_cooldown.
    bind_action_card_refresh_cooldown_gate` exactly: an unset `REDIS_URL`
    binds `UnavailableAbuseLimitGate` (every rate-limited operation denied)
    rather than skipping the check, and the production leg reuses the one
    shared `redis.asyncio` client instead of opening a second connection.
    """
    url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "").strip()
    if not url:
        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())
        return

    from juli_backend.services.analytics_kpi_cache import get_shared_redis_client

    client = get_shared_redis_client(url)
    if client is None:
        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())
        return
    set_agent_abuse_limit_gate(RedisAbuseLimitGate(client))
