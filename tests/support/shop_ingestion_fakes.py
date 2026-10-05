"""Fake TikTok resources for the per-shop ingestion tests (fast track P1-B).

``FakeAnalyticsResource`` answers A-31/A-32/A-33/A-34/A-36 the way the contract
samples in ``docs/integrations/tiktok_api/contract-collection.md`` do: a
``latest_available_date`` on every response and one DAILY interval per day of
the requested ``[start_date_ge, end_date_lt)`` window, clipped to the days the
fake shop "has data" for. It records every call (thread, window, concurrency)
so tests can assert on call counts rather than on mocks' internals.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from juli_backend.integrations.tiktok import TikTokAPIError


def _d(value: str) -> date:
    return date.fromisoformat(value)


@dataclass
class FakeAnalyticsResource:
    prefix: str = "A"
    latest: date = date(2026, 7, 15)
    earliest_data: date = date(2026, 1, 1)
    products: tuple[str, ...] = ("p1", "p2", "p3")
    skus: tuple[tuple[str, str], ...] = (("s1", "p1"), ("s2", "p2"))
    out_of_range_before: date | None = None
    detail_delay: float = 0.0
    gmv: str = "2000.00"
    calls: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    peak_in_flight: int = 0
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- helpers ------------------------------------------------------------

    def _record(self, name: str, **kwargs: Any) -> None:
        with self._lock:
            self.calls[name].append({**kwargs, "thread": threading.get_ident()})

    def _check_range(self, start: str) -> None:
        if self.out_of_range_before is not None and _d(start) < self.out_of_range_before:
            raise TikTokAPIError(36009004, "start_date_ge is out of the supported range")

    def _days(self, start: str, end: str) -> list[date]:
        first = max(_d(start), self.earliest_data)
        last = min(_d(end) - timedelta(days=1), self.latest)
        days: list[date] = []
        cursor = first
        while cursor <= last:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _detail_enter(self) -> None:
        with self._lock:
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)

    def _detail_exit(self) -> None:
        with self._lock:
            self._in_flight -= 1

    def pid(self, product: str) -> str:
        return f"{self.prefix}-{product}"

    def detail_calls(self) -> int:
        return len(self.calls["get_product_performance"]) + len(self.calls["get_sku_performance"])

    # -- A-32 / A-31 ----------------------------------------------------------

    def list_sku_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self._record("list_sku_performance_all", start=start_date_ge, end=end_date_lt)
        self._check_range(start_date_ge)
        if not self._days(start_date_ge, end_date_lt):
            return []
        return [
            {"id": f"{self.prefix}-{sku}", "product_id": self.pid(product)}
            for sku, product in self.skus
        ]

    def get_sku_performance(self, *, sku_id: str, start_date_ge: str, end_date_lt: str) -> dict:
        self._detail_enter()
        try:
            self._record("get_sku_performance", id=sku_id, start=start_date_ge, end=end_date_lt)
            if self.detail_delay:
                time.sleep(self.detail_delay)
            product = next(
                (self.pid(p) for s, p in self.skus if f"{self.prefix}-{s}" == sku_id), None
            )
            return {
                "latest_available_date": self.latest.isoformat(),
                "performance": {
                    "sku_id": sku_id,
                    "product_id": product,
                    "intervals": [
                        {
                            "start_date": day.isoformat(),
                            "end_date": (day + timedelta(days=1)).isoformat(),
                            "gmv": {"amount": "1000.00", "currency": "VND"},
                            "sku_orders": 1,
                            "items_sold": 1,
                        }
                        for day in self._days(start_date_ge, end_date_lt)
                    ],
                },
            }
        finally:
            self._detail_exit()

    # -- A-34 / A-33 ----------------------------------------------------------

    def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self._record("list_product_performance_all", start=start_date_ge, end=end_date_lt)
        self._check_range(start_date_ge)
        if not self._days(start_date_ge, end_date_lt):
            return []
        return [
            {
                "id": self.pid(product),
                "total_performance": {
                    "gmv": {"amount": self.gmv, "currency": "VND"},
                    "orders": 2,
                    "items_sold": 2,
                    "ctr": "0.05",
                    "click_order_rate": "0.10",
                },
            }
            for product in self.products
        ]

    def get_product_performance(
        self, *, product_id: str, start_date_ge: str, end_date_lt: str
    ) -> dict:
        self._detail_enter()
        try:
            self._record(
                "get_product_performance", id=product_id, start=start_date_ge, end=end_date_lt
            )
            if self.detail_delay:
                time.sleep(self.detail_delay)
            return {
                "latest_available_date": self.latest.isoformat(),
                "performance": {
                    "intervals": [
                        {
                            "start_date": day.isoformat(),
                            "end_date": (day + timedelta(days=1)).isoformat(),
                            "sales": {
                                "gmv": {"amount": self.gmv, "currency": "VND"},
                                "items_sold": 2,
                                "orders": 2,
                            },
                            "traffic": {
                                "breakdowns": [
                                    {
                                        "content_type": "VIDEO",
                                        "traffic": {"impressions": 100, "ctr": "0.05"},
                                    }
                                ]
                            },
                        }
                        for day in self._days(start_date_ge, end_date_lt)
                    ]
                },
            }
        finally:
            self._detail_exit()

    # -- A-36 / A-37 / A-28 ---------------------------------------------------

    def get_shop_performance(self, *, start_date_ge: str, end_date_lt: str) -> dict:
        self._record("get_shop_performance", start=start_date_ge, end=end_date_lt)
        self._check_range(start_date_ge)
        return {
            "latest_available_date": self.latest.isoformat(),
            "performance": {
                "intervals": [
                    {
                        "start_date": day.isoformat(),
                        "end_date": (day + timedelta(days=1)).isoformat(),
                        "sales": {
                            "gmv": {"overall": {"amount": "5000.00", "currency": "VND"}},
                            "orders_count": 3,
                            "sku_orders_count": 3,
                            "items_sold": 3,
                        },
                        "traffic": {"avg_visitors": 10, "avg_conversation_rate": "0.05"},
                    }
                    for day in self._days(start_date_ge, end_date_lt)
                ]
            },
        }

    def get_shop_performance_per_hour(self, *, date: str) -> dict:
        self._record("get_shop_performance_per_hour", date=date)
        return {}

    def list_live_performance_all(self, *, start_date_ge: str, end_date_lt: str) -> list[dict]:
        self._record("list_live_performance_all", start=start_date_ge, end=end_date_lt)
        return []

    def get_bestselling_products(self, **_: Any) -> dict:  # pragma: no cover - not called
        self._record("get_bestselling_products")
        return {}

    def get_bestselling_videos(self, **_: Any) -> dict:  # pragma: no cover - not called
        self._record("get_bestselling_videos")
        return {}


def make_resources(analytics: FakeAnalyticsResource, *, orders: list[dict] | None = None):
    """A ``ProductionReadResources`` stand-in: commerce mocks + the fake analytics."""
    order_rows = orders if orders is not None else []
    resources = SimpleNamespace(
        orders=MagicMock(),
        products=MagicMock(),
        returns=MagicMock(),
        inventory=MagicMock(),
        promotion=MagicMock(),
        analytics=analytics,
    )
    resources.orders.search_all.return_value = order_rows
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"inventory": []}
    return resources


class FakeRateLimiter:
    """Redis-window stand-in. ``limit`` requests per key until ``reset()``.

    ``global_detail_limit`` caps detail calls ACROSS products (the per-product
    path keys would otherwise never run out), so a test can prove the limiter
    actually gates the parallel pool.
    """

    def __init__(self, *, limit: int = 10_000, global_detail_limit: int | None = None) -> None:
        self.limit = limit
        self.global_detail_limit = global_detail_limit
        self.counts: dict[str, int] = defaultdict(int)
        self.detail_count = 0
        self.events: list[tuple[str, str]] = []
        self.refuse: set[str] = set()

    @staticmethod
    def _is_detail(endpoint: str) -> bool:
        listing = endpoint.endswith(("/shop_products/performance", "/shop_skus/performance"))
        return ("/shop_products/" in endpoint or "/shop_skus/" in endpoint) and not listing

    def acquire(self, app_id, shop_id, endpoint, *, max_requests=10, window_seconds=60) -> bool:
        if endpoint in self.refuse:
            self.events.append(("refused", endpoint))
            return False
        if self._is_detail(endpoint) and self.global_detail_limit is not None:
            if self.detail_count >= self.global_detail_limit:
                self.events.append(("refused", endpoint))
                return False
            self.detail_count += 1
        if self.counts[endpoint] >= self.limit:
            self.events.append(("refused", endpoint))
            return False
        self.counts[endpoint] += 1
        self.events.append(("acquired", endpoint))
        return True

    def is_exhausted(self, app_id, shop_id, endpoint, *, max_requests=10) -> bool:
        return False

    def time_until_reset(self, app_id, shop_id, endpoint) -> int:
        return 1

    def reset(self) -> None:
        self.counts.clear()
        self.detail_count = 0
        self.events.append(("reset", ""))


__all__ = ["FakeAnalyticsResource", "FakeRateLimiter", "make_resources"]
