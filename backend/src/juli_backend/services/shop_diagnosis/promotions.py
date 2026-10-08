"""Promotions analysis — ADR-108 decision 10 (vouchers, flash sales) and d.9's date bands.

Inputs are the raw payloads the fetch saved: Search Activities, Get Activity
details (product and SKU lists with activity prices or discounts) and Search
Coupons. Times are unix seconds (create / update times are milliseconds);
dates are read in the shop's timezone, UTC+7, like
:mod:`juli_backend.services.optimize_product.order_windows`.

* **Vouchers** are classified from their configuration against the *giá một món
  phổ biến* (median value of single-item orders, last 30 days), never from the
  seller-written title. Order data does not name the voucher an order used, so
  redemptions and cost are an upper bound — every order at or above the
  threshold while the voucher ran — and are labelled as such.
* **Flash sales**: coverage per day (share of the day's 24 hours under a flash
  sale; a flash day is ≥ 50 % covered), per week and over the last 30 days;
  **true depth** is the flash price against the price already lowered by a
  running product discount, not against list price.
* **Day groups**: CTOR and SKU orders per add-to-cart on the product card for
  pre-flash, flash and non-flash days; a cell under 5 days or 30 orders is
  *Chưa đủ dữ liệu*. Three flags follow; no recommendation is generated (d.12).

A deactivated activity or coupon is read as running until its last update.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

from juli_backend.services.optimize_product.order_windows import (
    create_day,
    kept,
    live_lines,
    orders_between,
)
from juli_backend.services.shop_diagnosis.channels import Counts
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows, to_float

SHOP_UTC_OFFSET_HOURS = 7
DAY_SECONDS = 86_400
SKIPPED_STATUSES = frozenset({"DRAFT", "NOT_EFFECTIVE"})
DEACTIVATED = "DEACTIVATED"


class PromoKind(StrEnum):
    FLASH = "Flash sale"
    DISCOUNT = "Giảm giá sản phẩm"
    BUNDLE = "Mua nhiều giảm nhiều"
    GIFT = "Quà tặng kèm"
    SHIPPING = "Giảm phí vận chuyển"
    VOUCHER = "Voucher"
    OTHER = "Khuyến mãi khác"


ACTIVITY_KINDS: dict[str, PromoKind] = {
    "FLASHSALE": PromoKind.FLASH,
    "FIXED_PRICE": PromoKind.DISCOUNT,
    "DIRECT_DISCOUNT": PromoKind.DISCOUNT,
    "BUY_MORE_SAVE_MORE": PromoKind.BUNDLE,
    "GIFT_WITH_PURCHASE": PromoKind.GIFT,
    "SHIPPING_DISCOUNT": PromoKind.SHIPPING,
}


def _zone() -> timezone:
    return timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))


def _seconds(value: object) -> int | None:
    try:
        seconds = int(str(value))
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return seconds // 1000 if seconds > 10**11 else seconds


def day_start(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=_zone()).timestamp())


def local_day(seconds: int) -> date:
    return datetime.fromtimestamp(seconds, tz=_zone()).date()


def _end(raw_end: object, status: str, update_time: object) -> int | None:
    end = _seconds(raw_end)
    if status == DEACTIVATED:
        updated = _seconds(update_time)
        if updated is not None:
            end = updated if end is None else min(end, updated)
    return end


@dataclass(frozen=True)
class Promotion:
    """One seller promotion activity (not a voucher)."""

    activity_id: str
    kind: PromoKind
    title: str
    begin: int
    #: ``None`` when open-ended.
    end: int | None
    #: Product ids from the activity detail; ``None`` when the detail was not fetched.
    products: frozenset[str] | None
    #: ``{product: {sku: activity price}}`` (flash sales, fixed-price discounts).
    sku_prices: dict[str, dict[str, float]]
    #: ``{product: {sku: discount percent}}`` (percentage product discounts).
    sku_discounts: dict[str, dict[str, float]]

    def covers(self, product_id: str | None) -> bool:
        """Applies to ``product_id`` (or to the shop when ``None``); unknown lists count."""
        return product_id is None or self.products is None or product_id in self.products

    def running_at(self, moment: int) -> bool:
        return self.begin <= moment and (self.end is None or moment < self.end)


@dataclass(frozen=True)
class Voucher:
    coupon_id: str
    title: str
    begin: int
    end: int | None
    threshold: float | None
    amount_off: float | None
    percent_off: float | None
    specific_products: bool
    claim_limit: int | None


def _sku_maps(detail: dict) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    prices: dict[str, dict[str, float]] = {}
    discounts: dict[str, dict[str, float]] = {}
    for product in detail.get("products") or []:
        if not isinstance(product, dict) or not product.get("id"):
            continue
        pid = str(product["id"])
        for sku in product.get("skus") or []:
            if not isinstance(sku, dict) or not sku.get("id"):
                continue
            price = to_float(sku.get("activity_price"))
            if price > 0:
                prices.setdefault(pid, {})[str(sku["id"])] = price
            percent = to_float(sku.get("discount"))
            if percent > 0:
                discounts.setdefault(pid, {})[str(sku["id"])] = percent
        product_price = to_float(product.get("activity_price"))
        product_percent = to_float(product.get("discount"))
        if product_price > 0:
            prices.setdefault(pid, {})["*"] = product_price
        if product_percent > 0:
            discounts.setdefault(pid, {})["*"] = product_percent
    return prices, discounts


def parse_activities(activities: list[dict], details: dict[str, dict]) -> list[Promotion]:
    """Every activity that ran, deduplicated by id, with its products when known."""
    out: list[Promotion] = []
    seen: set[str] = set()
    for activity in activities:
        activity_id = str(activity.get("id") or activity.get("activity_id") or "")
        status = str(activity.get("status") or "")
        if not activity_id or activity_id in seen or status in SKIPPED_STATUSES:
            continue
        seen.add(activity_id)
        begin = _seconds(activity.get("begin_time"))
        if begin is None:
            continue
        detail = details.get(activity_id)
        has_products = isinstance(detail, dict) and isinstance(detail.get("products"), list)
        prices, discounts = _sku_maps(detail) if isinstance(detail, dict) else ({}, {})
        products = (
            frozenset(
                str(p["id"])
                for p in (detail or {}).get("products") or []
                if isinstance(p, dict) and p.get("id")
            )
            if has_products
            else None
        )
        out.append(
            Promotion(
                activity_id,
                ACTIVITY_KINDS.get(str(activity.get("activity_type") or ""), PromoKind.OTHER),
                str(activity.get("title") or ""),
                begin,
                _end(activity.get("end_time"), status, activity.get("update_time")),
                products,
                prices,
                discounts,
            )
        )
    return out


def parse_vouchers(coupons: list[dict]) -> list[Voucher]:
    out: list[Voucher] = []
    seen: set[str] = set()
    for coupon in coupons:
        coupon_id = str(coupon.get("id") or "")
        status = str(coupon.get("status") or "")
        if not coupon_id or coupon_id in seen or status in SKIPPED_STATUSES:
            continue
        seen.add(coupon_id)
        duration = (
            coupon.get("claim_duration") if isinstance(coupon.get("claim_duration"), dict) else {}
        )
        begin = _seconds((duration or {}).get("start_time"))
        if begin is None:
            continue
        threshold_raw = coupon.get("threshold") if isinstance(coupon.get("threshold"), dict) else {}
        threshold = to_float((threshold_raw or {}).get("min_spend")) or None
        discount = coupon.get("discount") if isinstance(coupon.get("discount"), dict) else {}
        amount = to_float((discount or {}).get("reduction_amount")) or None
        percent = to_float((discount or {}).get("percentage")) or None
        limits = coupon.get("usage_limits") if isinstance(coupon.get("usage_limits"), dict) else {}
        claim_limit = int(to_float((limits or {}).get("redemption_limit"))) or None
        out.append(
            Voucher(
                coupon_id,
                str(coupon.get("title") or ""),
                begin,
                _end((duration or {}).get("end_time"), status, coupon.get("update_time")),
                threshold,
                amount,
                percent,
                str(coupon.get("product_scope") or "") == "SPECIFIC_PRODUCTS",
                claim_limit,
            )
        )
    return out


def _span_days(begin: int, end: int | None, days: list[date]) -> list[date]:
    """The days of ``days`` the interval ``[begin, end)`` touches."""
    stop = end if end is not None else day_start(days[-1]) + DAY_SECONDS
    return [d for d in days if begin < day_start(d) + DAY_SECONDS and stop > day_start(d)]


def coverage_by_day(
    intervals: Iterable[tuple[int, int | None]], days: list[date]
) -> dict[date, float]:
    """Per day, the share of its 24 hours inside the union of ``intervals``."""
    horizon = day_start(days[-1]) + DAY_SECONDS if days else 0
    merged: list[list[int]] = []
    for begin, end in sorted((b, e if e is not None else horizon) for b, e in intervals):
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end])
    out: dict[date, float] = {}
    for day in days:
        lo, hi = day_start(day), day_start(day) + DAY_SECONDS
        covered = sum(max(0, min(hi, e) - max(lo, b)) for b, e in merged)
        out[day] = covered / DAY_SECONDS
    return out


@dataclass(frozen=True)
class Band:
    """One promotion drawn as a date band (d.9), with its days in each window."""

    kind: PromoKind
    title: str
    first: date
    last: date
    days_prior: int
    days_last: int


def bands(
    promotions: list[Promotion],
    vouchers: list[Voucher],
    windows: Windows,
    product_id: str | None = None,
) -> list[Band]:
    """Flash sales, product discounts and vouchers overlapping the 60 days."""
    days = windows.all_days()
    prior, last = set(windows.prior_days()), set(windows.last_days())
    out: list[Band] = []
    spans: list[tuple[PromoKind, str, int, int | None]] = [
        (p.kind, p.title, p.begin, p.end)
        for p in promotions
        if p.kind in (PromoKind.FLASH, PromoKind.DISCOUNT) and p.covers(product_id)
    ]
    spans += [
        (PromoKind.VOUCHER, v.title, v.begin, v.end)
        for v in vouchers
        if product_id is None or not v.specific_products
    ]
    for kind, title, begin, end in spans:
        touched = _span_days(begin, end, days)
        if touched:
            out.append(
                Band(
                    kind,
                    title,
                    touched[0],
                    touched[-1],
                    sum(1 for d in touched if d in prior),
                    sum(1 for d in touched if d in last),
                )
            )
    return sorted(out, key=lambda b: (b.first, b.kind))


# --------------------------------------------------------------------------
# flash sales
# --------------------------------------------------------------------------


class DayGroup(StrEnum):
    PRE_FLASH = "Trước khi có flash sale"
    FLASH = "Ngày có flash sale"
    NON_FLASH = "Ngày không có flash sale"


@dataclass(frozen=True)
class DayGroupCell:
    group: DayGroup
    days: int
    sku_orders: float
    ctor: float | None
    orders_per_cart: float | None
    sufficient: bool


class FlashFlag(StrEnum):
    CONTINUOUS = "Flash gần như liên tục"
    SHALLOW = "Flash quá nông"
    WAITING = "Khách chờ flash"


@dataclass(frozen=True)
class FlashAnalysis:
    coverage: dict[date, float]
    #: ``(Monday of the week, mean daily coverage)`` over the 60 days.
    weekly: tuple[tuple[date, float], ...]
    coverage_last: float
    coverage_prior: float
    flash_days_last: int
    flash_days_prior: int
    #: Median true depth (flash price vs the already-discounted price), and vs list price.
    true_depth: float | None
    list_depth: float | None
    cells: tuple[DayGroupCell, ...]
    flags: tuple[FlashFlag, ...]
    #: Flash sales overlapping the 60 days whose product list was not fetched.
    unattributed: int


def _weekly(coverage: dict[date, float]) -> tuple[tuple[date, float], ...]:
    weeks: dict[date, list[float]] = {}
    for day, share in sorted(coverage.items()):
        weeks.setdefault(day - timedelta(days=day.weekday()), []).append(share)
    return tuple((monday, sum(v) / len(v)) for monday, v in sorted(weeks.items()))


def _base_price(
    promotions: list[Promotion],
    product_id: str,
    sku_id: str,
    moment: int,
    list_price: float | None,
) -> float | None:
    """The price before the flash sale: list price lowered by any running product discount."""
    candidates = [list_price] if list_price else []
    for promo in promotions:
        if promo.kind is not PromoKind.DISCOUNT or not promo.running_at(moment):
            continue
        prices = promo.sku_prices.get(product_id, {})
        fixed = prices.get(sku_id) or prices.get("*")
        if fixed:
            candidates.append(fixed)
        percents = promo.sku_discounts.get(product_id, {})
        percent = percents.get(sku_id) or percents.get("*")
        if percent and list_price:
            candidates.append(list_price * (1 - percent / 100))
    return min(candidates) if candidates else None


def flash_depths(
    promotions: list[Promotion],
    windows: Windows,
    snapshot: Snapshot,
    product_ids: Iterable[str],
) -> tuple[float | None, float | None]:
    """Median (true depth, depth vs list price) over the flash SKUs of the 60 days."""
    window_lo = day_start(windows.prior_first)
    window_hi = day_start(windows.last_last) + DAY_SECONDS
    true_depths: list[float] = []
    list_depths: list[float] = []
    for product_id in product_ids:
        list_prices = snapshot.list_prices(product_id)
        for promo in promotions:
            if promo.kind is not PromoKind.FLASH or promo.begin >= window_hi:
                continue
            if promo.end is not None and promo.end <= window_lo:
                continue
            for sku_id, flash_price in promo.sku_prices.get(product_id, {}).items():
                list_price = list_prices.get(sku_id)
                base = _base_price(promotions, product_id, sku_id, promo.begin, list_price)
                if base and base > 0:
                    true_depths.append(1 - flash_price / base)
                if list_price:
                    list_depths.append(1 - flash_price / list_price)
    return (
        statistics.median(true_depths) if true_depths else None,
        statistics.median(list_depths) if list_depths else None,
    )


def _cell(
    group: DayGroup, days: list[date], card_by_day: dict[date, Counts], config: ShopDiagnosisConfig
) -> DayGroupCell:
    total = Counts()
    for day in days:
        total = total + card_by_day.get(day, Counts())
    orders = total.sku_orders or 0.0
    return DayGroupCell(
        group,
        len(days),
        orders,
        total.ctor,
        total.orders_per_add_to_cart,
        len(days) >= config.day_group_min_days and orders >= config.day_group_min_orders,
    )


def analyse_flash(
    promotions: list[Promotion],
    windows: Windows,
    snapshot: Snapshot,
    card_by_day: dict[date, Counts],
    config: ShopDiagnosisConfig,
    product_id: str | None = None,
) -> FlashAnalysis:
    """Coverage, depth, day groups and flags for one product, or the shop when ``None``."""
    days = windows.all_days()
    window_lo, window_hi = day_start(days[0]), day_start(days[-1]) + DAY_SECONDS
    flashes = [
        p
        for p in promotions
        if p.kind is PromoKind.FLASH
        and p.covers(product_id)
        and p.begin < window_hi
        and (p.end is None or p.end > window_lo)
    ]
    coverage = coverage_by_day(((p.begin, p.end) for p in flashes), days)
    flash_days = {d for d, share in coverage.items() if share >= config.flash_day_coverage}
    prior_days, last_days = windows.prior_days(), windows.last_days()
    first_flash = min(flash_days) if flash_days else None
    groups = {
        DayGroup.PRE_FLASH: [d for d in days if first_flash is None or d < first_flash],
        DayGroup.FLASH: sorted(flash_days),
        DayGroup.NON_FLASH: [
            d for d in days if first_flash is not None and d >= first_flash and d not in flash_days
        ],
    }
    cells = tuple(_cell(g, groups[g], card_by_day, config) for g in DayGroup)
    weekly = _weekly(coverage)
    coverage_last = sum(coverage[d] for d in last_days) / len(last_days)
    products = [product_id] if product_id else sorted(snapshot.products)
    true_depth, list_depth = flash_depths(promotions, windows, snapshot, products)

    flags: list[FlashFlag] = []
    if coverage_last > config.flash_continuous_window or any(
        share > config.flash_continuous_week for _, share in weekly
    ):
        flags.append(FlashFlag.CONTINUOUS)
    if true_depth is not None and true_depth < config.flash_shallow_depth:
        flags.append(FlashFlag.SHALLOW)
    pre, flash, non = cells
    if all(c.sufficient and c.orders_per_cart is not None for c in cells):
        if (non.orders_per_cart or 0) < min(flash.orders_per_cart or 0, pre.orders_per_cart or 0):
            flags.append(FlashFlag.WAITING)
    return FlashAnalysis(
        coverage,
        weekly,
        coverage_last,
        sum(coverage[d] for d in prior_days) / len(prior_days),
        sum(1 for d in last_days if d in flash_days),
        sum(1 for d in prior_days if d in flash_days),
        true_depth,
        list_depth,
        cells,
        tuple(flags),
        sum(1 for p in flashes if p.products is None),
    )


# --------------------------------------------------------------------------
# vouchers
# --------------------------------------------------------------------------


class VoucherClass(StrEnum):
    CLOSING = "Chốt đơn"
    RAISE_VALUE = "Nâng giá trị đơn"
    MULTI_ITEM = "Đơn nhiều món"
    PERSONAL = "Cá nhân / bù khách"


SPECIFIC_PRODUCTS_LABEL = "Riêng sản phẩm"


def order_value(order: dict) -> float:
    """What the buyer paid for the items (after discounts), else the line prices summed."""
    payment = order.get("payment") if isinstance(order.get("payment"), dict) else {}
    value = to_float((payment or {}).get("sub_total"))
    if value > 0:
        return value
    return sum(to_float(line.get("sale_price")) for line in live_lines(order))


def single_item_values(orders: list[dict] | None, first: date, last: date) -> list[float]:
    """Values of the kept orders with exactly one non-gift unit, created in ``first..last``."""
    return [
        order_value(o)
        for o in kept(orders_between(orders, first, last))
        if len(live_lines(o)) == 1 and order_value(o) > 0
    ]


@dataclass(frozen=True)
class PriceYardstick:
    """Giá một món phổ biến and the Chốt đơn cut, from single-item orders of the last 30 days."""

    common_price: float
    closing_cut: float
    sample: int


def yardstick(
    orders: list[dict] | None, windows: Windows, config: ShopDiagnosisConfig
) -> PriceYardstick | None:
    values = sorted(single_item_values(orders, windows.last_first, windows.last_last))
    if len(values) < 2:
        return None
    cut_index = (1 - config.closing_order_share) * (len(values) - 1)
    lo = int(cut_index)
    hi = min(lo + 1, len(values) - 1)
    cut = values[lo] + (values[hi] - values[lo]) * (cut_index - lo)
    return PriceYardstick(statistics.median(values), cut, len(values))


def classify_voucher(
    voucher: Voucher, stick: PriceYardstick, config: ShopDiagnosisConfig
) -> tuple[VoucherClass, bool]:
    """``(class, specific-products scope)`` from the voucher's configuration."""
    if voucher.claim_limit is not None and 1 <= voucher.claim_limit <= config.personal_max_claims:
        return VoucherClass.PERSONAL, voucher.specific_products
    threshold = voucher.threshold or 0.0
    if threshold <= 0 or threshold <= stick.closing_cut:
        kind = VoucherClass.CLOSING
    elif threshold < config.multi_item_multiple * stick.common_price:
        kind = VoucherClass.RAISE_VALUE
    else:
        kind = VoucherClass.MULTI_ITEM
    return kind, voucher.specific_products


@dataclass(frozen=True)
class VoucherAnalysis:
    voucher: Voucher
    voucher_class: VoucherClass
    specific_products: bool
    first: date
    last: date
    #: Discount as a share of giá một món phổ biến.
    discount_share: float | None
    #: Share of orders during the voucher within ``near_threshold_band`` below the threshold.
    near_threshold_share: float | None
    #: Share of orders at or above the threshold, before vs after the start date.
    above_before: float | None
    above_after: float | None
    #: Upper bound: orders at or above the threshold while it ran, and their cost.
    redemptions_upper: int
    cost_upper: float
    overlaps_flash: bool


@dataclass(frozen=True)
class VoucherSummary:
    yardstick: PriceYardstick | None
    live: tuple[VoucherAnalysis, ...]
    #: ``(YYYY-MM, class label, count)`` for vouchers that ended before the 60 days.
    older_by_month: tuple[tuple[str, str, int], ...]


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _discount_amount(voucher: Voucher, value: float) -> float:
    if voucher.amount_off:
        return voucher.amount_off
    if voucher.percent_off:
        return value * voucher.percent_off / 100
    return 0.0


def analyse_vouchers(
    vouchers: list[Voucher],
    orders: list[dict] | None,
    windows: Windows,
    flash_days: set[date],
    config: ShopDiagnosisConfig,
) -> VoucherSummary:
    stick = yardstick(orders, windows, config)
    if stick is None:
        return VoucherSummary(None, (), ())
    days = windows.all_days()
    kept_orders = kept(orders_between(orders, days[0], days[-1]))
    live: list[VoucherAnalysis] = []
    older: Counter[tuple[str, str]] = Counter()
    for voucher in vouchers:
        kind, specific = classify_voucher(voucher, stick, config)
        label = kind.value + (f" · {SPECIFIC_PRODUCTS_LABEL}" if specific else "")
        touched = _span_days(voucher.begin, voucher.end, days)
        if not touched:
            if voucher.end is not None and local_day(voucher.end) < days[0]:
                older[(local_day(voucher.begin).strftime("%Y-%m"), label)] += 1
            continue
        touched_set = set(touched)
        during = [o for o in kept_orders if create_day(o) in touched_set]
        values = [order_value(o) for o in during]
        threshold = voucher.threshold or 0.0
        start = local_day(voucher.begin)
        mix = timedelta(days=config.voucher_mix_days)
        before = [
            order_value(o)
            for o in kept_orders
            if (d := create_day(o)) is not None and start - mix <= d < start
        ]
        after = [
            order_value(o)
            for o in kept_orders
            if (d := create_day(o)) is not None and start <= d < start + mix
        ]
        above = [v for v in values if v >= threshold]
        near = [v for v in values if threshold * (1 - config.near_threshold_band) <= v < threshold]
        base_discount = _discount_amount(voucher, stick.common_price)
        live.append(
            VoucherAnalysis(
                voucher,
                kind,
                specific,
                touched[0],
                touched[-1],
                base_discount / stick.common_price if stick.common_price else None,
                _share(len(near), len(values)) if threshold > 0 else None,
                _share(sum(1 for v in before if v >= threshold), len(before))
                if start >= days[0]
                else None,
                _share(sum(1 for v in after if v >= threshold), len(after)),
                len(above),
                sum(_discount_amount(voucher, v) for v in above),
                any(start <= d < start + mix for d in flash_days),
            )
        )
    return VoucherSummary(
        stick,
        tuple(sorted(live, key=lambda a: a.first)),
        tuple((month, label, n) for (month, label), n in sorted(older.items())),
    )


# --------------------------------------------------------------------------
# per-product discounts on orders (d.8 part 5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderDiscountShare:
    """Share of a product's items carrying a platform discount and a seller discount."""

    items: int
    platform_share: float | None
    seller_share: float | None


def order_discount_share(
    orders: list[dict] | None, product_id: str, first: date, last: date
) -> OrderDiscountShare:
    lines = [
        line
        for order in kept(orders_between(orders, first, last))
        for line in live_lines(order)
        if str(line.get("product_id")) == product_id
    ]
    return OrderDiscountShare(
        len(lines),
        _share(sum(1 for x in lines if to_float(x.get("platform_discount")) > 0), len(lines)),
        _share(sum(1 for x in lines if to_float(x.get("seller_discount")) > 0), len(lines)),
    )
