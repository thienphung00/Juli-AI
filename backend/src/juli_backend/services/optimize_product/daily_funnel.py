"""Daily per-product funnel rows → the inputs the stage diagnosis and a card need.

The catalog scan (:mod:`.catalog_scan`) builds :class:`ProductFunnel` values from
A-34 *window* responses saved to a snapshot. The backend scoring pass has no
snapshot: P1 ingestion stores one analytics row per product per day
(``analytics_performance_intervals``, grain ``product`` and ``sku``). This module
is the deterministic bridge from those daily rows — handed in as plain
:class:`ProductDay` values, so nothing here reads a database — to

* the :class:`ProductFunnel` the diagnosis consumes (current 14 days vs the
  prior 28, GMV over 28 days; ADR-106 decision 4), and
* the **funnel evidence** a card shows: TikTok's own KPI names and
  definitions over the last 30 days against the 30 before, as daily averages,
  each with the ADR-108 d.11 confidence label.

TikTok's definitions (ADR-106 decision 1, ADR-108): CTR = clicks ÷ product
impressions; Tỷ lệ thêm vào giỏ hàng = add-to-cart ÷ clicks; CTOR = SKU orders ÷
clicks; AOV = GMV ÷ SKU orders. Pure.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.funnel import ZERO, FunnelWindow, ProductFunnel
from juli_backend.services.shop_diagnosis.confidence import rate_label, series_label
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig

ALL_CHANNELS = "ALL_CHANNELS"
EVIDENCE_WINDOW_DAYS = 30


@dataclass(frozen=True)
class ProductDay:
    """One product's all-channel analytics for one day.

    ``add_to_cart`` and ``cart_clicks`` come from the A-34 list row (TikTok's
    ``add_cart_count`` and the ``product_clicks`` of the same row), which P1
    stores only for days fetched as single-day windows; ``None`` when the day
    has no such row. ``cart_clicks`` is kept apart from ``clicks`` (A-33) so
    the add-to-cart rate divides two numbers from the same response.
    """

    day: date
    impressions: Decimal = ZERO
    clicks: Decimal = ZERO
    sku_orders: Decimal = ZERO
    items_sold: Decimal = ZERO
    gmv: Decimal = ZERO
    add_to_cart: Decimal | None = None
    cart_clicks: Decimal | None = None


@dataclass(frozen=True)
class DayTotals:
    """Sums of :class:`ProductDay` values over a window, plus coverage."""

    days: int
    days_with_data: int
    impressions: Decimal = ZERO
    clicks: Decimal = ZERO
    sku_orders: Decimal = ZERO
    items_sold: Decimal = ZERO
    gmv: Decimal = ZERO
    add_to_cart: Decimal = ZERO
    cart_clicks: Decimal = ZERO
    days_with_cart: int = 0

    def to_window(self) -> FunnelWindow:
        return FunnelWindow(
            days=self.days,
            impressions=self.impressions,
            clicks=self.clicks,
            sku_orders=self.sku_orders,
            items_sold=self.items_sold,
            gmv=self.gmv,
        )


def in_window(rows: Iterable[ProductDay], first: date, last: date) -> list[ProductDay]:
    """Rows whose day lies in ``[first, last]`` (both included), in day order."""
    return sorted((r for r in rows if first <= r.day <= last), key=lambda r: r.day)


def totals(rows: Iterable[ProductDay], first: date, last: date) -> DayTotals:
    """Sum the rows of ``[first, last]``; ``days`` is the calendar length."""
    picked = in_window(rows, first, last)
    cart = [r for r in picked if r.add_to_cart is not None and r.cart_clicks is not None]
    return DayTotals(
        days=(last - first).days + 1,
        days_with_data=len(picked),
        impressions=sum((r.impressions for r in picked), ZERO),
        clicks=sum((r.clicks for r in picked), ZERO),
        sku_orders=sum((r.sku_orders for r in picked), ZERO),
        items_sold=sum((r.items_sold for r in picked), ZERO),
        gmv=sum((r.gmv for r in picked), ZERO),
        add_to_cart=sum((r.add_to_cart or ZERO for r in cart), ZERO),
        cart_clicks=sum((r.cart_clicks or ZERO for r in cart), ZERO),
        days_with_cart=len(cart),
    )


def diagnosis_windows(as_of: date, config: StageDiagnosisConfig) -> dict[str, tuple[date, date]]:
    """Inclusive ``(first, last)`` days of the diagnosis windows; ``as_of`` is the last day."""
    first_current = as_of - timedelta(days=config.current_window_days - 1)
    last_prior = first_current - timedelta(days=1)
    first_prior = last_prior - timedelta(days=config.prior_window_days - 1)
    return {
        "current": (first_current, as_of),
        "prior": (first_prior, last_prior),
        "last28": (as_of - timedelta(days=27), as_of),
    }


def evidence_windows(as_of: date, days: int = EVIDENCE_WINDOW_DAYS) -> dict[str, tuple[date, date]]:
    """Inclusive ``(first, last)`` of the current and previous evidence windows."""
    first_current = as_of - timedelta(days=days - 1)
    last_previous = first_current - timedelta(days=1)
    return {
        "current": (first_current, as_of),
        "previous": (last_previous - timedelta(days=days - 1), last_previous),
    }


def product_funnel(
    product_id: str,
    title: str,
    rows: list[ProductDay],
    *,
    as_of: date,
    config: StageDiagnosisConfig,
    age_days: int | None = None,
) -> ProductFunnel:
    """The diagnosis input for one product from its daily rows.

    The prior window is ``None`` when no row falls in it (history not fetched
    yet, or a new listing): a window of zeros would read as a 100 % fall.
    The series is all-channel — P1 stores no per-channel orders — so
    ``channel_scope`` is ``ALL_CHANNELS`` and the diagnosis adds its caveat.
    """
    windows = diagnosis_windows(as_of, config)
    current = totals(rows, *windows["current"])
    prior = totals(rows, *windows["prior"])
    last28 = totals(rows, *windows["last28"])
    return ProductFunnel(
        product_id=product_id,
        title=title,
        current=current.to_window(),
        prior=prior.to_window() if prior.days_with_data else None,
        gmv_28d=last28.gmv,
        age_days=age_days,
        channel_scope=ALL_CHANNELS,
    )


def last_window(
    rows: list[ProductDay], *, as_of: date, days: int = EVIDENCE_WINDOW_DAYS
) -> FunnelWindow:
    """The last ``days`` days as one all-channel window (D22's volume and AOV)."""
    return totals(rows, as_of - timedelta(days=days - 1), as_of).to_window()


# --------------------------------------------------------------------------- evidence

#: key, TikTok's Vietnamese name, unit. Unit drives formatting in the UI only.
EVIDENCE_METRICS: tuple[tuple[str, str, str], ...] = (
    ("impressions", "Lượt hiển thị sản phẩm", "count_per_day"),
    ("ctr", "CTR", "ratio"),
    ("add_to_cart_rate", "Tỷ lệ thêm vào giỏ hàng", "ratio"),
    ("ctor", "CTOR", "ratio"),
    ("aov", "AOV", "vnd"),
    ("gmv", "GMV trung bình mỗi ngày", "vnd_per_day"),
    ("sku_orders", "Đơn hàng SKU mỗi ngày", "count_per_day"),
)

DEFINITIONS: dict[str, str] = {
    "impressions": "Số lượt sản phẩm được hiển thị, trung bình mỗi ngày",
    "ctr": "Lượt nhấp ÷ lượt hiển thị sản phẩm",
    "add_to_cart_rate": "Lượt thêm vào giỏ hàng ÷ lượt nhấp",
    "ctor": "Đơn hàng SKU ÷ lượt nhấp",
    "aov": "GMV ÷ đơn hàng SKU",
    "gmv": "GMV ÷ số ngày",
    "sku_orders": "Đơn hàng SKU ÷ số ngày",
}

NOTE_NO_CART = "TikTok chưa trả số lượt thêm vào giỏ cho các ngày này"
NOTE_PARTIAL_CART = "Tỷ lệ thêm vào giỏ hàng chỉ tính trên {n} ngày có số liệu"
NOTE_NO_PREVIOUS = "Chưa có dữ liệu 30 ngày trước để so sánh"


def _ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return None if den <= 0 else num / den


def _per_day(value: Decimal, t: DayTotals) -> Decimal | None:
    return None if t.days_with_data == 0 else value / Decimal(t.days)


def _values(t: DayTotals) -> dict[str, Decimal | None]:
    return {
        "impressions": _per_day(t.impressions, t),
        "ctr": _ratio(t.clicks, t.impressions),
        "add_to_cart_rate": _ratio(t.add_to_cart, t.cart_clicks) if t.days_with_cart else None,
        "ctor": _ratio(t.sku_orders, t.clicks),
        "aov": _ratio(t.gmv, t.sku_orders),
        "gmv": _per_day(t.gmv, t),
        "sku_orders": _per_day(t.sku_orders, t),
    }


def _daily_series(rows: list[ProductDay], first: date, last: date, field: str) -> list[float]:
    """One value per calendar day of the window; a day with no row counts as 0."""
    by_day = {r.day: r for r in rows}
    out: list[float] = []
    day = first
    while day <= last:
        row = by_day.get(day)
        out.append(float(getattr(row, field)) if row is not None else 0.0)
        day += timedelta(days=1)
    return out


def _daily_aov(rows: list[ProductDay]) -> list[float]:
    return [float(r.gmv / r.sku_orders) for r in rows if r.sku_orders > 0]


def _confidence(
    key: str,
    cur: DayTotals,
    prev: DayTotals,
    cur_rows: list[ProductDay],
    prev_rows: list[ProductDay],
    windows: dict[str, tuple[date, date]],
    config: ShopDiagnosisConfig,
) -> str | None:
    """ADR-108 d.11 label for one comparison; ``None`` when nothing to compare."""
    if not prev.days_with_data or not cur.days_with_data:
        return None
    o0, o1 = float(prev.sku_orders), float(cur.sku_orders)
    if key == "ctr":
        return rate_label(
            float(prev.clicks),
            float(prev.impressions),
            float(cur.clicks),
            float(cur.impressions),
            o0,
            o1,
            config,
        ).value
    if key == "add_to_cart_rate":
        if not prev.days_with_cart or not cur.days_with_cart:
            return None
        return rate_label(
            float(prev.add_to_cart),
            float(prev.cart_clicks),
            float(cur.add_to_cart),
            float(cur.cart_clicks),
            o0,
            o1,
            config,
        ).value
    if key == "ctor":
        return rate_label(o0, float(prev.clicks), o1, float(cur.clicks), o0, o1, config).value
    if key == "aov":
        return series_label(_daily_aov(prev_rows), _daily_aov(cur_rows), o0, o1, config).value
    field = {"impressions": "impressions", "gmv": "gmv", "sku_orders": "sku_orders"}[key]
    return series_label(
        _daily_series(prev_rows, *windows["previous"], field),
        _daily_series(cur_rows, *windows["current"], field),
        o0,
        o1,
        config,
    ).value


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def funnel_evidence(
    rows: list[ProductDay],
    *,
    as_of: date,
    window_days: int = EVIDENCE_WINDOW_DAYS,
    config: ShopDiagnosisConfig | None = None,
) -> dict:
    """The card's funnel evidence: last ``window_days`` vs the ones before, per KPI.

    JSON-ready (floats and ISO dates). Ratios are window ratios — TikTok's own
    reading of "CTR over 30 days" — and counts are daily averages over the
    calendar window. ``change`` is relative (``current ÷ previous − 1``).
    """
    config = config or ShopDiagnosisConfig()
    windows = evidence_windows(as_of, window_days)
    cur_rows = in_window(rows, *windows["current"])
    prev_rows = in_window(rows, *windows["previous"])
    cur = totals(rows, *windows["current"])
    prev = totals(rows, *windows["previous"])
    cur_values, prev_values = _values(cur), _values(prev)
    metrics: list[dict] = []
    for key, label, unit in EVIDENCE_METRICS:
        now_value, before = cur_values[key], prev_values[key]
        change = (
            None
            if now_value is None or before is None or before == 0
            else now_value / before - Decimal(1)
        )
        note = None
        if key == "add_to_cart_rate":
            if not cur.days_with_cart:
                note = NOTE_NO_CART
            elif cur.days_with_cart < cur.days_with_data:
                note = NOTE_PARTIAL_CART.format(n=cur.days_with_cart)
        metrics.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "definition": DEFINITIONS[key],
                "current": _num(now_value),
                "previous": _num(before),
                "change": _num(change),
                "confidence": _confidence(key, cur, prev, cur_rows, prev_rows, windows, config),
                "note": note,
            }
        )
    notes = [] if prev.days_with_data else [NOTE_NO_PREVIOUS]
    return {
        "window_days": window_days,
        "current": {
            "start": windows["current"][0].isoformat(),
            "end": windows["current"][1].isoformat(),
            "days_with_data": cur.days_with_data,
        },
        "previous": {
            "start": windows["previous"][0].isoformat(),
            "end": windows["previous"][1].isoformat(),
            "days_with_data": prev.days_with_data,
        },
        "channel_scope": ALL_CHANNELS,
        "metrics": metrics,
        "notes": notes,
    }
