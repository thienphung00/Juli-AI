"""Seller promotions that overlap a window, per product (ADR-106 amendment 4).

Parses the raw ``activities/search`` / ``coupons/search`` payloads and the
``activities/{id}`` details the live fetch saved (see
``scripts/shop_optimization_report.py``). The search response carries no product
list, so product membership comes from the detail's ``products[]``; activities
without a detail are counted as unattributed rather than guessed. A coupon with
``product_scope == FULL_SHOP`` applies to every product; a
``SPECIFIC_PRODUCTS`` coupon needs ``get_coupon``, which production-read does
not allow, so it is counted as unattributed too.

Pure. Times are unix seconds; dates are read in the shop's timezone (UTC+7).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from juli_backend.services.optimize_product.funnel import to_decimal

SHOP_UTC_OFFSET_HOURS = 7
VOUCHER = "Voucher"
GIFT = "Quà tặng kèm"

TYPE_LABELS = {
    "FIXED_PRICE": "Giảm giá sản phẩm",
    "DIRECT_DISCOUNT": "Giảm giá sản phẩm",
    "FLASHSALE": "Flash sale",
    "BUY_MORE_SAVE_MORE": "Mua nhiều giảm nhiều",
    "SHIPPING_DISCOUNT": "Giảm phí vận chuyển",
}
SKIPPED_STATUSES = frozenset({"DRAFT", "DEACTIVATED", "NOT_EFFECTIVE"})


@dataclass(frozen=True)
class PromotionItem:
    kind: str
    title: str
    #: ISO dates in the shop's timezone; ``end`` is ``""`` when open-ended.
    begin: str
    end: str
    summary: str
    #: The promotion is running on the window's last day.
    active_at_end: bool


@dataclass(frozen=True)
class PromotionIndex:
    by_product: dict[str, list[PromotionItem]]
    #: Coupons that apply to the whole shop, shown on every product.
    shop_wide: list[PromotionItem]
    #: Overlapping activities / coupons whose products could not be listed.
    unattributed: int

    def for_product(self, product_id: str) -> list[PromotionItem]:
        return [*self.by_product.get(product_id, []), *self.shop_wide]


def _zone() -> timezone:
    return timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))


def _seconds(value: object) -> int | None:
    try:
        seconds = int(str(value))
    except ValueError:
        return None
    # The coupon sample shows millisecond create times; promotion windows are seconds.
    return seconds // 1000 if seconds > 10**11 else seconds


def _date(seconds: int) -> date:
    return datetime.fromtimestamp(seconds, tz=_zone()).date()


def _money(value: Decimal) -> str:
    return f"{int(value):,}".replace(",", ".") + " ₫"


def _activity_summary(activity: dict, product: dict | None) -> str:
    discount = activity.get("discount") if isinstance(activity.get("discount"), dict) else {}
    bmsm = discount.get("bmsm_discount") if isinstance(discount, dict) else None
    details = bmsm.get("details") if isinstance(bmsm, dict) else None
    if isinstance(details, list) and details:
        tier = details[0] if isinstance(details[0], dict) else {}
        return f"mua từ {tier.get('threshold_value', '?')} món giảm {tier.get('value', '?')} %"
    if product:
        percent = to_decimal(product.get("discount"))
        if percent > 0:
            return f"giảm {int(percent)} %"
        price = product.get("activity_price")
        amount = to_decimal(price.get("amount") if isinstance(price, dict) else price)
        if amount > 0:
            return f"giá {_money(amount)}"
    return ""


def _label(activity: dict) -> str:
    discount = activity.get("discount")
    gift = discount.get("gift_discount") if isinstance(discount, dict) else None
    if gift:
        return GIFT
    return TYPE_LABELS.get(str(activity.get("activity_type") or ""), "Khuyến mãi")


def _coupon_summary(coupon: dict) -> str:
    raw = coupon.get("discount")
    discount: dict = raw if isinstance(raw, dict) else {}
    if discount.get("type") == "PERCENT_OFF" and discount.get("percentage") is not None:
        return f"giảm {discount['percentage']} %"
    reduction = discount.get("reduction_amount")
    if isinstance(reduction, dict) and to_decimal(reduction.get("amount")) > 0:
        return f"giảm {_money(to_decimal(reduction['amount']))}"
    return ""


def _overlap(
    begin: int | None, end: int | None, window: tuple[date, date]
) -> tuple[date, date | None] | None:
    if begin is None:
        return None
    first = _date(begin)
    last = _date(end) if end else None
    if first > window[1] or (last is not None and last < window[0]):
        return None
    return first, last


def _item(
    kind: str, title: str, span: tuple[date, date | None], summary: str, window_end: date
) -> PromotionItem:
    first, last = span
    return PromotionItem(
        kind=kind,
        title=title,
        begin=first.isoformat(),
        end=last.isoformat() if last else "",
        summary=summary,
        active_at_end=first <= window_end and (last is None or last >= window_end),
    )


def unwrap_list(payload: object, key: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else payload
    value = source.get(key) if isinstance(source, dict) else payload
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def parse_promotions(
    activities_payload: object,
    coupons_payload: object,
    details: dict[str, object],
    window: tuple[date, date],
) -> PromotionIndex:
    """Index the promotions overlapping ``window`` (inclusive local dates) by product."""
    by_product: dict[str, list[PromotionItem]] = defaultdict(list)
    shop_wide: list[PromotionItem] = []
    unattributed = 0
    seen: set[str] = set()
    for activity in unwrap_list(activities_payload, "activities"):
        activity_id = str(activity.get("id") or "")
        if activity_id in seen or str(activity.get("status") or "") in SKIPPED_STATUSES:
            continue
        seen.add(activity_id)
        span = _overlap(
            _seconds(activity.get("begin_time")), _seconds(activity.get("end_time")), window
        )
        if span is None:
            continue
        raw = details.get(activity_id)
        detail = (
            raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
        )
        products = detail.get("products") if isinstance(detail, dict) else None
        if not isinstance(products, list) or not products:
            unattributed += 1
            continue
        merged = {**activity, **(detail if isinstance(detail, dict) else {})}
        title = str(activity.get("title") or merged.get("title") or "")
        for product in products:
            if isinstance(product, dict) and product.get("id"):
                by_product[str(product["id"])].append(
                    _item(
                        _label(merged),
                        title,
                        span,
                        _activity_summary(merged, product),
                        window[1],
                    )
                )
    for coupon in unwrap_list(coupons_payload, "coupons"):
        if str(coupon.get("status") or "") in SKIPPED_STATUSES:
            continue
        duration = coupon.get("claim_duration")
        duration = duration if isinstance(duration, dict) else {}
        span = _overlap(
            _seconds(duration.get("start_time")), _seconds(duration.get("end_time")), window
        )
        if span is None:
            continue
        if str(coupon.get("product_scope") or "") == "FULL_SHOP":
            shop_wide.append(
                _item(
                    VOUCHER,
                    str(coupon.get("title") or ""),
                    span,
                    _coupon_summary(coupon),
                    window[1],
                )
            )
        else:
            unattributed += 1
    return PromotionIndex(dict(by_product), shop_wide, unattributed)


def clause(items: list[PromotionItem]) -> str | None:
    """One short reason clause: a promotion running on the last day, else the latest one.

    A product's own promotions come before shop-wide vouchers.
    """
    if not items:
        return None
    running = [i for i in items if i.active_at_end]
    if running:
        item = max(running, key=lambda i: (i.kind != VOUCHER, i.end or "9999-12-31"))
        if item.end:
            return f"đang có {item.kind} đến {date.fromisoformat(item.end).strftime('%d/%m')}"
        return f"đang có {item.kind}"
    item = max(items, key=lambda i: (i.kind != VOUCHER, i.end or i.begin))
    return f"đã có {item.kind} trong 30 ngày qua"
