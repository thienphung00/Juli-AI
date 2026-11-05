"""Đơn hàng (P92 B-8): the order-level view of one window, for the seller.

One row per confirmed order: when, status, the items, GMV, the levers that touched it (programme
price, flash sale, shop voucher, combo), what the buyer paid, platform fees (and where they came
from: income export / order export / formula), giá vốn, contribution and, when the income export
has it, the payout. The order key is the keyed hash the order lines are stored under, cut to 12
characters: never a platform order id, never a buyer field. Pure over a :class:`PeriodView`.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ORDER_BASIS, num
from juli_backend.services.shopee_profit.money import ZERO

KEY_CHARS = 12
SORTS = ("date", "gmv", "contribution")
STATUSES = ("delivered", "refunded_accepted", "in_transit", "cancelled", "refunded_not_received")
MAX_LIMIT = 500


def build_orders(
    view: PeriodView,
    *,
    status: str | None = None,
    lever: str | None = None,
    sort: str = "date",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}")
    orders: dict[str, list[Any]] = defaultdict(list)
    for ln, pb in view.pairs:
        orders[ln.order_id].append((ln, pb))
    rows: list[dict[str, Any]] = []
    for order_id, items in orders.items():
        first = items[0][0]
        levers = []
        if any(pb.promo_discount > 0 and ln.promo_kind.value == "promotion" for ln, pb in items):
            levers.append("promotion")
        if any(ln.promo_kind.value == "flash_sale" for ln, _ in items):
            levers.append("flash_sale")
        if any(pb.voucher > 0 for _, pb in items):
            levers.append("voucher")
        if any(pb.bundle > 0 for _, pb in items):
            levers.append("combo")
        if any(ln.affiliate for ln, _ in items):
            levers.append("affiliate")
        statuses = {ln.status.value for ln, _ in items}
        order_status = first.status.value if len(statuses) == 1 else sorted(statuses)[0]
        carrying = [pb for _, pb in items if pb.excluded_reason is None]
        profit_known = bool(carrying) and all(pb.contribution is not None for pb in carrying)
        income = view.data.lines.income.get(order_id)
        rows.append(
            {
                "order_key": order_id[:KEY_CHARS],
                "ordered_on": first.order_date.isoformat(),
                "status": order_status,
                "lines": len(items),
                "units": sum(ln.qty for ln, _ in items),
                "items": sorted({ln.product_id for ln, _ in items}),
                "levers": levers,
                "gmv": num(sum((ln.order_value for ln, _ in items), ZERO)),
                "voucher": num(sum((pb.voucher for _, pb in items), ZERO)),
                "promo_discount": num(sum((pb.promo_discount for _, pb in items), ZERO)),
                "combo_discount": num(sum((pb.bundle for _, pb in items), ZERO)),
                "paid_amount": num(sum((pb.buyer_paid for _, pb in items), ZERO)),
                "fees": num(sum((pb.fees_total or ZERO for pb in carrying), ZERO))
                if carrying
                else None,
                "fee_source": next((pb.fee_source for pb in carrying if pb.fee_source), None),
                "cogs": num(sum((pb.cogs or ZERO for pb in carrying), ZERO)) if carrying else None,
                "contribution": num(sum((pb.contribution or ZERO for pb in carrying), ZERO))
                if profit_known
                else None,
                "income": None
                if income is None
                else {
                    "payout": num(income.payout),
                    "fees_total": num(income.fees_total),
                    "refund": num(income.refund_amount),
                    "net_shipping_cost": num(income.net_shipping_cost),
                },
            }
        )
    if status:
        rows = [r for r in rows if r["status"] == status]
    if lever:
        rows = [r for r in rows if lever in r["levers"]]
    key = {
        "date": lambda r: (r["ordered_on"], r["order_key"]),
        "gmv": lambda r: (Decimal(str(r["gmv"] or 0)), r["order_key"]),
        "contribution": lambda r: (Decimal(str(r["contribution"] or 0)), r["order_key"]),
    }[sort]
    rows.sort(key=key, reverse=True)
    limit = max(1, min(limit, MAX_LIMIT))
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r["status"]] += 1
    return {
        "platform": "shopee",
        "order_basis": ORDER_BASIS,
        "window": view.window.json(),
        "sort": sort,
        "count": len(rows),
        "offset": offset,
        "limit": limit,
        "by_status": dict(by_status),
        "orders": rows[offset : offset + limit],
        "privacy": "Mã đơn là khoá băm rút gọn; không có thông tin người mua.",
    }


__all__ = ["SORTS", "STATUSES", "build_orders"]
