"""Contract-shaped doubles for the TikTok polling collaborators.

Every method here carries the real collaborator's signature (keyword-only
where the real one is), so a call the production code stops making, renames,
or passes differently fails at call time instead of being absorbed by a
``MagicMock``. Calls are recorded as ``(method, kwargs)`` for assertions on
*what was asked of the vendor*; results come from the ``responses`` mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Call = tuple[str, dict[str, Any]]


class RecordingRateLimiter:
    """``integrations.tiktok.rate_limiter.RateLimiter`` surface, without Redis."""

    def __init__(self, *, allow: bool = True, exhausted: bool = False) -> None:
        self.allow = allow
        self.exhausted = exhausted
        self.acquired: list[str] = []  # endpoints, in order
        self.exhaustion_checks: list[str] = []

    def acquire(
        self, app_id: str, shop_id: str, endpoint: str, max_requests: int, window_seconds: int
    ) -> bool:
        self.acquired.append(endpoint)
        return self.allow

    def is_exhausted(self, app_id: str, shop_id: str, endpoint: str, max_requests: int) -> bool:
        self.exhaustion_checks.append(endpoint)
        return self.exhausted

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


class _Recording:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses: dict[str, Any] = dict(responses or {})
        self.calls: list[Call] = []

    def _record(self, method: str, default: Any, **kwargs: Any) -> Any:
        self.calls.append((method, kwargs))
        return self.responses.get(method, default)

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == method]


class FakeAnalyticsResource(_Recording):
    """``integrations.tiktok.resources.analytics.AnalyticsResource`` surface."""

    def list_sku_performance_all(
        self, *, start_date_ge: str, end_date_lt: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        return self._record(
            "list_sku_performance_all", [], start_date_ge=start_date_ge, end_date_lt=end_date_lt
        )

    def get_sku_performance(
        self, *, sku_id: str, start_date_ge: str, end_date_lt: str
    ) -> dict[str, Any]:
        return self._record(
            "get_sku_performance",
            {"performance": {}},
            sku_id=sku_id,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )

    def list_product_performance_all(
        self, *, start_date_ge: str, end_date_lt: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        return self._record(
            "list_product_performance_all",
            [],
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )

    def get_product_performance(
        self, *, product_id: str, start_date_ge: str, end_date_lt: str
    ) -> dict[str, Any]:
        return self._record(
            "get_product_performance",
            {"performance": {}},
            product_id=product_id,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )

    def get_shop_performance(self, *, start_date_ge: str, end_date_lt: str) -> dict[str, Any]:
        return self._record(
            "get_shop_performance",
            {"performance": {}},
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
        )

    def get_shop_performance_per_hour(self, *, date: str) -> dict[str, Any]:
        return self._record("get_shop_performance_per_hour", {"performance": {}}, date=date)

    def get_bestselling_products(self, *, date: str, time_slot: str = "1D") -> dict[str, Any]:
        return self._record(
            "get_bestselling_products", {"products": []}, date=date, time_slot=time_slot
        )

    def get_bestselling_videos(self, *, date: str, time_slot: str = "1D") -> dict[str, Any]:
        return self._record(
            "get_bestselling_videos", {"videos": []}, date=date, time_slot=time_slot
        )

    def list_live_performance_all(
        self, *, start_date_ge: str, end_date_lt: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        return self._record(
            "list_live_performance_all", [], start_date_ge=start_date_ge, end_date_lt=end_date_lt
        )


class FakePromotionResource(_Recording):
    def get_activity(self, activity_id: str) -> dict[str, Any]:
        return self._record("get_activity", {"activity_id": activity_id}, activity_id=activity_id)


class FakeOrdersResource(_Recording):
    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        return self._record(
            "search_all",
            [],
            status=status,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )


class FakeProductsResource(FakeOrdersResource):
    pass


class FakeReturnsResource(_Recording):
    def search_returns_all(
        self,
        *,
        return_status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        return self._record(
            "search_returns_all",
            [],
            return_status=return_status,
            update_time_from=update_time_from,
            update_time_to=update_time_to,
        )


class FakeInventoryResource(_Recording):
    def search(self, *, sku_ids: list[str] | None = None) -> dict[str, Any]:
        return self._record("search", {"code": 0, "data": {"inventory": []}}, sku_ids=sku_ids)


@dataclass
class FakeProductionReadResources:
    """The attribute set of ``integrations.tiktok.factories.ProductionReadResources``."""

    orders: FakeOrdersResource = field(default_factory=FakeOrdersResource)
    products: FakeProductsResource = field(default_factory=FakeProductsResource)
    returns: FakeReturnsResource = field(default_factory=FakeReturnsResource)
    inventory: FakeInventoryResource = field(default_factory=FakeInventoryResource)
    analytics: FakeAnalyticsResource = field(default_factory=FakeAnalyticsResource)
    promotion: FakePromotionResource = field(default_factory=FakePromotionResource)


__all__ = [
    "FakeAnalyticsResource",
    "FakeInventoryResource",
    "FakeOrdersResource",
    "FakeProductionReadResources",
    "FakeProductsResource",
    "FakePromotionResource",
    "FakeReturnsResource",
    "RecordingRateLimiter",
]
