"""Per-order cost reads: price detail and finance transactions (fast track P14-C, D24.13).

Two read-only GETs, one order per call:

- ``GET /order/202407/orders/{order_id}/price_detail`` (scope
  ``seller.order.info``) -- the order's and each line item's list / sale price
  and the seller-funded vs platform-funded deductions.
- ``GET /finance/202501/orders/{order_id}/statement_transactions`` (scope
  ``seller.finance.info``) -- the SKU-level settlement: revenue, fees, shipping.

Both return the vendor ``data`` object untouched. Parsing (and dropping
anything that is not an amount or an id) is ``services/order_costs``' job; the
payloads never leave this call as anything but a dict handed to that parser.
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    finance_order_transactions_path,
    order_price_detail_path,
)


class OrderCostsResource:
    """Read one order's price detail or finance transactions."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def get_price_detail(self, order_id: str) -> dict[str, Any]:
        data = self._client.get(order_price_detail_path(order_id))
        return data if isinstance(data, dict) else {}

    def get_statement_transactions(self, order_id: str) -> dict[str, Any]:
        data = self._client.get(finance_order_transactions_path(order_id))
        return data if isinstance(data, dict) else {}
