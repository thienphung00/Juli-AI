"""Why two voucher versions can give the same numbers (the owner's "why do they look identical").

A voucher's outcome moves with its value, minimum spend and days always, but a usage limit only
when expected uses reach it, a maximum discount only when an order's discount is above it, and the
per-buyer limit never (order lines carry no buyer). When two versions differ only in such inputs and
none of them binds, the numbers are equal, and this names the reason in one line each.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Inputs that change the outcome whenever they differ.
ALWAYS = ("value", "pct", "min_spend", "days")
#: Inputs that change it only when they bind.
CONDITIONAL = ("quantity", "max_value", "per_user_limit")


def _detail(card: Mapping[str, Any]) -> Mapping[str, Any]:
    return (card.get("certain") or {}).get("voucher_detail") or {}


def _p50(card: Mapping[str, Any]) -> float | None:
    total = ((card.get("predicted") or {}).get("money_per_month") or {}).get("total") or {}
    return (total.get("p50") or {}).get("dprofit")


def _same_outcome(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    ca, cb = a.get("certain") or {}, b.get("certain") or {}
    if ca.get("extra_cost") != cb.get("extra_cost"):
        return False
    pa, pb = _p50(a), _p50(b)
    return pa == pb or (pa is not None and pb is not None and abs(pa - pb) < 0.5)


def _n(value: Any) -> str:
    if not isinstance(value, int | float):
        return "?"
    v = float(value)
    return str(int(round(v))) if v >= 10 or v == int(v) else f"{v:.1f}".replace(".", ",")


def same_result_notes(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    """Vietnamese one-liners naming the inputs that differ but did not change the result
    (empty when the versions differ in a way that matters, or are not both vouchers)."""
    da, db = _detail(a), _detail(b)
    if not da or not db:
        return []
    ia, ib = a.get("inputs") or {}, b.get("inputs") or {}
    differing = [k for k in (*ALWAYS, *CONDITIONAL) if ia.get(k) != ib.get(k)]
    if not differing or any(k in ALWAYS for k in differing) or not _same_outcome(a, b):
        return []
    days = db.get("days") or da.get("days")
    notes: list[str] = []
    if "quantity" in differing:
        limits = [x for x in (ia.get("quantity"), ib.get("quantity")) if x is not None]
        uses = (db.get("usage") or {}).get("used")
        if limits:
            notes.append(
                f"Giới hạn {_n(max(limits))} lượt không đổi kết quả: dự kiến chỉ dùng "
                f"{_n(uses)} lượt trong {_n(days)} ngày, chưa chạm giới hạn."
            )
    if "max_value" in differing:
        pct_voucher = bool((db.get("max_discount") or {}).get("pct_voucher"))
        if pct_voucher:
            notes.append(
                "Mức giảm tối đa không đổi kết quả: không đơn nào đủ lớn để chạm mức tối đa."
            )
        else:
            notes.append("Mức giảm tối đa chỉ có tác dụng với voucher giảm theo %.")
    if "per_user_limit" in differing:
        notes.append(
            "Giới hạn mỗi người mua chưa tính vào kết quả: dữ liệu đơn không cho biết người mua."
        )
    return notes


__all__ = ["same_result_notes"]
