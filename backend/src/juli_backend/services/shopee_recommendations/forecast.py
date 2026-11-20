"""F7.1 / F7.2: the one forecast of a card, as an amount, for every metric.

``metrics_of_result`` turns the builder's engine result (``OptionResult``) into
``forecast.metrics``: for each of ``profit``, ``gmv``, ``orders``, ``aov`` and ``margin_pct`` a
block ``{hien_tai, du_kien, delta, delta_pct, low, high, days}`` over the card's own N days.

* ``hien_tai`` = the base the engine scaled to the card's N days (``result.before``: the shop's or
  product's per-day figure over its base window x N), so a 7-day card carries 7 days, never a
  30-day total (F7.2).
* ``delta`` = the engine's P50 effect (the ``likely`` column minus ``before``); ``du_kien`` =
  ``hien_tai + delta`` (F7.1). ``low`` / ``high`` = ``hien_tai`` + the P10 / P90 effect, so
  ``low <= du_kien <= high`` for amounts. No centre or prior logic lives here: the centre and the
  band are whatever the engine produced. Without an estimate every ``du_kien`` is None and the
  forecast carries the reason code (``reasons``).
* ``margin_pct`` = profit / doanh thu thực in percent (the dashboard's margin, built from the
  result's ``margin_basis``); its ``delta`` is in points and ``delta_pct`` is None.

The block also carries ``data_through`` (the newest complete data day the numbers were computed
on; the screen says "Số liệu đến dd/mm"). Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_builder.engine.wire import _margin_pct
from juli_backend.services.shopee_builder.reasons import code_for_note, text_for

if TYPE_CHECKING:
    from juli_backend.services.shopee_builder.engine.contract import OptionResult, Scenario

SCHEMA = "forecast/1"
METRIC_KEYS = ("profit", "gmv", "orders", "aov", "margin_pct")


def _f(x: Decimal | float | None) -> float | None:
    return None if x is None else float(x)


def _aov(s: Scenario) -> Decimal | None:
    return s.gmv / s.orders if s.orders > 0 else None


def _margin(r: OptionResult, s: Scenario) -> float | None:
    """The dashboard margin of scenario ``s``: (m0 x R_before + Δ profit) / R_after, with
    R = GMV x (net revenue / GMV) of the margin basis (``engine.wire._margin``)."""
    mb = r.margin_basis
    if mb is None or mb.profit is None or mb.net_revenue <= 0 or mb.gmv <= 0:
        return None
    if s is r.before:
        return _margin_pct(mb.profit, mb.net_revenue)
    if s.profit is None or r.before.profit is None:
        return None
    ratio = mb.net_revenue / mb.gmv
    m0 = mb.profit / mb.net_revenue
    return _margin_pct(m0 * (r.before.gmv * ratio) + (s.profit - r.before.profit), s.gmv * ratio)


def _block(
    get: Callable[[Scenario], Decimal | float | None],
    r: OptionResult,
    *,
    relative: bool = True,
) -> dict[str, Any]:
    hien = _f(get(r.before))
    out: dict[str, Any] = {
        "hien_tai": hien,
        "du_kien": None,
        "delta": None,
        "delta_pct": None,
        "low": None,
        "high": None,
        "days": r.days,
    }
    if r.likely is None or hien is None:
        return out
    likely = _f(get(r.likely))
    if likely is None:
        return out
    delta = likely - hien
    out["delta"] = delta
    out["du_kien"] = hien + delta
    if relative and hien > 0:
        out["delta_pct"] = delta / hien * 100.0
    lo = _f(get(r.low)) if r.low is not None else None
    hi = _f(get(r.high)) if r.high is not None else None
    out["low"], out["high"] = (
        (None, None) if lo is None or hi is None else (min(lo, hi), max(lo, hi))
    )
    return out


def metrics_of_result(r: OptionResult) -> dict[str, dict[str, Any]]:
    """The five metric blocks of ``r`` (see the module docstring)."""

    def aov(s: Scenario) -> Decimal | None:
        return _aov(s)

    def margin(s: Scenario) -> float | None:
        return _margin(r, s)

    return {
        "profit": _block(lambda s: s.profit, r),
        "gmv": _block(lambda s: s.gmv, r),
        "orders": _block(lambda s: s.orders, r),
        "aov": _block(aov, r),
        "margin_pct": _block(margin, r, relative=False),
    }


def empty_metrics(days: int | None = None) -> dict[str, dict[str, Any]]:
    """Every metric null (no result at all): the reason code says why."""
    return {
        k: {
            "hien_tai": None,
            "du_kien": None,
            "delta": None,
            "delta_pct": None,
            "low": None,
            "high": None,
            "days": days,
        }
        for k in METRIC_KEYS
    }


def forecast_of(
    result: OptionResult | None, *, reason: str | None, data_through: date | None
) -> dict[str, Any]:
    """The card's ``forecast`` block: ``metrics`` + ``estimable`` / ``basis`` / ``reason_code`` /
    ``reason_text`` + ``data_through`` (ISO day). ``reason`` is the stored block's reason (used
    when there is no result at all)."""
    estimable = result is not None and result.estimable and result.likely is not None
    code: str | None = None
    if not estimable:
        if result is not None:
            code = code_for_note(result.notes[0] if result.notes else None)
        else:
            code = reason or "no_estimate"
    return {
        "schema": SCHEMA,
        "days": None if result is None else result.days,
        "estimable": estimable,
        "basis": None if result is None else result.basis,
        "reason_code": code,
        "reason_text": text_for(code),
        "within_noise": [] if result is None else list(result.within_noise),
        "data_through": None if data_through is None else data_through.isoformat(),
        "metrics": empty_metrics() if result is None else metrics_of_result(result),
    }


__all__ = ["SCHEMA", "empty_metrics", "forecast_of", "metrics_of_result"]
