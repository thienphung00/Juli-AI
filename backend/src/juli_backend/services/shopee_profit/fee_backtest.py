"""Backtest of the fee formula against the income export (P92 B-9, last bullet). Pure.

For every order that has an Income row (``shopee_order_income``: what Shopee really charged), the
fees the FORMULA would have charged -- same order lines, income and reported fees stripped, the
shop's fee schedule on the order date, per-order fees split once per order -- are compared with the
actual fees (fixed + service incl. infrastructure and Voucher Xtra + payment + PiShip + NTTD).

Reported per order ``gap = formula - actual`` (positive: the formula over-charges). The headline
is the **mean absolute gap** (đ per order) and that gap as a **percentage of what the buyer paid**
(Σ|gap| ÷ Σ buyer-paid); the contract's target is <= 1 % (``TARGET_PCT``), checked on real data in
Ops and on synthetic data in the unit test (which asserts the computation, not a threshold).

Orders that cannot be compared are counted, never guessed: no Income row on some line,
a status that carries no fee (cancelled / undelivered), or no formula for the order date.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    SkuCost,
    profit_lines,
)

TARGET_PCT = 1.0
WORST = 5
KEY_CHARS = 12


def _f(value: Decimal) -> float:
    return float(round(value, 2))


def backtest(
    pairs: Sequence[tuple[OrderLine, ProfitBreakdown]],
    schedule_of: Callable[[str], FeeSchedule],
    costs: Mapping[str, SkuCost],
) -> dict[str, Any]:
    orders: dict[str, list[OrderLine]] = defaultdict(list)
    for line, _ in pairs:
        orders[line.order_id].append(line)
    rows: list[dict[str, Any]] = []
    skipped = {"no_income": 0, "no_fee_status": 0, "no_formula": 0}
    for order_id, lines in orders.items():
        if any(ln.income is None for ln in lines):
            skipped["no_income"] += 1
            continue
        if not all(ln.status.carries_profit for ln in lines):
            skipped["no_fee_status"] += 1
            continue
        schedule = schedule_of(lines[0].product_id)
        if schedule.formula_on(lines[0].order_date) is None:
            skipped["no_formula"] += 1
            continue
        actual = sum((ln.income.fees_total for ln in lines if ln.income is not None), ZERO)
        stripped = [replace(ln, income=None, actual_fees=None) for ln in lines]
        formula = sum(
            (pb.fees_total or ZERO for _, pb in profit_lines(stripped, costs, schedule=schedule)),
            ZERO,
        )
        rows.append(
            {
                "order_key": order_id[:KEY_CHARS],
                "formula": formula,
                "actual": actual,
                "gap": formula - actual,
                "buyer_paid": sum((ln.buyer_paid for ln in lines), ZERO),
            }
        )
    n = len(rows)
    base: dict[str, Any] = {
        "target_pct": TARGET_PCT,
        "orders_compared": n,
        "orders_skipped": skipped,
        "definition": (
            "Chênh lệch = phí theo công thức - phí Shopee thực thu (Income) của cùng một đơn; "
            "dương = công thức tính dư. % = tổng |chênh lệch| / tổng tiền người mua trả."
        ),
    }
    if n == 0:
        return {
            **base,
            "mean_abs_gap": None,
            "mean_gap": None,
            "pct_of_buyer_paid": None,
            "within_target": None,
            "worst": [],
        }
    abs_sum = sum((abs(r["gap"]) for r in rows), ZERO)
    paid = sum((r["buyer_paid"] for r in rows), ZERO)
    pct = None if paid <= 0 else float(abs_sum / paid * 100)
    worst = sorted(rows, key=lambda r: (-abs(r["gap"]), r["order_key"]))[:WORST]
    return {
        **base,
        "mean_abs_gap": _f(abs_sum / n),
        "mean_gap": _f(sum((r["gap"] for r in rows), ZERO) / n),
        "mean_formula_fees": _f(sum((r["formula"] for r in rows), ZERO) / n),
        "mean_actual_fees": _f(sum((r["actual"] for r in rows), ZERO) / n),
        "mean_buyer_paid": _f(paid / n),
        "pct_of_buyer_paid": None if pct is None else round(pct, 3),
        "within_target": None if pct is None else pct <= TARGET_PCT,
        "worst": [
            {
                "order_key": r["order_key"],
                "formula_fees": _f(r["formula"]),
                "actual_fees": _f(r["actual"]),
                "gap": _f(r["gap"]),
                "buyer_paid": _f(r["buyer_paid"]),
            }
            for r in worst
        ],
    }


__all__ = ["TARGET_PCT", "backtest"]
