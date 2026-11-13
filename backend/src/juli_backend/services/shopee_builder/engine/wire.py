"""The wire shape of an ``OptionResult`` (contract ``WIRE_KEYS`` / ``option-result.ts``).

Money and counts are plain numbers, rates are percent numbers (3.5 = 3,5 %), unknown = ``None``.
Delta money is whole đồng so the build-up adds up to it exactly.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_builder.engine.contract import (
    AdsEvaluation,
    OptionResult,
    Scenario,
)
from juli_backend.services.shopee_builder.engine.vn import DRIVER_LABELS, count, vnd

AOV_ONLY_NOTE = "Đòn bẩy này tăng giá trị mỗi đơn, không tăng số đơn."
NOT_ESTIMABLE_NOTE = "Chưa ước tính được."
PER_30D_LABEL = "Quy đổi 30 ngày (tham khảo)"


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


def _ceil(x: Decimal) -> int:
    return math.ceil(float(x) - 1e-6)


def _pct(x: Decimal | None) -> float | None:
    return None if x is None else float(x) * 100.0


def _whole(x: Decimal | None) -> float | None:
    return None if x is None else float(round(x))


def round_count(x: Decimal | float | None) -> float | None:
    """Δ Đơn at the precision the card shows (``vn.count``, P99): one decimal under 10 orders,
    whole orders from 10 up -- so the API never carries 7,6638 đơn."""
    if x is None:
        return None
    v = float(x)
    return float(round(v)) if abs(v) >= 10 else round(v, 1)


def _ratio(delta: Decimal | None, before: Decimal | None) -> float | None:
    if delta is None or before is None or before <= 0:
        return None
    return float(delta / before) * 100.0


def _column(s: Scenario) -> dict[str, Any]:
    ctr = ctor = aov = None
    if s.views and s.clicks is not None:
        ctr = s.clicks / s.views
    if s.clicks and s.clicks > 0:
        ctor = s.orders / s.clicks
    if s.orders > 0:
        aov = s.gmv / s.orders
    by_source: dict[str, dict[str, float | None]] = {}
    for key, row in s.by_source.items():
        by_source[key] = {k: (_pct(v) if k in ("ctr", "ctor") else _f(v)) for k, v in row.items()}
    return {
        "views": _f(s.views),
        "ctr": _pct(ctr),
        "ctor": _pct(ctor),
        "orders": float(s.orders),
        "aov": _f(aov),
        "gmv": float(s.gmv),
        "profit": _f(s.profit),
        "by_source": by_source,
    }


def _delta(r: OptionResult, field: str) -> tuple[Decimal | None, Decimal | None]:
    """(likely delta, before value) of orders / gmv / profit; None when not estimable."""
    if r.likely is None:
        return None, getattr(r.before, field)
    a, b = getattr(r.likely, field), getattr(r.before, field)
    return (None if a is None or b is None else a - b), b


def per_30d_profit(r: OptionResult) -> Decimal | None:
    d, _ = _delta(r, "profit")
    return None if d is None else d * 30 / r.days


def _margin_pct(s: Scenario | None) -> float | None:
    if s is None or s.profit is None or s.gmv <= 0:
        return None
    return float(s.profit / s.gmv) * 100.0


def _margin(r: OptionResult) -> dict[str, Any]:
    """P100-C (B.6): profit ÷ GMV before and after, and the shift in points. A secondary line --
    the headline is Δ tổng lợi nhuận (a lower margin can still mean more total profit)."""
    before, after = _margin_pct(r.before), _margin_pct(r.likely)
    shift = None if before is None or after is None else after - before
    return {"before_pct": before, "after_pct": after, "shift_pts": shift}


def _roi(r: OptionResult, d_gmv: Decimal | None) -> dict[str, Any]:
    """P100-C (B.4): ROI = ΔGMV ÷ chi phí (incremental). None without a cost or an estimate."""
    if d_gmv is None or r.cost_total <= 0:
        return {"value": None, "text": None}
    v = float(d_gmv / r.cost_total)
    return {"value": v, "text": "ROI " + f"{v:.1f}".replace(".", ",")}


def result_json(r: OptionResult) -> dict[str, Any]:
    d_profit, b_profit = _delta(r, "profit")
    d_gmv, b_gmv = _delta(r, "gmv")
    d_orders, b_orders = _delta(r, "orders")

    profit: dict[str, Any] | None = None
    if d_profit is not None and r.low and r.high and b_profit is not None:
        lo = r.low.profit
        hi = r.high.profit
        profit = {
            "value": _whole(d_profit),
            "pct": _ratio(d_profit, b_profit),
            "low": None if lo is None else _whole(lo - b_profit),
            "high": None if hi is None else _whole(hi - b_profit),
        }
    aov_only = r.estimable and bool(r.drivers) and all(m == "aov" for m in r.drivers)
    if aov_only:
        note: str | None = AOV_ONLY_NOTE
    elif not r.estimable:
        note = r.notes[0] if r.notes else NOT_ESTIMABLE_NOTE
    else:
        note = None

    n_cost = r.cost_total
    if n_cost > 0:
        parts = [f"Chi phí {vnd(n_cost)}"]
    elif n_cost < 0:  # P100 B.15: an Ads edit that spends less
        parts = [f"Chi phí giảm {vnd(-n_cost)}"]
    else:
        parts = ["Không có chi phí thêm"]
    be = []
    if r.break_even_orders is not None:
        be.append(f"thêm ≥ {count(_ceil(r.break_even_orders))} đơn")
    if r.break_even_aov is not None:
        be.append(f"AOV ≥ {vnd(r.break_even_aov)}")
    if be:
        parts.append("hoà vốn khi " + " hoặc ".join(be))
    after_label = f"Sau {r.days} ngày" if r.horizon == "duration" else "30 ngày đầu"
    k = Decimal(30) / r.days

    def per30(x: Decimal | None) -> float | None:
        return None if x is None else float(x * k)

    return {
        "kind": r.kind,
        "label": r.label,
        "days": r.days,
        "horizon": r.horizon,
        "drivers": list(r.drivers),
        "estimable": r.estimable,
        "basis": r.basis,
        "basis_weak": r.basis == "prior",
        "delta": {
            "profit": profit,
            "gmv": {"value": _whole(d_gmv), "pct": _ratio(d_gmv, b_gmv)},
            "orders": {
                "value": round_count(d_orders),
                "pct": _ratio(d_orders, b_orders),
                "note": note,
            },
        },
        "build_up": [{"key": p.key, "amount": float(p.amount), "text": p.text} for p in r.build_up],
        "drivers_pct": list(_drivers_pct(r)),
        "cost": {
            "total": float(n_cost),
            "break_even_orders": (
                None if r.break_even_orders is None else float(_ceil(r.break_even_orders))
            ),
            "break_even_aov": _f(r.break_even_aov),
            "text": " · ".join(parts),
        },
        "after": {
            "days": r.days,
            "label": after_label,
            "gmv_before": float(r.before.gmv),
            "gmv_after": None if r.likely is None else float(r.likely.gmv),
            "profit_before": _f(r.before.profit),
            "profit_after": None if r.likely is None else _f(r.likely.profit),
        },
        # P99b: secondary only -- the primary Δ / cost (``delta`` / ``cost``) is for the version's
        # own days; this is the same Δ rescaled to 30 days (the comparison's sort key)
        "per_30d": {
            "profit": per30(d_profit),
            "gmv": per30(d_gmv),
            "orders": round_count(per30(d_orders)),
            "secondary": True,
            "label": PER_30D_LABEL,
        },
        "roi": _roi(r, d_gmv),
        "margin": _margin(r),
        "detail": {
            "before": _column(r.before),
            "low": None if r.low is None else _column(r.low),
            "likely": None if r.likely is None else _column(r.likely),
            "high": None if r.high is None else _column(r.high),
        },
        "notes": list(r.notes),
        "ads": ads_json(r.ads),
    }


VERDICT_TEXT = {"co_lai": "có lãi", "lo": "lỗ"}


def _verdict(cpa: Decimal | None, break_even: Decimal | None) -> str | None:
    """P100 B.15: CPA below the break-even CPA -> "có lãi", else "lỗ"."""
    if cpa is None or break_even is None:
        return None
    return "co_lai" if cpa < break_even else "lo"


def ads_json(a: AdsEvaluation | None) -> dict[str, Any] | None:
    """P100 B.15: the Ads edit's own lines (CPA → CPA mới, CPA hoà vốn, kết luận, lợi nhuận sau
    quảng cáo, ROAS Shopee tham khảo) and the incremental part of its Δ orders."""
    if a is None:
        return None
    cpa_now, cpa_after = a.cpa_now, a.cpa_after
    v_now, v_after = _verdict(cpa_now, a.break_even_cpa), _verdict(cpa_after, a.break_even_cpa)

    def roas(gmv: Decimal | None, spend: Decimal | None) -> float | None:
        return None if gmv is None or not spend or spend <= 0 else float(gmv / spend)

    all_delta = None if a.orders_after is None else a.orders_after - a.orders_now
    share = a.incremental_share
    extra = None if all_delta is None or share is None else all_delta * share.p50
    return {
        "lever": a.lever,
        "campaign": a.campaign,
        "days": a.days,
        "spend_basis": a.spend_basis,
        "spend_text": a.spend_text,
        "spend": {"now": _whole(a.spend_now), "after": _whole(a.spend_after)},
        "orders": {"now": round_count(a.orders_now), "after": round_count(a.orders_after)},
        "cpa": {"now": _whole(cpa_now), "after": _whole(cpa_after)},
        "break_even_cpa": _whole(a.break_even_cpa),
        "verdict": {"now": v_now, "after": v_after},
        "verdict_text": {
            "now": None if v_now is None else VERDICT_TEXT[v_now],
            "after": None if v_after is None else VERDICT_TEXT[v_after],
        },
        "profit_after_ads": {
            "now": _whole(a.profit_after_ads(a.spend_now, a.orders_now)),
            "after": _whole(a.profit_after_ads(a.spend_after, a.orders_after)),
        },
        "roas_shopee": {
            "now": roas(a.gmv_now, a.spend_now),
            "after": roas(a.gmv_after, a.spend_after),
        },
        "incremental": {
            "share": None if share is None else _pct(share.p50),
            "orders_all": round_count(all_delta),
            "orders_extra": round_count(extra),
        },
        "cancel_rate_pct": _pct(a.cancel_rate),
    }


def _drivers_pct(r: OptionResult) -> list[dict[str, Any]]:
    """Per driver metric: the likely change of that funnel metric (percent), from the columns."""
    out: list[dict[str, Any]] = []
    b = _column(r.before)
    a = _column(r.likely) if r.likely is not None else None
    for m in r.drivers:
        pct: float | None = None
        if a is not None and b[m] not in (None, 0) and a[m] is not None:
            pct = (a[m] / b[m] - 1.0) * 100.0
        out.append({"metric": m, "label": DRIVER_LABELS[m], "pct": pct})
    return out
