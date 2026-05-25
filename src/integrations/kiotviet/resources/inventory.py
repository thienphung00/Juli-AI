"""KiotViet Inventory resource.

Read-only access to product on-hand quantities with branch filtering
and incremental sync support.
"""

from __future__ import annotations

from typing import Any

from ..client import KiotVietClient


class InventoryResource:
    """High-level operations on the /productOnHands endpoint."""

    def __init__(self, client: KiotVietClient) -> None:
        self._client = client

    def list(
        self,
        *,
        page_size: int = 100,
        current_item: int = 0,
        branch_ids: list[int] | None = None,
        last_modified_from: str | None = None,
        order_by: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pageSize": page_size,
            "currentItem": current_item,
        }
        if branch_ids:
            params["branchIds"] = ",".join(str(b) for b in branch_ids)
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        if order_by is not None:
            params["orderBy"] = order_by
        return self._client.get("productOnHands", params=params)

    def list_all(
        self,
        *,
        branch_ids: list[int] | None = None,
        last_modified_from: str | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through all inventory records."""
        params: dict[str, Any] = {}
        if branch_ids:
            params["branchIds"] = ",".join(str(b) for b in branch_ids)
        if last_modified_from is not None:
            params["lastModifiedFrom"] = last_modified_from
        return self._client.get_all("productOnHands", params=params)

    def get_by_branch(self, branch_id: int) -> list[dict[str, Any]]:
        """Convenience: fetch all inventory for a single branch."""
        return self.list_all(branch_ids=[branch_id])

    def sync(
        self,
        last_modified_from: str,
        branch_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Incremental sync — fetch only records changed since *last_modified_from*."""
        return self.list_all(
            branch_ids=branch_ids,
            last_modified_from=last_modified_from,
        )
