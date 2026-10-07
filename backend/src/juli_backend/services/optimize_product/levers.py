"""Lever checks the report adds in ADR-106 amendment 5, as pure functions.

* shipping discount: share of the product's orders where the buyer paid shipping;
* gift with purchase: choosing the gift product of the same shop;
* shop flash sale: the guards and the proposed price;
* Seller Center levers (review voucher, bundle deal, minimum-spend voucher): data
  reasons only, since Juli cannot create these through the API.

Callers hand in orders already cut to the right creation-time window
(:mod:`~juli_backend.services.optimize_product.order_windows`); nothing here
reads a window on its own.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from itertools import combinations

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.funnel import to_decimal
from juli_backend.services.optimize_product.order_windows import kept, live_lines
from juli_backend.services.optimize_product.promotions import PromotionIndex

ZERO = Decimal(0)
FLASH_KIND = "Flash sale"
PRODUCT_DISCOUNT_KIND = "Giảm giá sản phẩm"

# --------------------------------------------------------------------------- shipping


@dataclass(frozen=True)
class ShippingEval:
    orders: int
    paid_orders: int
    share: Decimal | None
    #: ``insufficient_orders`` | ``below_share`` | ``ok``
    verdict: str

    @property
    def ok(self) -> bool:
        return self.verdict == "ok"


def shipping_eval(product_orders: list[dict], config: StageDiagnosisConfig) -> ShippingEval:
    """Share of the product's orders whose ``payment.shipping_fee`` is above zero."""
    total = len(product_orders)
    paid = sum(
        1
        for order in product_orders
        if isinstance(order.get("payment"), dict)
        and to_decimal(order["payment"].get("shipping_fee")) > 0
    )
    if total < config.shipping_lever_min_orders:
        return ShippingEval(total, paid, None, "insufficient_orders")
    share = Decimal(paid) / Decimal(total)
    verdict = "ok" if share >= config.shipping_lever_min_paid_share else "below_share"
    return ShippingEval(total, paid, share, verdict)


# --------------------------------------------------------------------------- stock (gift)


@dataclass(frozen=True)
class ProductStock:
    """What a GetProduct payload says about one product's price, stock and warehouses."""

    product_id: str
    title: str
    price: Decimal | None
    stock: int
    warehouses: frozenset[str]
    #: SKU id -> list (sale) price.
    sku_prices: dict[str, Decimal] = field(default_factory=dict)


def product_stock(product_id: str, detail: dict | None) -> ProductStock | None:
    """Parse a GetProduct payload; ``None`` without a payload."""
    if not isinstance(detail, dict):
        return None
    stock = 0
    warehouses: set[str] = set()
    prices: dict[str, Decimal] = {}
    for sku in detail.get("skus") or []:
        if not isinstance(sku, dict):
            continue
        for entry in sku.get("inventory") or []:
            if not isinstance(entry, dict):
                continue
            stock += int(to_decimal(entry.get("quantity")))
            if entry.get("warehouse_id"):
                warehouses.add(str(entry["warehouse_id"]))
        price = sku.get("price")
        amount = to_decimal(price.get("sale_price")) if isinstance(price, dict) else Decimal(0)
        if amount > 0 and sku.get("id"):
            prices[str(sku["id"])] = amount
    return ProductStock(
        product_id=product_id,
        title=str(detail.get("title") or product_id),
        price=min(prices.values()) if prices else None,
        stock=stock,
        warehouses=frozenset(warehouses),
        sku_prices=prices,
    )


@dataclass(frozen=True)
class GiftChoice:
    product_id: str
    title: str
    price: Decimal
    stock: int
    review_count: int | None


@dataclass(frozen=True)
class GiftSearch:
    choice: GiftChoice | None
    evaluated: int
    #: Candidates dropped, by the first rule that dropped them.
    rejected: dict[str, int]
    max_price: Decimal | None


def find_gift(
    main: ProductStock | None,
    aov: Decimal | None,
    candidates: list[ProductStock],
    review_counts: dict[str, int] | None,
    config: StageDiagnosisConfig,
) -> GiftSearch:
    """The gift for ``main``: fewest reviews when known, else the cheapest.

    A candidate is a product of the same shop, in stock (more than
    ``gift_min_stock`` units over its SKUs), sharing a warehouse with the main
    product, priced at most ``gift_max_price_share`` of the main product's 30-day
    AOV and at most ``gift_max_price_vnd``.
    """
    rejected: Counter[str] = Counter()
    if main is None or aov is None or aov <= 0:
        return GiftSearch(None, 0, {}, None)
    cap = min(aov * config.gift_max_price_share, config.gift_max_price_vnd)
    pool: list[ProductStock] = []
    for cand in candidates:
        if cand.product_id == main.product_id:
            continue
        if cand.stock <= config.gift_min_stock:
            rejected["stock"] += 1
        elif not (cand.warehouses & main.warehouses):
            rejected["warehouse"] += 1
        elif cand.price is None or cand.price > cap:
            rejected["price"] += 1
        else:
            pool.append(cand)
    evaluated = len(pool) + sum(rejected.values())
    if not pool:
        return GiftSearch(None, evaluated, dict(rejected), cap)

    def key(c: ProductStock) -> tuple[int, int, Decimal, str]:
        reviews = (review_counts or {}).get(c.product_id)
        # With a review file, products with a known count come first, fewest first.
        if review_counts is None:
            return (0, 0, c.price or ZERO, c.product_id)
        return (0 if reviews is not None else 1, reviews or 0, c.price or ZERO, c.product_id)

    best = min(pool, key=key)
    reviews = (review_counts or {}).get(best.product_id)
    return GiftSearch(
        GiftChoice(best.product_id, best.title, best.price or ZERO, best.stock, reviews),
        evaluated,
        dict(rejected),
        cap,
    )


# --------------------------------------------------------------------------- flash sale


@dataclass(frozen=True)
class FlashEval:
    ok: bool
    #: Codes of the guards that failed (empty when ``ok``).
    failed: tuple[str, ...]
    days: int
    #: Lowest unit price paid over the look-back window (any SKU), and the proposal.
    low_price: Decimal | None
    proposed_price: Decimal | None
    #: Implied discount against the list price of the SKU the price came from.
    discount: Decimal | None
    price_sku_id: str | None = None


def paid_unit_price(line: dict) -> Decimal:
    """What the buyer paid per unit: ``sale_price`` less the platform's share."""
    return max(to_decimal(line.get("sale_price")) - to_decimal(line.get("platform_discount")), ZERO)


def recent_flash(promotions: PromotionIndex, product_id: str, as_of: date, days: int) -> bool:
    """A flash sale of the product overlaps the last ``days`` days (per the promotion data)."""
    first = (as_of - timedelta(days=days - 1)).isoformat()
    for item in promotions.by_product.get(product_id, []):
        if (
            item.kind == FLASH_KIND
            and item.begin <= as_of.isoformat()
            and (not item.end or item.end >= first)
        ):
            return True
    return False


def product_discount_active(promotions: PromotionIndex | None, product_id: str) -> bool:
    """A product discount from any source runs on the product on the window's last day."""
    if promotions is None:
        return False
    return any(
        item.kind == PRODUCT_DISCOUNT_KIND and item.active_at_end
        for item in promotions.by_product.get(product_id, [])
    )


def flash_eval(
    *,
    product_id: str,
    orders_low_window: list[dict],
    stock: ProductStock | None,
    promotions: PromotionIndex | None,
    as_of: date,
    max_discount_percent: Decimal | None,
    config: StageDiagnosisConfig,
) -> FlashEval:
    """Every guard of the flash sale; ``orders_low_window`` are this product's orders of
    the last ``flash_low_price_days`` days."""
    failed: list[str] = []
    days = config.flash_default_days
    if promotions is None:
        failed.append("promotion_data_missing")
    elif recent_flash(promotions, product_id, as_of, config.flash_recent_days):
        failed.append("flash_sale_in_last_14_days")
    if max_discount_percent is None:
        failed.append("max_discount_not_set")
    if not config.flash_min_days <= days <= config.flash_max_days:
        failed.append("duration_out_of_range")

    # Lowest paid unit price over the window, with the SKU that paid it.
    low: Decimal | None = None
    low_sku: str | None = None
    for order in kept(orders_low_window):
        for line in live_lines(order):
            if str(line.get("product_id")) != product_id:
                continue
            price = paid_unit_price(line)
            if price > 0 and (low is None or price < low):
                low, low_sku = price, str(line.get("sku_id") or "") or None
    if low is None:
        failed.append("no_orders_in_window")
        return FlashEval(False, tuple(failed), days, None, None, None)

    proposed = (low * (1 - config.flash_undercut) / 100).to_integral_value(
        rounding=ROUND_FLOOR
    ) * 100
    list_price = (stock.sku_prices.get(low_sku or "") if stock else None) or (
        stock.price if stock else None
    )
    discount: Decimal | None = None
    if not list_price or list_price <= 0:
        failed.append("list_price_unknown")
    else:
        discount = Decimal(1) - proposed / list_price
        if max_discount_percent is not None and discount * 100 > max_discount_percent:
            failed.append("discount_over_maximum")
    return FlashEval(not failed, tuple(failed), days, low, proposed, discount, low_sku)


# --------------------------------------------------------------------------- Seller Center


@dataclass(frozen=True)
class BundlePair:
    first: str
    second: str
    together: int
    orders_first: int
    orders_second: int

    @property
    def share_first(self) -> Decimal:
        return Decimal(self.together) / Decimal(self.orders_first)

    @property
    def share_second(self) -> Decimal:
        return Decimal(self.together) / Decimal(self.orders_second)


def bundle_pairs(
    orders: list[dict], live_ids: set[str], config: StageDiagnosisConfig
) -> list[BundlePair]:
    """Product pairs bought together in at least ``bundle_min_pair_orders`` orders and
    ``bundle_min_share`` of either product's orders; most frequent pair first."""
    per_product: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    for order in kept(orders):
        ids = sorted({str(line["product_id"]) for line in live_lines(order)} & live_ids)
        per_product.update(ids)
        pairs.update(combinations(ids, 2))
    out = [
        BundlePair(a, b, n, per_product[a], per_product[b])
        for (a, b), n in pairs.items()
        if n >= config.bundle_min_pair_orders
        and max(Decimal(n) / per_product[a], Decimal(n) / per_product[b]) >= config.bundle_min_share
    ]
    return sorted(out, key=lambda p: (-p.together, p.first, p.second))


@dataclass(frozen=True)
class MinSpendEval:
    orders: int
    multi_orders: int
    multi_share: Decimal | None
    aov_current: Decimal | None
    aov_previous: Decimal | None
    #: Relative AOV fall (positive = fell).
    aov_drop: Decimal | None
    level: Decimal | None
    #: ``no_orders`` | ``few_multi`` | ``aov_not_down`` | ``ok``
    verdict: str

    @property
    def ok(self) -> bool:
        return self.verdict == "ok"


def multi_product_orders(orders: list[dict]) -> tuple[int, int]:
    """(non-cancelled orders, those with two or more different products)."""
    total = multi = 0
    for order in kept(orders):
        ids = {str(line["product_id"]) for line in live_lines(order)}
        if ids:
            total += 1
            multi += 1 if len(ids) >= 2 else 0
    return total, multi


def min_spend_eval(
    orders: list[dict],
    aov_current: Decimal | None,
    aov_previous: Decimal | None,
    config: StageDiagnosisConfig,
) -> MinSpendEval:
    total, multi = multi_product_orders(orders)
    drop: Decimal | None = None
    if aov_current is not None and aov_previous is not None and aov_previous > 0:
        drop = Decimal(1) - aov_current / aov_previous
    if total == 0:
        return MinSpendEval(0, 0, None, aov_current, aov_previous, drop, None, "no_orders")
    share = Decimal(multi) / Decimal(total)
    level = None
    if aov_current is not None:
        step = Decimal(config.min_spend_round_vnd)
        level = (aov_current * config.min_spend_aov_multiple / step).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        ) * step
    if share < config.min_spend_min_multi_share:
        verdict = "few_multi"
    elif drop is None or drop < config.min_spend_aov_drop:
        verdict = "aov_not_down"
    else:
        verdict = "ok"
    return MinSpendEval(total, multi, share, aov_current, aov_previous, drop, level, verdict)
