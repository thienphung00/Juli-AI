"""KiotViet Products resource.

Covers product CRUD, batch operations, attribute listing,
and inventory-on-hand queries.
"""

from __future__ import annotations

from typing import Any

from ..client import KiotVietClient


class ProductsResource:
    """High-level operations on the /products endpoint."""

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
        category_id: int | None = None,
        name: str | None = None,
        is_active: bool | None = None,
        include_inventory: bool = False,
        include_pricebook: bool = False,
        last_modified_from: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageSize": page_size,
            "currentItem": current_item,
        }
        if category_id is not None:
            params["categoryId"] = category_id
        if name is not None:
            params["name"] = name
        if is_active is not None:
            params["isActive"] = is_active
        if include_inventory:
            params["includeInventory"] = True
        if include_pricebook:
            params["includePricebook"] = True
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        if order_by is not None:
            params["orderBy"] = order_by
        if order_direction is not None:
            params["orderDirection"] = order_direction
        params.update(extra)
        return self._client.get("products", params=params)

    def list_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Paginate through every product and return the full list."""
        params: dict[str, Any] = {}
        if "category_id" in kwargs and kwargs["category_id"] is not None:
            params["categoryId"] = kwargs.pop("category_id")
        if "name" in kwargs and kwargs["name"] is not None:
            params["name"] = kwargs.pop("name")
        if kwargs.get("is_active") is not None:
            params["isActive"] = kwargs.pop("is_active")
        if kwargs.pop("include_inventory", False):
            params["includeInventory"] = True
        if kwargs.pop("include_pricebook", False):
            params["includePricebook"] = True
        if "last_modified_from" in kwargs and kwargs["last_modified_from"] is not None:
            params["lastModifiedFrom"] = kwargs.pop("last_modified_from")
        return self._client.get_all("products", params=params)

    # ------------------------------------------------------------------
    # Single-record lookups
    # ------------------------------------------------------------------

    def get_by_id(self, product_id: int) -> dict[str, Any]:
        return self._client.get(f"products/{product_id}")

    def get_by_code(self, code: str) -> dict[str, Any]:
        return self._client.get(f"products/code/{code}")

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create(self, product: dict[str, Any]) -> dict[str, Any]:
        return self._client.post("products", json=product)

    def update(self, product_id: int, product: dict[str, Any]) -> dict[str, Any]:
        return self._client.put(f"products/{product_id}", json=product)

    def delete(self, product_id: int) -> dict[str, Any]:
        return self._client.delete(f"products/{product_id}")

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def batch_create(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        return self._client.post("listaddproducts", json={"listProducts": products})

    def batch_update(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        return self._client.put("listupdatedproducts", json={"listProducts": products})

    # ------------------------------------------------------------------
    # Attributes
    # ------------------------------------------------------------------

    def get_attributes(self) -> list[dict[str, Any]]:
        """Fetch all product attributes with distinct values."""
        return self._client.get("attributes/allwithdistinctvalue")

    # ------------------------------------------------------------------
    # Inventory on-hand
    # ------------------------------------------------------------------

    def get_inventory(
        self,
        *,
        branch_ids: list[int] | None = None,
        last_modified_from: str | None = None,
        page_size: int = 100,
        current_item: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageSize": page_size,
            "currentItem": current_item,
        }
        if branch_ids:
            params["branchIds"] = ",".join(str(b) for b in branch_ids)
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        return self._client.get("productOnHands", params=params)
