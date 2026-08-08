"""A bronze Partner fetch failure must not abort the Shared Compute job.

`_handle_response` calls `raise_for_status()` before it inspects the JSON body, so
the Partner API surfaces two disjoint exception families:

    HTTP 5xx / transport   -> requests.RequestException
    application error code -> TikTokAPIError

The sync helpers originally caught only the second. An upstream 500 on
``orders/search`` therefore escaped, aborted the bronze stage, and took silver and
gold down with it — freezing the Demo KPI envelope even though ``ctor`` and
``live_hours`` are computed from local rows and need nothing from TikTok.
"""

from __future__ import annotations

import inspect

import pytest
import requests

from juli_backend.integrations.tiktok import TikTokAPIError
from juli_backend.integrations.tiktok.resources.orders import OrdersResource
from juli_backend.services.cdp_speed.targeted_fetch_sync import (
    sync_cancellations,
    sync_orders,
    sync_returns,
)


class _AllowAllRateLimiter:
    """Matches RateLimiter.acquire's real call shape; always grants."""

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        return True


class _RaisingOrdersResource:
    """Orders double whose search_all fails the way the real client fails.

    Bound to the real signature below so a change to OrdersResource.search_all
    breaks this test rather than silently passing against a **kwargs stub.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        self.calls += 1
        raise self._exc


def test_orders_double_matches_the_real_resource_signature():
    """Guards the double itself — a drifted signature would make every test below vacuous."""
    assert inspect.signature(_RaisingOrdersResource.search_all) == inspect.signature(
        OrdersResource.search_all
    )


async def _noop_handoff(topic: str, shop_key: str, payload: bytes) -> None:
    raise AssertionError("handoff must not run when the fetch failed")


def _kwargs(resource, sync_state):
    return {
        "resource": resource,
        "rate_limiter": _AllowAllRateLimiter(),
        "handoff_fn": _noop_handoff,
        "app_id": "app-test",
        "shop_key": "shop_627",
        "sync_state": sync_state,
        "correlation_id": "corr-test",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        requests.HTTPError("500 Server Error: Internal Server Error for url: ..."),
        requests.ConnectionError("connection reset"),
        requests.Timeout("read timeout"),
        TikTokAPIError(106001, "Invalid credentials"),
    ],
    ids=["http_500", "connection_error", "timeout", "api_error"],
)
async def test_sync_orders_absorbs_every_partner_failure_family(exc, caplog):
    resource = _RaisingOrdersResource(exc)
    sync_state: dict = {}

    with caplog.at_level("WARNING"):
        await sync_orders(**_kwargs(resource, sync_state))

    assert resource.calls == 1
    assert "targeted_fetch_orders_failed" in caplog.text
    # A failed fetch must not advance the cursor, or the skipped window is lost forever.
    assert sync_state == {}


@pytest.mark.asyncio
async def test_http_error_does_not_propagate_out_of_returns_or_cancellations():
    exc = requests.HTTPError("503 Server Error: Service Unavailable")

    class _RaisingReturns:
        def search_returns_all(self, *, update_time_from=None):
            raise exc

        def search_cancellations_all(self, *, update_time_from=None):
            raise exc

    resource = _RaisingReturns()
    await sync_returns(**_kwargs(resource, {}))
    await sync_cancellations(**_kwargs(resource, {}))


@pytest.mark.asyncio
async def test_a_successful_fetch_still_advances_the_cursor():
    """Mutation guard: proves the handler absorbs failures rather than everything."""

    class _WorkingOrders:
        def search_all(
            self, *, status=None, update_time_from=None, update_time_to=None, page_size=50
        ):
            return [{"order_id": "577", "update_time": 1786000000}]

    handed_off: list[bytes] = []

    async def capture(topic: str, shop_key: str, payload: bytes) -> None:
        handed_off.append(payload)

    sync_state: dict = {}
    kwargs = _kwargs(_WorkingOrders(), sync_state)
    kwargs["handoff_fn"] = capture
    await sync_orders(**kwargs)

    assert len(handed_off) == 1
    assert sync_state["orders_last_update_time"] == 1786000000
