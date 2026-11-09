"""So sánh phương án: before -> after with its range for seven metrics (P97 D85.9), laid out from
the option's ONE result (P98 / ADR-122): GMV, biên lợi nhuận, số đơn, AOV, CTOR, CTR, lượt xem --
``before`` = ``result.detail.before`` (the scope's stored funnel, scaled to the option's days) and
``after`` = the low / likely / high columns (whole scenarios ranked by Δ lợi nhuận, so the funnel
holds in each). A metric the option does not move is ``unchanged`` with the reason in Vietnamese --
never an invented lift. Pure; no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ROWS: tuple[tuple[str, str, str], ...] = (
    ("gmv", "GMV", "vnd"),
    ("margin", "Biên lợi nhuận", "pct"),
    ("orders", "Số đơn", "count"),
    ("aov", "AOV", "vnd"),
    ("ctor", "CTOR", "pct"),
    ("ctr", "CTR", "pct"),
    ("views", "Lượt xem", "count"),
)
LEVER_NAME = {
    "aov": "tăng giá trị mỗi đơn",
    "ctor": "tăng tỉ lệ đặt hàng",
    "orders": "tăng tỉ lệ đặt hàng",
    "views": "tăng lượt xem",
    "ctr": "tăng tỉ lệ nhấp",
}
NO_DATA = "Chưa đủ dữ liệu để ước tính."


def _row(key: str, label: str, unit: str, before: float | None, after: Mapping[str, Any] | None,
         reason: str | None = None, *, unchanged: bool = False) -> dict[str, Any]:  # fmt: skip
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "before": before,
        "after": after,
        "unchanged": unchanged,
        "reason": reason,
    }


def _unchanged(
    key: str, label: str, unit: str, before: float | None, reason: str
) -> dict[str, Any]:
    flat = None if before is None else {"low": before, "p50": before, "high": before}
    return _row(key, label, unit, before, flat, reason, unchanged=True)


#: result driver -> the funnel rows it moves (ADR-122 d.1: đơn moves only under views / CTR / CTOR)
RESULT_MOVES: dict[str, frozenset[str]] = {
    "views": frozenset({"views", "orders", "gmv"}),
    "ctr": frozenset({"ctr", "orders", "gmv"}),
    "ctor": frozenset({"ctor", "orders", "gmv"}),
    "aov": frozenset({"aov", "gmv"}),
}
_COLUMN_KEY = {"gmv": "gmv", "orders": "orders", "aov": "aov", "ctor": "ctor", "ctr": "ctr",
               "views": "views"}  # fmt: skip
EPS = 1e-6


def _margin_of(col: Mapping[str, Any] | None) -> float | None:
    if col is None or col.get("profit") is None or not col.get("gmv"):
        return None
    return float(col["profit"]) / float(col["gmv"]) * 100


def _value(col: Mapping[str, Any] | None, key: str) -> float | None:
    if col is None:
        return None
    if key == "margin":
        return _margin_of(col)
    v = col.get(_COLUMN_KEY[key])
    return None if v is None else float(v)


def from_result(
    result: Mapping[str, Any] | None,
    *,
    scope: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """P98 / ADR-122: the seven rows laid out from ONE ``OptionResult.json()`` -- ``before`` is the
    result's ``detail.before`` and ``after`` its low / likely / high columns, so this view shows
    exactly the numbers of ``result`` (no second calculation). Biên lợi nhuận = lợi nhuận ÷ GMV of
    the same column. ``result`` None (the family refused) or not estimable: ``after`` is None with
    the reason."""
    detail = (result or {}).get("detail") or {}
    before = detail.get("before")
    cols = (detail.get("low"), detail.get("likely"), detail.get("high"))
    estimable = bool(result and result.get("estimable")) and all(c is not None for c in cols)
    drivers = list((result or {}).get("drivers") or [])
    moved: set[str] = set()
    for d in drivers:
        moved |= RESULT_MOVES.get(d, frozenset())
    orders_note = (((result or {}).get("delta") or {}).get("orders") or {}).get("note")
    why_not = reason or orders_note or NO_DATA
    rows: list[dict[str, Any]] = []
    for key, label, unit in ROWS:
        b = _value(before, key)
        if not estimable:
            rows.append(_row(key, label, unit, b, None, why_not))
            continue
        lo, mid, hi = (_value(c, key) for c in cols)
        after = {"low": lo, "p50": mid, "high": hi}
        flat = b is not None and all(
            v is not None and abs(v - b) <= EPS * max(1.0, abs(b)) for v in (lo, mid, hi)
        )
        if key == "margin" and b is None:
            rows.append(_row(key, label, unit, None, None, "Chưa có giá vốn: biên chưa tính."))
        elif flat and key not in moved and key not in ("gmv", "margin"):
            lead = drivers[0] if drivers else "none"
            why = orders_note if key == "orders" and orders_note else _no_effect(key, lead)
            rows.append(_unchanged(key, label, unit, b, why))  # flat: float noise dropped
        else:
            rows.append(_row(key, label, unit, b, after))
    days = (result or {}).get("days")
    return {
        "scope": scope,
        "rows": rows,
        "range": "P10 – P90, giữa là P50 (cả ba là kịch bản trọn vẹn của cùng phễu)",
        "days": days,
        "note": f"Trước = phễu 30 ngày gần nhất của cùng phạm vi, quy về {days or 30} ngày; sau = "
        "kết quả dự kiến của cùng phương án. Chỉ số phương án không tác động ghi “không đổi” "
        "kèm lý do.",
        "source": "result",
    }


def _no_effect(key: str, metric: str) -> str:
    """Why a metric stays put: what the lever does move, and that the rest is not modelled."""
    name = LEVER_NAME.get(metric)
    if name is None:
        return "Mô hình không dự kiến thay đổi chỉ số này cho đòn bẩy này (không bịa mức tăng)."
    return (
        f"Đòn bẩy này {name}; mô hình không dự kiến thay đổi "
        f"{dict((k, lbl) for k, lbl, _ in ROWS)[key]} (không bịa mức tăng)."
    )


def _wrap(base: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scope": base["scope"],
        "rows": rows,
        "range": "P10 – P90, giữa là P50",
        "note": "Trước = số liệu 30 ngày gần nhất của cùng phạm vi; sau = trước cộng thay đổi dự "
        "kiến. Chỉ số mô hình không ước tính được ghi “không đổi” kèm lý do.",
    }


__all__ = ["ROWS", "from_result"]
