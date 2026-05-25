"""KiotViet Orders resource.

Covers order listing, lookup, creation, and update with
payment and delivery support.
"""

from __future__ import annotations

from typing import Any

from ..client import KiotVietClient


class OrdersResource:
    """High-level operations on the /orders endpoint."""

    def __init__(self, client: KiotVietClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # List / Search
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        page_size: int = 20,
        current_item: int = 0,
        branch_ids: list[int] | None = None,
        customer_ids: list[int] | None = None,
        customer_code: str | None = None,
        status: list[int] | None = None,
        include_payment: bool = False,
        include_order_delivery: bool = False,
        last_modified_from: str | None = None,
        to_date: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageSize": page_size,
            "currentItem": current_item,
        }
        if branch_ids:
            params["branchIds"] = ",".join(str(b) for b in branch_ids)
        if customer_ids:
            params["customerIds"] = ",".join(str(c) for c in customer_ids)
        if customer_code is not None:
            params["customerCode"] = customer_code
        if status:
            params["status"] = ",".join(str(s) for s in status)
        if include_payment:
            params["includePayment"] = True
        if include_order_delivery:
            params["includeOrderDelivery"] = True
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        if to_date is not None:
            params["toDate"] = to_date
        if order_by is not None:
            params["orderBy"] = order_by
        if order_direction is not None:
            params["orderDirection"] = order_direction
        params.update(extra)
        return self._client.get("orders", params=params)

    def list_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Paginate through every order and return the full list."""
        params: dict[str, Any] = {}
        if kwargs.get("include_payment"):
            params["includePayment"] = True
        if kwargs.get("include_order_delivery"):
            params["includeOrderDelivery"] = True
        if kwargs.get("last_modified_from"):
            params["lastModifiedFrom"] = kwargs["last_modified_from"]
        return self._client.get_all("orders", params=params)

    # ------------------------------------------------------------------
    # Single-record lookups
    # ------------------------------------------------------------------

    def get_by_id(self, order_id: int) -> dict[str, Any]:
        return self._client.get(f"orders/{order_id}")

    def get_by_code(self, code: str) -> dict[str, Any]:
        return self._client.get(f"orders/code/{code}")

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(self, order: dict[str, Any]) -> dict[str, Any]:
        return self._client.post("orders", json=order)

    def update(self, order_id: int, order: dict[str, Any]) -> dict[str, Any]:
        return self._client.put(f"orders/{order_id}", json=order)
