"""U1 (owner 2026-11-17): the ONE rule for what a daily-budget raise of a Dịch vụ hiển thị
campaign costs. The card (``evaluate.py``) and Tự tạo step 4 (``engine_families/ads_edit.py``)
both call it, so the same card shows the same number: the EXTRA budget, never the full budget."""

from __future__ import annotations

from decimal import Decimal


def budget_raise_extra_per_day(new: Decimal | None, before: Decimal | None) -> Decimal | None:
    """``new - before`` per day for a raise; ``None`` for a cut, an unlimited budget or an
    unknown current budget (the caller then keeps the spend-based figure)."""
    if new is None or before is None or new <= before:
        return None
    return new - before
