"""Per-shop cooldown gate for POST /v1/action-cards/refresh (#899, ADR-061 §2b).

The manual refresh endpoint enqueues a real TikTok poll + full scoring
pipeline Celery job on every call (``dispatch.enqueue_action_card_refresh``).
It is authenticated and shop-scoped, so Nginx — which throttles by network
origin (issue #898) — cannot express a useful limit here: every caller for a
shop shares an address and a session. This is the one application-level rate
limit in the epic, keyed on shop identity rather than network origin.

Fails closed by construction. ``get_refresh_cooldown_gate()`` raises until
``bind_action_card_refresh_cooldown_gate()`` runs at API startup, and the
bound production gate *denies* every request — rather than allowing it
through — when Redis is unset or unreachable. This codebase already has two
controls that quietly went unlimited when a dependency was unset
(``SUPABASE_JWT_SECRET`` defaulting to ``""``, ``REDIS_URL`` warming
"fail-open if unset" in ``api/main.py``); this module is deliberately not a
third (ADR-061).

Async by construction (#927). ``infra/systemd/juli-api.service`` runs uvicorn
with ``--workers 1``, so the API has exactly one event loop serving every
shop's traffic. The original #899 slice used the *synchronous* ``redis``
client and called ``try_acquire`` from an async route with no ``await`` and
no ``asyncio.to_thread`` — a slow or hung Redis connection therefore blocked
that one event loop, stalling every request for every shop, which is
precisely the availability failure ADR-061 §2b exists to prevent. Every
concrete gate here is ``async def try_acquire``, and
:class:`RedisRefreshCooldownGate` takes the same process-lifetime
``redis.asyncio`` client the Analytics KPI cache already warms and closes
(``services/analytics_kpi_cache/cache.py``, ADR-041) — one shared client,
correct shutdown, and (via that module) explicit socket timeouts, all for
free instead of a second bespoke connection.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS_ENV_VAR = "ACTION_CARD_REFRESH_COOLDOWN_SECONDS"
_DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes: TikTok poll + full scoring pipeline
# juli:<module>: future convention (docs/architecture/ownership-registry.yml
# redisKeyPolicy) — "intelligence" matches the action_cards module's planning
# owner (see the `action_cards` table entry in the same registry).
_REDIS_KEY_PREFIX = "juli:intelligence:action_card_refresh_cooldown:"


def refresh_cooldown_seconds() -> int:
    """Cooldown window in seconds — configuration, never a literal in the route.

    Override via ``ACTION_CARD_REFRESH_COOLDOWN_SECONDS``; defaults to 300s.
    """
    raw = os.getenv(_COOLDOWN_SECONDS_ENV_VAR, "").strip()
    if not raw:
        return _DEFAULT_COOLDOWN_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_COOLDOWN_SECONDS
    return value if value > 0 else _DEFAULT_COOLDOWN_SECONDS


@dataclass(frozen=True, slots=True)
class CooldownDecision:
    """Outcome of one ``try_acquire`` call."""

    allowed: bool
    retry_after_seconds: int


class RefreshCooldownGate(Protocol):
    async def try_acquire(self, shop_id: str) -> CooldownDecision: ...


class UnavailableRefreshCooldownGate:
    """Denies every request — bound when no Redis backing store is configured.

    This is the fail-closed leg: an unset ``REDIS_URL`` must not be read as
    "no limit configured." It is read as "the backing store is unavailable,"
    exactly like a live Redis connection failure.
    """

    async def try_acquire(self, shop_id: str) -> CooldownDecision:
        window = refresh_cooldown_seconds()
        logger.warning(
            "action_card_refresh_cooldown_store_unconfigured",
            extra={"shop_id": shop_id, "retry_after_seconds": window},
        )
        return CooldownDecision(allowed=False, retry_after_seconds=window)


class RedisRefreshCooldownGate:
    """Production gate: Redis ``SET NX EX`` per shop (app cache DB /0, ADR-041).

    Fails closed on any Redis error — a broken connection denies the request
    rather than allowing it through unlimited. ``redis_client`` must be an
    **async** (``redis.asyncio``) client (#927) — a synchronous client called
    from this coroutine would block the single uvicorn worker's event loop
    for every shop, not just the one being throttled.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        cooldown_seconds: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._cooldown_seconds_override = cooldown_seconds

    def _window(self) -> int:
        if self._cooldown_seconds_override is not None:
            return self._cooldown_seconds_override
        return refresh_cooldown_seconds()

    @staticmethod
    def _key(shop_id: str) -> str:
        return f"{_REDIS_KEY_PREFIX}{shop_id}"

    async def try_acquire(self, shop_id: str) -> CooldownDecision:
        from redis.exceptions import RedisError

        window = self._window()
        key = self._key(shop_id)
        try:
            acquired = await self._redis.set(key, "1", nx=True, ex=window)
        except RedisError as exc:
            logger.warning(
                "action_card_refresh_cooldown_store_unavailable",
                extra={"shop_id": shop_id, "error": str(exc)},
            )
            return CooldownDecision(allowed=False, retry_after_seconds=window)

        if acquired:
            return CooldownDecision(allowed=True, retry_after_seconds=0)

        try:
            ttl_raw = await self._redis.ttl(key)
        except RedisError:
            ttl_raw = None
        ttl = int(ttl_raw) if isinstance(ttl_raw, int) and ttl_raw > 0 else window
        return CooldownDecision(allowed=False, retry_after_seconds=ttl)


class InMemoryRefreshCooldownGate:
    """Test double with the same ``SET NX EX`` semantics — never used in production."""

    def __init__(
        self,
        *,
        cooldown_seconds: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cooldown_seconds_override = cooldown_seconds
        self._clock = clock
        self._expires_at: dict[str, float] = {}

    def _window(self) -> int:
        if self._cooldown_seconds_override is not None:
            return self._cooldown_seconds_override
        return refresh_cooldown_seconds()

    async def try_acquire(self, shop_id: str) -> CooldownDecision:
        now = self._clock()
        window = self._window()
        expiry = self._expires_at.get(shop_id)
        if expiry is not None and now < expiry:
            return CooldownDecision(
                allowed=False,
                retry_after_seconds=max(int(expiry - now), 1),
            )

        self._expires_at[shop_id] = now + window
        return CooldownDecision(allowed=True, retry_after_seconds=0)


_gate: RefreshCooldownGate | None = None


def get_refresh_cooldown_gate() -> RefreshCooldownGate:
    if _gate is None:
        raise RuntimeError(
            "Action card refresh cooldown gate is not bound; call "
            "bind_action_card_refresh_cooldown_gate() at startup"
        )
    return _gate


def set_refresh_cooldown_gate(gate: RefreshCooldownGate | None) -> None:
    global _gate
    _gate = gate


def bind_action_card_refresh_cooldown_gate(*, redis_url: str | None = None) -> None:
    """Bind the production cooldown gate at API startup (#899, ADR-061 §2b).

    An unset ``REDIS_URL`` binds :class:`UnavailableRefreshCooldownGate` —
    every refresh request is denied — rather than skipping the check.

    Reuses the process-lifetime ``redis.asyncio`` client from
    ``services.analytics_kpi_cache`` (ADR-041's "one shared async Redis
    client") instead of opening a second, bespoke connection (#927). That
    gives this gate async, non-blocking behaviour, the explicit socket
    timeouts configured on the shared client, and correct lifespan shutdown
    via ``close_shared_redis_client()`` — all without this module owning any
    connection lifecycle of its own. ``get_shared_redis_client`` only
    returns ``None`` when ``url`` is empty, which is already handled above,
    but the fallback below keeps this gate fail-closed even if that
    ever changes.
    """
    url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "").strip()
    if not url:
        set_refresh_cooldown_gate(UnavailableRefreshCooldownGate())
        return

    from juli_backend.services.analytics_kpi_cache import get_shared_redis_client

    client = get_shared_redis_client(url)
    if client is None:
        set_refresh_cooldown_gate(UnavailableRefreshCooldownGate())
        return
    set_refresh_cooldown_gate(RedisRefreshCooldownGate(client))
