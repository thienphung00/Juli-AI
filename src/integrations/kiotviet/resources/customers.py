"""KiotViet Customers resource.

Covers customer CRUD, search, and customer-group listing.
"""

from __future__ import annotations

from typing import Any

from ..client import KiotVietClient


class CustomersResource:
    """High-level operations on the /customers endpoint."""

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
        name: str | None = None,
        contact_number: str | None = None,
        group_id: int | None = None,
        include_customer_group: bool = False,
        last_modified_from: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageSize": page_size,
            "currentItem": current_item,
        }
        if name is not None:
            params["name"] = name
        if contact_number is not None:
            params["contactNumber"] = contact_number
        if group_id is not None:
            params["groupId"] = group_id
        if include_customer_group:
            params["includeCustomerGroup"] = True
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        if order_by is not None:
            params["orderBy"] = order_by
        if order_direction is not None:
            params["orderDirection"] = order_direction
        params.update(extra)
        return self._client.get("customers", params=params)

    def list_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Paginate through every customer and return the full list."""
        params: dict[str, Any] = {}
        if kwargs.get("include_customer_group"):
            params["includeCustomerGroup"] = True
        if kwargs.get("last_modified_from"):
            params["lastModifiedFrom"] = kwargs["last_modified_from"]
        return self._client.get_all("customers", params=params)

    # ------------------------------------------------------------------
    # Single-record lookups
    # ------------------------------------------------------------------

    def get_by_id(self, customer_id: int) -> dict[str, Any]:
        return self._client.get(f"customers/{customer_id}")

    def get_by_code(self, code: str) -> dict[str, Any]:
        return self._client.get(f"customers/code/{code}")

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(self, customer: dict[str, Any]) -> dict[str, Any]:
        return self._client.post("customers", json=customer)

    def update(self, customer_id: int, customer: dict[str, Any]) -> dict[str, Any]:
        return self._client.put(f"customers/{customer_id}", json=customer)

    def delete(self, customer_id: int) -> dict[str, Any]:
        return self._client.delete(f"customers/{customer_id}")

    # ------------------------------------------------------------------
    # Customer groups
    # ------------------------------------------------------------------

    def list_groups(self) -> dict[str, Any]:
        return self._client.get("customergroups")
