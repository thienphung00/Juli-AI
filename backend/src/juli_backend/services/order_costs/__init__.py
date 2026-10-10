"""Per-order cost data, read-only from TikTok (fast track P14-C, D24.13).

- ``parse`` -- price-detail / finance-transaction payloads -> rows (amounts and
  ids only; no buyer data, no names).
- ``store`` -- the per-cycle work lists, idempotent row replacement, fetch
  bookkeeping, and ``sku_deductions`` (seller- vs platform-funded per SKU).
- ``sync`` -- ``sync_order_costs``, the bounded, rate-limited fetch step the
  poll cycle (``workers/services/polling/ingestion.run_shop_cycle``) runs.

Contract: ``fasttrack/contracts/p14-rules-and-cost.md``.
"""

from juli_backend.services.order_costs.parse import (
    PLATFORM_FUNDED_FIELDS,
    SELLER_FUNDED_FIELDS,
    FinanceParse,
    FinanceRow,
    PriceParse,
    PriceRow,
    line_item_skus,
    parse_amount,
    parse_price_detail,
    parse_statement_transactions,
)
from juli_backend.services.order_costs.store import (
    FINANCE_RECHECK,
    MAX_ATTEMPTS,
    WINDOW_DAYS,
    OrderRef,
    SkuDeductions,
    orders_needing_finance,
    orders_needing_price,
    record_error,
    record_finance_fetch,
    record_price_fetch,
    replace_finance_rows,
    replace_price_rows,
    sku_deductions,
)
from juli_backend.services.order_costs.sync import (
    OrderCostsResult,
    PassResult,
    sync_order_costs,
)

__all__ = [
    "FINANCE_RECHECK",
    "MAX_ATTEMPTS",
    "PLATFORM_FUNDED_FIELDS",
    "SELLER_FUNDED_FIELDS",
    "WINDOW_DAYS",
    "FinanceParse",
    "FinanceRow",
    "OrderCostsResult",
    "OrderRef",
    "PassResult",
    "PriceParse",
    "PriceRow",
    "SkuDeductions",
    "line_item_skus",
    "orders_needing_finance",
    "orders_needing_price",
    "parse_amount",
    "parse_price_detail",
    "parse_statement_transactions",
    "record_error",
    "record_finance_fetch",
    "record_price_fetch",
    "replace_finance_rows",
    "replace_price_rows",
    "sku_deductions",
    "sync_order_costs",
]
