"""Per-shop optimization report: 30-day tables, 14/28-day cards, one HTML page.

Owner decisions (2026-10-07) this module encodes:

* Cards use the stage diagnosis windows — current 14 days against the prior
  28 days (``StageDiagnosisConfig``), the same pipeline as the catalog scan.
* Every analysis table uses 30 days against the previous 30 days
  (current = ``[as_of-29, as_of]``, previous = ``[as_of-59, as_of-30]``).
* "Chủ lực" is the top five products by current-30-day GMV, each with its
  share of shop GMV; "còn lại" is every other live product. Gift /
  not-for-sale titles (``StageDiagnosisConfig.exclude_title_patterns``) and
  products whose status is not ``ACTIVATE`` are excluded and counted.
* No review columns.

Pure: the only I/O is reading the snapshot directory handed in. Nothing here
imports TikTok, DB or worker code; the live fetch lives in
``scripts/shop_optimization_report.py``.

Snapshot layout (a superset of :mod:`catalog_scan`'s)::

    meta.json               {"as_of": "YYYY-MM-DD", "shop_name": optional}
    a34_current.json        A-34 products, current 14 days     (cards)
    a34_prior.json          A-34 products, prior 28 days       (cards)
    a34_last28.json         A-34 products, last 28 days        (cards, GMV_28d)
    a34_30d_current.json    A-34 products, current 30 days     (tables)
    a34_30d_previous.json   A-34 products, previous 30 days    (tables)
    products/<id>.json      GetProduct payload
    diagnoses/<id>.json     optional, one data.products[] entry of the diagnoses endpoint
    diagnoses/_error.json   optional
    orders.json             optional, {"orders": [...]} order search payloads, fetched by creation
                            time over the previous + current 30 days; every order-derived figure
                            reads only the orders created in its own window (ADR-106 amendment 5)
    ratings.json            optional, {"<product_id>": {"rating": 4.8, "review_count": 601}}
                            (the review count picks the gift product and the review-voucher card)
    owner_tests.json        optional, the owner's own tests (see ``_owner_cards``)
    promotions/activities.json       optional, {"activities": [...]} Search Activities pages
    promotions/coupons.json          optional, {"coupons": [...]} Search Coupons pages
    promotions/activity_details.json optional, {"<activity_id>": Get Activity payload}
    promotions/_error.json           optional, {"error_class", "message"}
    live/sessions.json               optional, {"sessions": [...]} top LIVE sessions by GMV
    live/products/<id>.json          optional, one session's product performance
    live/_error.json                 optional
    videos/videos.json               optional, {"videos": [...]} top shop videos by GMV
    videos/products/<id>.json        optional, one video's product performance
    videos/_error.json               optional
"""

from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from juli_backend.services.optimize_product import promotions as promo
from juli_backend.services.optimize_product.basket import (
    CANCELLED,
    basket_threshold,
    quantities_by_product,
    share_with_at_least,
)
from juli_backend.services.optimize_product.cards import (
    ANGLE_ACTION,
    NOT_ENOUGH_DATA,
    build_cards,
    gap_reason_sentence,
    main_kpi_value,
)
from juli_backend.services.optimize_product.catalog_scan import (
    a34_index,
    asked_products,
    build_inputs,
    diagnose_all,
    load_json,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.diagnosis import (
    BRANCH_ORDER,
    Angle,
    Branch,
    Gap,
    PageLevers,
    Trigger,
)
from juli_backend.services.optimize_product.discounts import (
    DiscountPair,
    WindowShare,
    discount_shares,
    empty_pair,
)
from juli_backend.services.optimize_product.funnel import (
    ZERO,
    FunnelWindow,
    ProductFunnel,
    to_decimal,
)
from juli_backend.services.optimize_product.levers import (
    FlashEval,
    GiftSearch,
    ProductStock,
    ShippingEval,
    bundle_pairs,
    find_gift,
    flash_eval,
    min_spend_eval,
    product_discount_active,
    product_stock,
    shipping_eval,
)
from juli_backend.services.optimize_product.listing_signals import (
    is_description_code,
    is_image_code,
    is_title_code,
    listing_signals_from_product,
)
from juli_backend.services.optimize_product.live_video import Appearance, parse_appearances
from juli_backend.services.optimize_product.order_windows import (
    orders_between,
    orders_by_product,
    summarize,
)
from juli_backend.services.optimize_product.promotions import PromotionIndex, PromotionItem
from juli_backend.services.optimize_product.traffic import (
    DILUTION,
    UNCLEAR,
    UNIFORM,
    TrafficAttribution,
    attribute_traffic,
    dilution_reason,
    source_clause,
)

WINDOW_DAYS = 30
TOP_N = 5
REST_ROWS = 10
HOW_TO_SOLVE_MAX = 140

STATUS_RULE = "Juli tự đề xuất"
STATUS_NEEDS_CAP = "Cần mức giảm giá tối đa"
STATUS_NOT_ASKED = "Chưa hỏi TikTok"
STATUS_OWNER = "Thử nghiệm theo kế hoạch của bạn"
STATUS_SC = "Bạn tự làm trên Seller Center"

WATCH_NO_FAULT = "TikTok không thấy lỗi ở trang sản phẩm"
WATCH_BASKET = "Rất ít đơn mua nhiều món cùng lúc, chưa nên làm mua nhiều giảm nhiều"
WATCH_NO_GIFT = "Không có sản phẩm phù hợp làm quà"
WATCH_DISCOUNT_RUNNING = "Đang có giảm giá sản phẩm và chưa đủ điều kiện làm flash sale"
NO_ORDERS_IN_WINDOW = "chưa đủ đơn trong khoảng thời gian"

#: Seller Center card kinds (``ReportCard.kind``).
KIND_REVIEW = "voucher_danh_gia"
KIND_BUNDLE = "uu_dai_theo_goi"
KIND_MIN_SPEND = "voucher_chi_tieu_toi_thieu"
KIND_GIFT = "gift_fallback"
SHOP_WIDE = "Toàn shop"
FLASH_CONFIRM = "cần xác nhận điểm vi phạm < 36 trước khi chạy"

#: Owner-test angles beyond the five diagnosis angles.
ANGLE_GIFT = "quà tặng kèm"
OWNER_ANGLES = (*(a.value for a in Angle), ANGLE_GIFT)
BASKET_ANGLES = (Angle.MUA_NHIEU_GIAM_NHIEU.value, ANGLE_GIFT)

# --------------------------------------------------------------------------- metrics

#: key, label, kind. Kind drives formatting only.
METRICS: tuple[tuple[str, str, str], ...] = (
    ("orders_per_day", "Đơn/ngày", "dec1"),
    ("gmv_per_day", "GMV/ngày", "money"),
    ("aov", "AOV", "money"),
    ("items_per_order", "Món/đơn", "dec2"),
    ("ctr", "CTR", "ratio"),
    ("add_to_cart_rate", "Thêm giỏ/click", "ratio"),
    ("ctor", "CTOR", "ratio"),
    ("refund_share", "Hoàn tiền/GMV", "ratio"),
    ("card_ctr", "CTR kênh thẻ sản phẩm", "ratio"),
    ("card_ctor", "CTOR kênh thẻ sản phẩm", "ratio"),
)


def money(value: object) -> Decimal:
    """``{amount, currency}`` dict or bare string/number -> Decimal."""
    if isinstance(value, dict):
        return to_decimal(value.get("amount"))
    return to_decimal(value)


def _ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return None if den <= 0 else num / den


@dataclass(frozen=True)
class Counts:
    """Raw A-34 counts for one product (or a sum of products) over one window."""

    orders: Decimal = ZERO
    items: Decimal = ZERO
    gmv: Decimal = ZERO
    impressions: Decimal = ZERO
    clicks: Decimal = ZERO
    add_cart: Decimal = ZERO
    refunds: Decimal = ZERO
    card_impressions: Decimal = ZERO
    card_clicks: Decimal = ZERO
    card_orders: Decimal = ZERO
    card_gmv: Decimal = ZERO

    def __add__(self, other: Counts) -> Counts:
        return Counts(*(getattr(self, f) + getattr(other, f) for f in self.__dataclass_fields__))

    @classmethod
    def from_item(cls, item: dict | None) -> Counts:
        item = item or {}
        total = item.get("total_performance") or {}
        card = FunnelWindow.from_a34_product_card(item, days=WINDOW_DAYS)
        return cls(
            orders=to_decimal(total.get("sku_orders")),
            items=to_decimal(total.get("items_sold")),
            gmv=money(total.get("gmv")),
            impressions=to_decimal(total.get("product_impressions")),
            clicks=to_decimal(total.get("product_clicks")),
            add_cart=to_decimal(total.get("add_cart_count")),
            refunds=money(total.get("refunds")),
            card_impressions=card.impressions if card else ZERO,
            card_clicks=card.clicks if card else ZERO,
            card_orders=card.sku_orders if card else ZERO,
            card_gmv=card.gmv if card else ZERO,
        )

    def metrics(self, days: int = WINDOW_DAYS) -> dict[str, Decimal | None]:
        return {
            "orders": self.orders,
            "orders_per_day": self.orders / Decimal(days),
            "gmv": self.gmv,
            "gmv_per_day": self.gmv / Decimal(days),
            "aov": _ratio(self.gmv, self.orders),
            "items_per_order": _ratio(self.items, self.orders),
            "impressions": self.impressions,
            "clicks": self.clicks,
            "ctr": _ratio(self.clicks, self.impressions),
            "add_to_cart_rate": _ratio(self.add_cart, self.clicks),
            "ctor": _ratio(self.orders, self.clicks),
            "refund_share": _ratio(self.refunds, self.gmv),
            "card_impressions": self.card_impressions,
            "card_clicks": self.card_clicks,
            "card_orders": self.card_orders,
            "card_gmv": self.card_gmv,
            "card_ctr": _ratio(self.card_clicks, self.card_impressions),
            "card_ctor": _ratio(self.card_orders, self.card_clicks),
        }


def window_metrics(item: dict | None, *, days: int = WINDOW_DAYS) -> dict[str, Decimal | None]:
    """KPI block for one A-34 product row; ``None`` ratios mean a zero denominator."""
    return Counts.from_item(item).metrics(days)


def change(cur: Decimal | None, prev: Decimal | None) -> dict[str, Decimal | None]:
    if cur is None or prev is None:
        return {"abs": None, "pct": None}
    return {"abs": cur - prev, "pct": None if prev == 0 else (cur - prev) / prev * 100}


@dataclass(frozen=True)
class Delta:
    current: Decimal | None
    previous: Decimal | None
    abs: Decimal | None
    pct: Decimal | None

    @classmethod
    def of(cls, cur: Decimal | None, prev: Decimal | None) -> Delta:
        diff = change(cur, prev)
        return cls(cur, prev, diff["abs"], diff["pct"])


@dataclass(frozen=True)
class MetricRow:
    key: str
    label: str
    kind: str
    delta: Delta


@dataclass(frozen=True)
class GroupRow:
    key: str
    label: str
    kind: str
    top: Delta
    rest: Delta


@dataclass(frozen=True)
class ProductBlock:
    product_id: str
    title: str
    rows: list[MetricRow]
    gmv_share: Delta
    #: Share of current-window orders by channel; only non-zero channels.
    channels: list[tuple[str, Decimal]]
    #: Platform- and seller-discounted share of order lines, both windows.
    discounts: DiscountPair


@dataclass(frozen=True)
class RestRow:
    product_id: str
    title: str
    impressions: Decimal
    clicks: Decimal
    orders: Decimal
    ctr: Decimal | None
    ctor: Decimal | None
    aov: Decimal | None


@dataclass(frozen=True)
class ReportCard:
    rank: int
    product_id: str
    title: str
    main_kpi: str
    main_kpi_value: str
    reason: str
    change: str
    status: str
    rank_score: Decimal
    #: Empty for diagnosis cards; a ``KIND_*`` for gift-fallback and Seller Center cards.
    kind: str = ""


@dataclass(frozen=True)
class WatchRow:
    """A product the report names but proposes nothing for, and why."""

    product_id: str
    title: str
    reason: str
    detail: str


@dataclass(frozen=True)
class DiagnosisRow:
    product_id: str
    title: str
    part: str
    how_to_solve: str
    suggested_images: int
    code: str


@dataclass(frozen=True)
class TrafficChannelRow:
    label: str
    impressions_per_day_previous: Decimal
    impressions_per_day_current: Decimal
    ctr_previous: Decimal | None
    ctr_current: Decimal | None
    #: Enough impressions in both windows to count towards the verdict.
    qualifies: bool
    spiking: bool
    ctr_dropped: bool


@dataclass(frozen=True)
class TrafficBlock:
    """The "Traffic đến từ đâu" entry of one product."""

    product_id: str
    title: str
    #: True when the product holds a card; False for a product whose card was
    #: withheld because the CTR fall is dilution.
    has_card: bool
    verdict: str
    top_impression_source: str
    channels: list[TrafficChannelRow]
    promotions: list[PromotionItem]
    discounts: DiscountPair
    appearances: list[Appearance]


@dataclass(frozen=True)
class ShopReport:
    shop_name: str
    as_of: str
    windows: dict[str, list[str]]
    exclusions: dict[str, int]
    shop_rows: list[MetricRow]
    group_rows: list[GroupRow]
    top_products: list[ProductBlock]
    rest_products: list[RestRow]
    cards: list[ReportCard]
    watch: list[WatchRow]
    diagnoses: list[DiagnosisRow]
    diagnoses_error: dict[str, str] | None
    traffic: list[TrafficBlock]
    technical: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------- formatting (vi-VN)


def _vn(value: Decimal, places: int) -> str:
    q = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = f"{q:,.{places}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def fmt_value(kind: str, value: Decimal | None) -> str:
    """Vietnamese number format: ``.`` thousands, ``,`` decimals, ``₫`` after money."""
    if value is None:
        return "—"
    if kind == "money":
        return f"{_vn(value, 0)} ₫"
    if kind == "ratio":
        return f"{_vn(value * 100, 2)} %"
    if kind == "dec1":
        return _vn(value, 1)
    if kind == "dec2":
        return _vn(value, 2)
    if kind == "pct":
        return f"{_vn(value, 0)} %"
    return _vn(value, 0)


def _signed(text: str, value: Decimal) -> str:
    return f"+{text}" if value > 0 else text


def fmt_abs_change(kind: str, delta: Delta) -> str:
    if delta.abs is None:
        return "—"
    if kind == "ratio":
        return _signed(f"{_vn(delta.abs * 100, 2)} điểm %", delta.abs)
    if kind == "money":
        return _signed(f"{_vn(delta.abs, 0)} ₫", delta.abs)
    return _signed(_vn(delta.abs, 2 if kind == "dec2" else 1), delta.abs)


def fmt_pct_change(delta: Delta) -> str:
    if delta.pct is None:
        return "—"
    return _signed(f"{_vn(delta.pct, 1)} %", delta.pct)


# --------------------------------------------------------------------------- build


def report_windows(as_of: date, config: StageDiagnosisConfig) -> dict[str, list[str]]:
    """Inclusive ``[first_day, last_day]`` ISO pairs for every window the report reads."""

    def span(first_back: int, last_back: int) -> list[str]:
        return [
            (as_of - timedelta(days=first_back)).isoformat(),
            (as_of - timedelta(days=last_back)).isoformat(),
        ]

    cur, prior = config.current_window_days, config.prior_window_days
    return {
        "current_30d": span(WINDOW_DAYS - 1, 0),
        "previous_30d": span(2 * WINDOW_DAYS - 1, WINDOW_DAYS),
        "card_current": span(cur - 1, 0),
        "card_prior": span(cur + prior - 1, cur),
        "card_last28": span(27, 0),
    }


def _detail(snapshot: Path, product_id: str) -> dict | None:
    raw = load_json(snapshot / "products" / f"{product_id}.json")
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    return data if isinstance(data, dict) else raw


def channel_shares(item: dict) -> list[tuple[str, Decimal]]:
    """Share (%) of a product's channel-attributed orders, non-zero channels only.

    TikTok attributes some orders to more than one channel block, so the shares
    are normalised over the sum of the five blocks and always total 100 %.
    """

    def block(name: str) -> dict:
        value = item.get(name)
        return value if isinstance(value, dict) else {}

    tab = block("shop_tab_performance")
    orders = (
        (
            "Thẻ sản phẩm",
            to_decimal(block("seller_product_card_performance").get("attributed_sku_orders")),
        ),
        (
            "Shop Tab",
            to_decimal(tab.get("shop_tab_product_clicks"))
            * to_decimal(tab.get("shop_tab_ctor_sku")),
        ),
        (
            "Video của shop",
            to_decimal(block("seller_video_performance").get("attributed_sku_orders")),
        ),
        (
            "LIVE của shop",
            to_decimal(block("seller_live_performance").get("attributed_sku_orders")),
        ),
        (
            "Affiliate",
            to_decimal(block("affiliate_total_performance").get("attributed_sku_orders")),
        ),
    )
    total = sum((n for _label, n in orders), ZERO)
    if total <= 0:
        return []
    return [(label, n / total * 100) for label, n in orders if n > 0]


def _rows(cur: dict[str, Decimal | None], prev: dict[str, Decimal | None]) -> list[MetricRow]:
    return [
        MetricRow(key, label, kind, Delta.of(cur[key], prev[key])) for key, label, kind in METRICS
    ]


def part_of(code: str) -> str:
    if is_image_code(code):
        return "Ảnh bìa"
    if is_title_code(code):
        return "Tiêu đề"
    if is_description_code(code):
        return "Mô tả"
    return "Khác"


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _diagnosis_rows(snapshot: Path, titles: dict[str, str], skip: set[str]) -> list[DiagnosisRow]:
    rows: list[DiagnosisRow] = []
    folder = snapshot / "diagnoses"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        entry = load_json(path)
        if path.name.startswith("_") or not isinstance(entry, dict):
            continue
        product_id = str(entry.get("id") or path.stem)
        if product_id in skip:
            continue
        for diag in entry.get("diagnoses") or []:
            if not isinstance(diag, dict):
                continue
            suggestion = diag.get("suggestion")
            images = suggestion.get("images") if isinstance(suggestion, dict) else None
            count = len(images) if isinstance(images, list) else 0
            for result in diag.get("diagnosis_results") or []:
                if not isinstance(result, dict) or not result.get("code"):
                    continue
                code = str(result["code"])
                rows.append(
                    DiagnosisRow(
                        product_id=product_id,
                        title=titles.get(product_id, product_id),
                        part=part_of(code),
                        how_to_solve=_truncate(
                            str(result.get("how_to_solve") or ""), HOW_TO_SOLVE_MAX
                        ),
                        suggested_images=count,
                        code=code,
                    )
                )
    return rows


def _load_orders(snapshot: Path) -> list[dict] | None:
    raw = load_json(snapshot / "orders.json")
    orders = raw.get("orders") if isinstance(raw, dict) else raw
    return [o for o in orders if isinstance(o, dict)] if isinstance(orders, list) else None


def _load_ratings(snapshot: Path) -> dict[str, Decimal] | None:
    raw = load_json(snapshot / "ratings.json")
    if not isinstance(raw, dict):
        return None
    out: dict[str, Decimal] = {}
    for product_id, entry in raw.items():
        value = entry.get("rating") if isinstance(entry, dict) else entry
        if not str(product_id).startswith("_") and value is not None:
            out[str(product_id)] = to_decimal(value)
    return out


def _load_review_counts(snapshot: Path) -> dict[str, int] | None:
    """Review counts from ``ratings.json``; ``None`` when the file is absent."""
    raw = load_json(snapshot / "ratings.json")
    if not isinstance(raw, dict):
        return None
    return {
        str(pid): int(to_decimal(entry["review_count"]))
        for pid, entry in raw.items()
        if isinstance(entry, dict)
        and entry.get("review_count") is not None
        and not str(pid).startswith("_")
    }


def _load_owner_tests(snapshot: Path) -> list[dict]:
    raw = load_json(snapshot / "owner_tests.json")
    tests = [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []
    for test in tests:
        if test.get("angle") not in OWNER_ANGLES or not test.get("product_id"):
            raise ValueError(f"owner test needs product_id and one of {OWNER_ANGLES}: {test}")
    return tests


def _load_promotions(
    snapshot: Path, window: tuple[date, date]
) -> tuple[PromotionIndex | None, dict[str, Any]]:
    """Promotion index (``None`` when not fetched) and the fetch status for the notes."""
    folder = snapshot / "promotions"
    error = load_json(folder / "_error.json")
    activities = load_json(folder / "activities.json")
    coupons = load_json(folder / "coupons.json")
    details = load_json(folder / "activity_details.json")
    status: dict[str, Any] = {"status": "skipped"}
    if isinstance(error, dict):
        status = {
            "status": "error",
            "detail": f"{error.get('error_class', '')}: {error.get('message', '')}",
        }
    if activities is None and coupons is None:
        return None, status
    index = promo.parse_promotions(
        activities, coupons, details if isinstance(details, dict) else {}, window
    )
    if status["status"] == "skipped":
        status = {"status": "ok"}
    status.update(
        {
            "activities": len(promo.unwrap_list(activities, "activities")),
            "coupons": len(promo.unwrap_list(coupons, "coupons")),
            "details": len(details) if isinstance(details, dict) else 0,
            "unattributed": index.unattributed,
        }
    )
    return index, status


def _load_appearances(snapshot: Path) -> tuple[dict[str, list[Appearance]], dict[str, Any]]:
    """LIVE / video appearances per product and the fetch status of each source."""
    status: dict[str, Any] = {}
    sessions: list[dict] = []
    videos: list[dict] = []
    session_products: dict[str, object] = {}
    video_products: dict[str, object] = {}
    for name, key, bucket, products in (
        ("live", "sessions", sessions, session_products),
        ("videos", "videos", videos, video_products),
    ):
        folder = snapshot / name
        error = load_json(folder / "_error.json")
        raw = load_json(folder / f"{key}.json")
        items = raw.get(key) if isinstance(raw, dict) else None
        state: dict[str, Any] = {"status": "skipped"}
        if isinstance(error, dict):
            state = {
                "status": "error",
                "detail": f"{error.get('error_class', '')}: {error.get('message', '')}",
            }
        if isinstance(items, list):
            bucket.extend(i for i in items if isinstance(i, dict))
            for item in bucket:
                payload = load_json(folder / "products" / f"{item.get('id')}.json")
                if payload is not None:
                    products[str(item.get("id"))] = payload
            if state["status"] == "skipped":
                state = {"status": "ok"}
            state["count"] = len(bucket)
        status[name] = state
    return parse_appearances(sessions, session_products, videos, video_products), status


def _kpi_value(funnel: ProductFunnel | None, config: StageDiagnosisConfig, *, aov: bool) -> str:
    """Current 14-day Main KPI, or "chưa đủ dữ liệu" below its ADR-077 floor (Amendment 3)."""
    if funnel is None:
        return NOT_ENOUGH_DATA
    floors = funnel.clears_floor(config)
    if aov:
        return fmt_value("money", funnel.current.aov) if floors["aov"] else NOT_ENOUGH_DATA
    return fmt_value("ratio", funnel.current.ctor) if floors["ctor"] else NOT_ENOUGH_DATA


def _firing_gap(gaps: dict[str, Gap], config: StageDiagnosisConfig) -> Gap:
    """The larger fired gap of CTR and CTOR — the one a pending card's reason names."""
    firing = [g for g in (gaps["ctr"], gaps["ctor"]) if g.fires(config)]
    return max(firing, key=lambda g: g.gap)


def _gap_sentence(gap: Gap, config: StageDiagnosisConfig) -> str:
    return gap_reason_sentence(
        gap, gap.trigger or Trigger.SHOP_MEDIAN, full_median_peers=config.full_median_peers
    )


def _owner_cards(
    tests: list[dict],
    *,
    funnels: dict[str, ProductFunnel],
    titles: dict[str, str],
    quantities: dict[str, list[int]],
    orders_present: bool,
    cur_items: dict[str, dict],
    config: StageDiagnosisConfig,
) -> list[ReportCard]:
    """One card per owner test, in file order, with a placeholder rank."""
    out: list[ReportCard] = []
    for test in tests:
        product_id, angle = str(test["product_id"]), str(test["angle"])
        funnel = funnels.get(product_id)
        basket = angle in BASKET_ANGLES
        note = str(test.get("note") or "").strip()
        if not note:
            aov = Counts.from_item(cur_items.get(product_id)).metrics()["aov"]
            note = (
                "Chưa đủ đơn trong 30 ngày để tính AOV"
                if aov is None
                else f"AOV 30 ngày qua là {fmt_value('money', aov)}"
            )
            share = share_with_at_least(quantities.get(product_id), 2) if orders_present else None
            if share is not None:
                note += f"; {_vn(share * 100, 0)} % số đơn có từ 2 món"
        threshold = basket_threshold(
            quantities.get(product_id), funnel.current.items_per_order if funnel else None, config
        ).threshold_items
        if angle == Angle.MUA_NHIEU_GIAM_NHIEU.value:
            change = f"Mua nhiều giảm nhiều, từ {threshold} món"
        elif angle == ANGLE_GIFT:
            gift_id = str(test.get("gift_product_id") or "")
            gift = _truncate(titles.get(gift_id, gift_id), 80)
            change = (
                f"Tặng kèm {gift} cho khách mua từ {threshold} món"
                if gift_id
                else f"Tặng quà kèm cho khách mua từ {threshold} món"
            )
        else:
            change = ANGLE_ACTION[Angle(angle)]
        out.append(
            ReportCard(
                rank=0,
                product_id=product_id,
                title=titles.get(product_id, product_id),
                main_kpi="AOV" if basket else "CTOR",
                main_kpi_value=_kpi_value(funnel, config, aov=basket),
                reason=note,
                change=change,
                status=STATUS_OWNER,
                rank_score=ZERO,
            )
        )
    return out


REASON_MAX = 170
KPI_NAMES = ("CTR", "CTOR", "AOV", "GMV")


@dataclass(frozen=True)
class TrafficContext:
    """What the traffic-source check and the reason clauses read, per product."""

    attribution: dict[str, TrafficAttribution]
    discounts: dict[str, DiscountPair]
    promotions: PromotionIndex | None


def _with_clauses(
    reason: str,
    product_id: str,
    ctx: TrafficContext,
    config: StageDiagnosisConfig,
    *,
    card_branch: bool,
    lead: str | None = None,
) -> str:
    """Append the short source clauses that fit: the lever's own, traffic source, platform
    discount, promotion."""
    clauses: list[str | None] = [lead]
    attribution = ctx.attribution.get(product_id)
    if card_branch and attribution is not None:
        clauses.append(source_clause(attribution))
    pair = ctx.discounts.get(product_id)
    share = pair.current.platform_share if pair else None
    if share is not None and share >= config.platform_discount_note_share:
        clauses.append(f"{_vn(share * 100, 0)} % đơn có giảm giá của sàn")
    if ctx.promotions is not None:
        clauses.append(promo.clause(ctx.promotions.for_product(product_id)))
    for clause in clauses:
        if clause and len(reason) + 2 + len(clause) <= REASON_MAX:
            reason = f"{reason}; {clause}"
    return reason


FLASH_FAILURE_TEXT = {
    "promotion_data_missing": "chưa lấy được dữ liệu khuyến mãi",
    "flash_sale_in_last_14_days": "đã có flash sale trong 14 ngày qua",
    "max_discount_not_set": "shop chưa đặt mức giảm giá tối đa",
    "duration_out_of_range": "thời lượng nằm ngoài 1 đến 3 ngày",
    "no_orders_in_window": NO_ORDERS_IN_WINDOW,
    "list_price_unknown": "không đọc được giá niêm yết",
    "discount_over_maximum": "mức giảm cần có vượt mức giảm giá tối đa của shop",
}


def _flash_failure_text(flash: FlashEval | None) -> str:
    if flash is None or not flash.failed:
        return "chưa đủ điều kiện"
    return "; ".join(FLASH_FAILURE_TEXT.get(code, code) for code in flash.failed)


def _flash_change(flash: FlashEval) -> str:
    price = _vn(flash.proposed_price or ZERO, 0)
    return (
        f"Flash sale {flash.days} ngày, giá {price} ₫ (thấp hơn mức giá thấp nhất khách đã trả "
        "trong 14 ngày qua); bạn cần xác nhận shop đủ điều kiện tham gia flash sale trước khi chạy"
    )


@dataclass(frozen=True)
class LeverFacts:
    """Per-product facts behind the shipping, gift and flash-sale levers."""

    levers: dict[str, PageLevers]
    shipping: dict[str, ShippingEval]
    flash: dict[str, FlashEval]
    stocks: dict[str, ProductStock]


def _lever_facts(
    snapshot: Path,
    config: StageDiagnosisConfig,
    *,
    as_of: date,
    live_ids: list[str],
    orders_30: list[dict],
    orders_14: list[dict],
    promotions: PromotionIndex | None,
    max_discount_percent: Decimal | None,
) -> LeverFacts:
    by_30 = orders_by_product(orders_30)
    by_14 = orders_by_product(orders_14)
    levers: dict[str, PageLevers] = {}
    shipping: dict[str, ShippingEval] = {}
    flash: dict[str, FlashEval] = {}
    stocks: dict[str, ProductStock] = {}
    for pid in live_ids:
        stock = product_stock(pid, _detail(snapshot, pid))
        if stock is not None:
            stocks[pid] = stock
        shipping[pid] = shipping_eval(by_30.get(pid, []), config)
        flash[pid] = flash_eval(
            product_id=pid,
            orders_low_window=by_14.get(pid, []),
            stock=stock,
            promotions=promotions,
            as_of=as_of,
            max_discount_percent=max_discount_percent,
            config=config,
        )
        levers[pid] = PageLevers(
            shipping_ok=shipping[pid].ok,
            flash_ok=flash[pid].ok,
            product_discount_active=product_discount_active(promotions, pid),
        )
    return LeverFacts(levers, shipping, flash, stocks)


def _gift_detail(search: GiftSearch) -> dict[str, Any]:
    choice = search.choice
    return {
        "gift_product_id": choice.product_id if choice else None,
        "gift_price": choice.price if choice else None,
        "gift_stock": choice.stock if choice else None,
        "gift_review_count": choice.review_count if choice else None,
        "max_price": search.max_price,
        "candidates_evaluated": search.evaluated,
        "rejected": search.rejected,
    }


def _short(title: str, limit: int = 50) -> str:
    return _truncate(title, limit)


def _seller_center_cards(
    config: StageDiagnosisConfig,
    *,
    titles: dict[str, str],
    live_ids: list[str],
    cur: dict[str, Counts],
    shop_cur: Counts,
    shop_prev: Counts,
    orders_30: list[dict],
    review_counts: dict[str, int] | None,
    taken: set[str],
    blocked_by_rating: Callable[[str, str], bool],
) -> tuple[list[ReportCard], dict[str, Any]]:
    """Seller Center cards, in the order review voucher, bundle deal, minimum-spend voucher.

    Each kind is emitted only with data behind it; a product that already holds a
    card is passed over (``taken`` is updated with the products these cards use).
    """
    cards: list[ReportCard] = []
    dropped: list[str] = []
    tech: dict[str, Any] = {}

    # 1. Voucher đánh giá.
    review_emitted = 0
    if review_counts is None:
        tech["review_voucher"] = {"status": "skipped", "detail": "không có ratings.json"}
    else:
        for pid in sorted(live_ids, key=lambda i: (cur[i].orders, i), reverse=True):
            reviews = review_counts.get(pid)
            per_day = cur[pid].orders / Decimal(WINDOW_DAYS)
            if (
                reviews is None
                or reviews >= config.review_voucher_max_reviews
                or per_day < config.review_voucher_min_orders_per_day
            ):
                continue
            if pid in taken:
                dropped.append(pid)
                continue
            reason = (
                f"Bán trung bình {_vn(per_day, 1)} đơn mỗi ngày trong 30 ngày qua nhưng mới có "
                f"{reviews} đánh giá"
            )
            taken.add(pid)
            if blocked_by_rating(pid, reason):
                continue
            review_emitted += 1
            cards.append(
                ReportCard(
                    rank=0,
                    product_id=pid,
                    title=titles.get(pid, pid),
                    main_kpi="Đánh giá",
                    main_kpi_value=str(reviews),
                    reason=reason,
                    change="Tạo voucher đánh giá trên Seller Center cho sản phẩm này",
                    status=STATUS_SC,
                    rank_score=per_day,
                    kind=KIND_REVIEW,
                )
            )
        tech["review_voucher"] = {"status": "ok", "emitted": review_emitted}

    # 2. Ưu Đãi Theo Gói.
    pairs = bundle_pairs(orders_30, set(live_ids), config)
    bundle_emitted = 0
    for pair in pairs:
        if pair.first in taken or pair.second in taken:
            dropped.extend(i for i in (pair.first, pair.second) if i in taken)
            continue
        main_id, other_id = (
            (pair.first, pair.second)
            if pair.orders_first >= pair.orders_second
            else (pair.second, pair.first)
        )
        name_main, name_other = (
            _short(titles.get(main_id, main_id)),
            _short(titles.get(other_id, other_id)),
        )
        main_orders = max(pair.orders_first, pair.orders_second)
        reason = (
            f"{pair.together} đơn trong 30 ngày qua mua cả hai sản phẩm cùng lúc, bằng "
            f"{_vn(Decimal(pair.together) / Decimal(main_orders) * 100, 0)} % số đơn của "
            f"{name_main}"
        )
        if blocked_by_rating(main_id, reason) or blocked_by_rating(other_id, reason):
            taken.update((main_id, other_id))
            continue
        taken.update((main_id, other_id))
        bundle_emitted += 1
        aov = cur[main_id].metrics()["aov"]
        cards.append(
            ReportCard(
                rank=0,
                product_id=main_id,
                title=f"{name_main} + {name_other}",
                main_kpi="AOV",
                main_kpi_value=fmt_value("money", aov) if aov is not None else NOT_ENOUGH_DATA,
                reason=reason,
                change=f"Tạo ưu đãi theo gói {name_main} + {name_other} trên Seller Center",
                status=STATUS_SC,
                rank_score=Decimal(pair.together),
                kind=KIND_BUNDLE,
            )
        )
    tech["bundle"] = {
        "orders": len(orders_30),
        "pairs_found": len(pairs),
        "emitted": bundle_emitted,
        "status": "ok" if orders_30 else NO_ORDERS_IN_WINDOW,
    }

    # 3. Voucher có mức chi tiêu tối thiểu (shop-level).
    shop_aov_cur, shop_aov_prev = shop_cur.metrics()["aov"], shop_prev.metrics()["aov"]
    spend = min_spend_eval(orders_30, shop_aov_cur, shop_aov_prev, config)
    tech["min_spend"] = {
        "verdict": spend.verdict,
        "orders": spend.orders,
        "multi_orders": spend.multi_orders,
        "multi_share": spend.multi_share,
        "aov_current": spend.aov_current,
        "aov_previous": spend.aov_previous,
        "aov_drop": spend.aov_drop,
        "level": spend.level,
    }
    if (
        spend.ok
        and spend.level is not None
        and spend.multi_share is not None
        and spend.aov_drop is not None
        and shop_aov_cur is not None
        and shop_aov_prev is not None
    ):
        cards.append(
            ReportCard(
                rank=0,
                product_id="",
                title=SHOP_WIDE,
                main_kpi="AOV",
                main_kpi_value=fmt_value("money", shop_aov_cur),
                reason=(
                    f"AOV của shop giảm {_vn(spend.aov_drop * 100, 0)} % so với 30 ngày trước "
                    f"({fmt_value('money', shop_aov_cur)} so với "
                    f"{fmt_value('money', shop_aov_prev)}); "
                    f"{_vn(spend.multi_share * 100, 0)} % số đơn trong 30 ngày qua có từ 2 sản "
                    "phẩm khác nhau"
                ),
                change=f"Tạo voucher giảm khi đơn từ {_vn(spend.level, 0)} ₫",
                status=STATUS_SC,
                rank_score=shop_cur.gmv,
                kind=KIND_MIN_SPEND,
            )
        )
    tech["dropped_product_has_card"] = sorted(set(dropped))
    return cards, tech


def _cards(
    snapshot: Path,
    config: StageDiagnosisConfig,
    *,
    titles: dict[str, str],
    cur_items: dict[str, dict],
    ctx: TrafficContext,
    as_of: date,
    live_ids: list[str],
    cur: dict[str, Counts],
    shop_cur: Counts,
    shop_prev: Counts,
) -> tuple[list[ReportCard], list[WatchRow], dict[str, Any]]:
    """Cards in the owner's order, plus the products the report only watches.

    Order: rule cards (Juli tự đề xuất), then cards that wait for a discount cap
    (each group ranked by gap × GMV_28d), then owner tests in file order, then
    Seller Center cards, then "Chưa hỏi TikTok" cards fill what is left of
    ``max_open_cards_per_shop``. A product holds one card; a rule card wins over an
    owner test, and both win over a Seller Center card, on the same product.
    """
    funnels, _signals, evidence_by_id, excluded = build_inputs(snapshot, config)
    windows = report_windows(as_of, config)
    first_cur, last_cur = (date.fromisoformat(d) for d in windows["current_30d"])
    first_prev = date.fromisoformat(windows["previous_30d"][0])
    all_orders = _load_orders(snapshot)
    order_window = summarize(all_orders, first_prev, last_cur)
    # Every order-derived figure below reads only orders created in its own window.
    orders_30 = orders_between(all_orders, first_cur, last_cur)
    orders_14 = orders_between(
        all_orders, as_of - timedelta(days=config.flash_low_price_days - 1), last_cur
    )
    quantities = quantities_by_product(orders_30)
    meta = load_json(snapshot / "meta.json") or {}
    cap_set = meta.get("max_discount_percent") is not None
    max_discount_percent = to_decimal(meta["max_discount_percent"]) if cap_set else None
    facts = _lever_facts(
        snapshot,
        config,
        as_of=as_of,
        live_ids=live_ids,
        orders_30=orders_30,
        orders_14=orders_14,
        promotions=ctx.promotions,
        max_discount_percent=max_discount_percent,
    )
    review_counts = _load_review_counts(snapshot)
    asked = asked_products(snapshot)
    medians, diagnoses, skips = diagnose_all(
        funnels,
        evidence_by_id,
        excluded,
        config,
        asked=asked,
        quantities=quantities,
        discount_cap_set=cap_set,
        levers=facts.levers,
    )
    by_id = {d.product_id: d for d in diagnoses}
    funnel_by_id = {f.product_id: f for f in funnels}
    ratings = _load_ratings(snapshot)
    low = {
        pid: rating
        for pid, rating in (ratings or {}).items()
        if rating < config.min_rating_for_demand_levers
    }
    watch: list[WatchRow] = []

    def blocked_by_rating(product_id: str, detail: str) -> bool:
        if product_id not in low:
            return False
        reason = f"Điểm đánh giá {_vn(low[product_id], 1)} sao, cần cải thiện sản phẩm trước"
        if any(w.product_id == product_id and w.reason == reason for w in watch):
            return True
        watch.append(WatchRow(product_id, titles.get(product_id, product_id), reason, detail))
        return True

    diluted: list[str] = []

    def blocked_by_dilution(product_id: str, detail: str) -> bool:
        """A CTR-triggered card is withheld when the CTR fall is dilution (amendment 4)."""
        attribution = ctx.attribution.get(product_id)
        if attribution is None or attribution.verdict != DILUTION:
            return False
        watch.append(
            WatchRow(
                product_id, titles.get(product_id, product_id), dilution_reason(attribution), detail
            )
        )
        diluted.append(product_id)
        return True

    rule_cards: list[ReportCard] = []
    bmsm_details: dict[str, dict[str, Any]] = {}
    flash_details: dict[str, dict[str, Any]] = {}
    gift_details: dict[str, dict[str, Any]] = {}
    for scored in build_cards(diagnoses, config):
        diag = by_id[scored.product_id]
        if blocked_by_rating(scored.product_id, scored.reason):
            continue
        card_branch = diag.branch is Branch.CARD
        if card_branch and blocked_by_dilution(scored.product_id, scored.reason):
            continue
        if diag.angle is Angle.MUA_NHIEU_GIAM_NHIEU and diag.bmsm:
            text = f"Mua nhiều giảm nhiều, từ {diag.bmsm.threshold_items} món"
            bmsm_details[scored.product_id] = {
                "threshold_items": diag.bmsm.threshold_items,
                "source": diag.bmsm.source,
                "orders": diag.bmsm.orders,
                "share_at_threshold": diag.bmsm.share,
            }
        elif diag.angle is Angle.FLASH_SALE:
            flash = facts.flash[scored.product_id]
            text = _flash_change(flash)
            flash_details[scored.product_id] = {
                "days": flash.days,
                "low_price_14d": flash.low_price,
                "proposed_price": flash.proposed_price,
                "implied_discount": flash.discount,
                "note": FLASH_CONFIRM,
            }
        elif diag.angle is Angle.GIAM_PHI_VAN_CHUYEN:
            text = "Giảm phí vận chuyển 30 ngày, trong mức giảm tối đa của shop"
        else:
            text = ANGLE_ACTION[diag.angle]
        lead = None
        if diag.angle is Angle.GIAM_PHI_VAN_CHUYEN:
            ship = facts.shipping[scored.product_id]
            lead = f"{_vn((ship.share or ZERO) * 100, 0)} % đơn khách tự trả phí vận chuyển"
        rule_cards.append(
            ReportCard(
                rank=0,
                product_id=scored.product_id,
                title=scored.title,
                main_kpi=scored.main_kpi,
                main_kpi_value=main_kpi_value(diag),
                reason=_with_clauses(
                    scored.reason,
                    scored.product_id,
                    ctx,
                    config,
                    card_branch=card_branch,
                    lead=lead,
                ),
                change=text,
                status=STATUS_RULE,
                rank_score=diag.rank_score,
            )
        )

    needs_cap: list[ReportCard] = []
    not_asked: list[ReportCard] = []
    for skip in skips:
        if skip.reason == "bmsm_threshold_unreached":
            aov_gap = skip.gaps["aov"]
            sentence = _gap_sentence(aov_gap, config)
            if blocked_by_rating(skip.product_id, sentence):
                continue
            # AOV fallback (amendment 5): a gift with purchase instead of the tier.
            search = find_gift(
                facts.stocks.get(skip.product_id),
                cur[skip.product_id].metrics()["aov"] if skip.product_id in cur else None,
                [s for pid, s in facts.stocks.items() if pid != skip.product_id],
                review_counts,
                config,
            )
            gift_details[skip.product_id] = _gift_detail(search)
            if search.choice is None:
                watch.append(
                    WatchRow(
                        skip.product_id, skip.title, WATCH_NO_GIFT, f"{sentence}; {WATCH_BASKET}"
                    )
                )
                continue
            gift_name = _truncate(search.choice.title, 80)
            rule_cards.append(
                ReportCard(
                    rank=0,
                    product_id=skip.product_id,
                    title=skip.title,
                    main_kpi="AOV",
                    main_kpi_value=(
                        fmt_value("money", aov_gap.value)
                        if aov_gap.cleared_floor
                        else NOT_ENOUGH_DATA
                    ),
                    reason=_with_clauses(sentence, skip.product_id, ctx, config, card_branch=False),
                    change=(f"Tặng kèm {gift_name} cho khách mua từ {config.gift_min_items} món"),
                    status=STATUS_RULE,
                    rank_score=aov_gap.gap * funnel_by_id[skip.product_id].gmv_28d,
                    kind=KIND_GIFT,
                )
            )
            continue
        if skip.reason == "product_discount_running":
            sentence = _gap_sentence(_firing_gap(skip.gaps, config), config)
            if not blocked_by_rating(skip.product_id, sentence):
                note = f"{sentence}; flash sale chưa chạy được: " + _flash_failure_text(
                    facts.flash.get(skip.product_id)
                )
                watch.append(WatchRow(skip.product_id, skip.title, WATCH_DISCOUNT_RUNNING, note))
            continue
        if skip.reason not in ("tiktok_not_asked", "discount_cap_needed", "tiktok_found_no_fault"):
            continue
        # These skips arise only under the CTOR label, whose gaps are CTR and CTOR.
        gap = _firing_gap(skip.gaps, config)
        sentence = _gap_sentence(gap, config)
        if blocked_by_rating(skip.product_id, sentence):
            continue
        if skip.reason == "tiktok_found_no_fault":
            watch.append(WatchRow(skip.product_id, skip.title, WATCH_NO_FAULT, sentence))
            continue
        score = gap.gap * funnel_by_id[skip.product_id].gmv_28d
        ctr, ctor = skip.gaps["ctr"], skip.gaps["ctor"]
        branch = Branch.CARD if ctr.fires(config) and ctr.gap >= ctor.gap else Branch.PAGE
        if branch is Branch.CARD and blocked_by_dilution(skip.product_id, sentence):
            continue
        needs = skip.reason == "discount_cap_needed"
        card = ReportCard(
            rank=0,
            product_id=skip.product_id,
            title=skip.title,
            main_kpi="CTOR",
            main_kpi_value=_kpi_value(funnel_by_id[skip.product_id], config, aov=False),
            reason=_with_clauses(
                sentence, skip.product_id, ctx, config, card_branch=branch is Branch.CARD
            ),
            change=(
                "Giảm giá sản phẩm, sau khi shop đặt mức giảm giá tối đa"
                if needs
                else f"{ANGLE_ACTION[BRANCH_ORDER[branch][0]]}, nếu TikTok chỉ ra lỗi"
            ),
            status=STATUS_NEEDS_CAP if needs else STATUS_NOT_ASKED,
            rank_score=score,
        )
        (needs_cap if needs else not_asked).append(card)
    rule_cards.sort(key=lambda c: c.rank_score, reverse=True)
    needs_cap.sort(key=lambda c: c.rank_score, reverse=True)
    not_asked.sort(key=lambda c: c.rank_score, reverse=True)

    owner_tests = _load_owner_tests(snapshot)
    titles = dict(titles)
    for test in owner_tests:
        for key in ("product_id", "gift_product_id"):
            pid = str(test.get(key) or "")
            detail = _detail(snapshot, pid) if pid and pid not in titles else None
            if detail and detail.get("title"):
                titles[pid] = str(detail["title"])
    taken = {c.product_id for c in (*rule_cards, *needs_cap)}
    dropped: list[str] = []
    owner_cards: list[ReportCard] = []
    for card in _owner_cards(
        owner_tests,
        funnels=funnel_by_id,
        titles=titles,
        quantities=quantities,
        orders_present=bool(orders_30),
        cur_items=cur_items,
        config=config,
    ):
        if card.product_id in taken:
            dropped.append(card.product_id)
        elif blocked_by_rating(card.product_id, card.reason):
            taken.add(card.product_id)
        else:
            taken.add(card.product_id)
            owner_cards.append(card)
    sc_cards, sc_tech = _seller_center_cards(
        config,
        titles=titles,
        live_ids=live_ids,
        cur=cur,
        shop_cur=shop_cur,
        shop_prev=shop_prev,
        orders_30=orders_30,
        review_counts=review_counts,
        taken=taken,
        blocked_by_rating=blocked_by_rating,
    )
    fill = [c for c in not_asked if c.product_id not in taken]

    ordered = [*rule_cards, *needs_cap, *owner_cards, *sc_cards, *fill]
    limit = config.max_open_cards_per_shop
    cards = [replace(c, rank=i) for i, c in enumerate(ordered[:limit], start=1)]
    for card in ordered[limit:]:
        watch.append(
            WatchRow(
                card.product_id,
                card.title,
                f"Đủ điều kiện nhưng đã đủ {limit} card",
                card.reason,
            )
        )
    tech = {
        "medians": {
            "ctr": medians.ctr,
            "ctor": medians.ctor,
            "aov": medians.aov,
            "peers": medians.peers,
        },
        "card_products": len(funnels),
        "card_excluded": len(excluded),
        "rule_cards_found": len(rule_cards),
        "needs_cap_found": len(needs_cap),
        "not_asked_found": len(not_asked),
        "traffic_diluted": diluted,
        "owner_tests": len(owner_tests),
        "owner_tests_dropped_rule_card_wins": dropped,
        "skip_reasons": dict(Counter(s.reason.split(":")[0] for s in skips)),
        "orders_present": bool(orders_30),
        "orders_counted": sum(1 for o in orders_30 if str(o.get("status") or "") != CANCELLED),
        "order_window": {
            "file_present": order_window.present,
            "in_file": order_window.total,
            "used": order_window.used,
            "excluded_out_of_window": order_window.excluded,
            "used_first": order_window.used_first.isoformat() if order_window.used_first else None,
            "used_last": order_window.used_last.isoformat() if order_window.used_last else None,
            "excluded_first": (
                order_window.excluded_first.isoformat() if order_window.excluded_first else None
            ),
            "excluded_last": (
                order_window.excluded_last.isoformat() if order_window.excluded_last else None
            ),
            "fetch": meta.get("orders_fetch"),
            "current_30d_orders": len(orders_30),
            "last_14d_orders": len(orders_14),
        },
        "shipping_lever": {
            "min_paid_share": config.shipping_lever_min_paid_share,
            "min_orders": config.shipping_lever_min_orders,
            "evaluated": len(facts.shipping),
            "insufficient_orders": sum(
                1 for e in facts.shipping.values() if e.verdict == "insufficient_orders"
            ),
            "passed": {
                pid: {"orders": e.orders, "paid_share": e.share}
                for pid, e in facts.shipping.items()
                if e.ok
            },
        },
        "gift": {
            "min_stock": config.gift_min_stock,
            "max_price_share": config.gift_max_price_share,
            "max_price_vnd": config.gift_max_price_vnd,
            "min_items": config.gift_min_items,
            "products": gift_details,
        },
        "flash_sale": {
            "promotions_fetched": ctx.promotions is not None,
            "max_discount_percent": max_discount_percent,
            "undercut": config.flash_undercut,
            "recent_days": config.flash_recent_days,
            "low_price_days": config.flash_low_price_days,
            "default_days": config.flash_default_days,
            "chosen": flash_details,
            "blocked_by": dict(
                Counter(
                    code
                    for pid, e in facts.flash.items()
                    if facts.levers[pid].product_discount_active
                    for code in e.failed
                )
            ),
            "product_discount_running": sorted(
                pid for pid, lv in facts.levers.items() if lv.product_discount_active
            ),
        },
        "seller_center": {**sc_tech, "emitted": len(sc_cards)},
        "bmsm": bmsm_details,
        "discount_cap_set": cap_set,
        "ratings_applied": ratings is not None,
        "ratings_count": len(ratings or {}),
        "ratings_below_min": sorted(low),
        "min_rating_for_demand_levers": config.min_rating_for_demand_levers,
        "bmsm_min_orders_for_histogram": config.bmsm_min_orders_for_histogram,
        "bmsm_min_share_at_threshold": config.bmsm_min_share_at_threshold,
    }
    return cards, watch, tech


def _traffic_block(
    product_id: str,
    title: str,
    *,
    has_card: bool,
    attribution: TrafficAttribution,
    discounts: DiscountPair,
    promotions: list[PromotionItem],
    appearances: list[Appearance],
) -> TrafficBlock:
    return TrafficBlock(
        product_id=product_id,
        title=title,
        has_card=has_card,
        verdict=attribution.verdict,
        top_impression_source=attribution.top_impression_source,
        channels=[
            TrafficChannelRow(
                c.label,
                c.impressions_per_day_previous,
                c.impressions_per_day_current,
                c.ctr_previous,
                c.ctr_current,
                c.qualifies,
                c.spiking,
                c.ctr_dropped,
            )
            for c in attribution.channels
            if c.shown
        ],
        promotions=promotions,
        discounts=discounts,
        appearances=appearances,
    )


def build_shop_report(
    snapshot: Path,
    *,
    config: StageDiagnosisConfig | None = None,
    shop_name: str | None = None,
) -> ShopReport:
    """Read a snapshot directory and compute everything the report shows."""
    config = config or StageDiagnosisConfig()
    meta = load_json(snapshot / "meta.json") or {}
    as_of = date.fromisoformat(str(meta["as_of"]))
    name = shop_name or str(meta.get("shop_name") or "Shop")

    cur_items = a34_index(load_json(snapshot / "a34_30d_current.json"))
    prev_items = a34_index(load_json(snapshot / "a34_30d_previous.json"))

    # Universe: every product in either 30-day window, minus gift / not-for-sale
    # titles and non-ACTIVATE statuses. No product detail = status unknown = kept.
    titles: dict[str, str] = {}
    live: list[str] = []
    excluded_ids: set[str] = set()
    counts = {"gift": 0, "inactive": 0, "no_detail": 0}
    for product_id in [*cur_items, *(i for i in prev_items if i not in cur_items)]:
        detail = _detail(snapshot, product_id)
        if detail is None:
            counts["no_detail"] += 1
            titles[product_id] = product_id
            live.append(product_id)
            continue
        titles[product_id] = str(detail.get("title") or product_id)
        signals = listing_signals_from_product({**detail, "id": product_id}, config)
        if signals.excluded_reason:
            counts["gift"] += 1
            excluded_ids.add(product_id)
        elif signals.status not in (None, "ACTIVATE"):
            counts["inactive"] += 1
            excluded_ids.add(product_id)
        else:
            live.append(product_id)

    cur = {i: Counts.from_item(cur_items.get(i)) for i in live}
    prev = {i: Counts.from_item(prev_items.get(i)) for i in live}
    shop_cur = sum(cur.values(), Counts())
    shop_prev = sum(prev.values(), Counts())

    ranked = sorted(live, key=lambda i: (cur[i].gmv, i), reverse=True)
    top_ids = [i for i in ranked if cur[i].gmv > 0][:TOP_N]
    rest_ids = [i for i in live if i not in set(top_ids)]

    shop_rows = _rows(shop_cur.metrics(), shop_prev.metrics())

    def group(ids: list[str]) -> tuple[Counts, Counts]:
        return sum((cur[i] for i in ids), Counts()), sum((prev[i] for i in ids), Counts())

    top_cur, top_prev = group(top_ids)
    rest_cur, rest_prev = group(rest_ids)
    tm_cur, tm_prev = top_cur.metrics(), top_prev.metrics()
    rm_cur, rm_prev = rest_cur.metrics(), rest_prev.metrics()
    group_rows = [
        GroupRow(
            "gmv_share",
            "Tỷ trọng GMV của shop",
            "ratio",
            Delta.of(_ratio(top_cur.gmv, shop_cur.gmv), _ratio(top_prev.gmv, shop_prev.gmv)),
            Delta.of(_ratio(rest_cur.gmv, shop_cur.gmv), _ratio(rest_prev.gmv, shop_prev.gmv)),
        ),
        GroupRow(
            "gmv",
            "GMV 30 ngày",
            "money",
            Delta.of(tm_cur["gmv"], tm_prev["gmv"]),
            Delta.of(rm_cur["gmv"], rm_prev["gmv"]),
        ),
        *(
            GroupRow(
                key,
                label,
                kind,
                Delta.of(tm_cur[key], tm_prev[key]),
                Delta.of(rm_cur[key], rm_prev[key]),
            )
            for key, label, kind in METRICS
        ),
    ]

    windows = report_windows(as_of, config)
    orders = _load_orders(snapshot)
    first_cur, last_cur = (date.fromisoformat(d) for d in windows["current_30d"])
    first_prev, last_prev = (date.fromisoformat(d) for d in windows["previous_30d"])
    discounts = (
        discount_shares(
            orders, current=(first_cur, last_cur), previous=(first_prev, last_prev), config=config
        )
        if orders is not None
        else {}
    )
    blank_discounts = empty_pair(config)
    promotions, promotions_status = _load_promotions(snapshot, (first_cur, last_cur))
    appearances, live_video_status = _load_appearances(snapshot)
    attribution = {
        i: attribute_traffic(i, cur_items.get(i), prev_items.get(i), config) for i in live
    }
    ctx = TrafficContext(attribution, discounts, promotions)

    top_products: list[ProductBlock] = []
    for product_id in top_ids:
        c, p = cur[product_id].metrics(), prev[product_id].metrics()
        rows = _rows(c, p)
        rows.insert(1, MetricRow("gmv", "GMV 30 ngày", "money", Delta.of(c["gmv"], p["gmv"])))
        top_products.append(
            ProductBlock(
                product_id=product_id,
                title=titles[product_id],
                rows=rows,
                gmv_share=Delta.of(
                    _ratio(cur[product_id].gmv, shop_cur.gmv),
                    _ratio(prev[product_id].gmv, shop_prev.gmv),
                ),
                channels=channel_shares(cur_items.get(product_id) or {}),
                discounts=discounts.get(product_id, blank_discounts),
            )
        )

    rest_sorted = sorted(rest_ids, key=lambda i: (cur[i].impressions, i), reverse=True)
    rest_products = []
    for product_id in rest_sorted[:REST_ROWS]:
        m = cur[product_id].metrics()
        if cur[product_id].impressions <= 0:
            break
        rest_products.append(
            RestRow(
                product_id=product_id,
                title=titles[product_id],
                impressions=cur[product_id].impressions,
                clicks=cur[product_id].clicks,
                orders=cur[product_id].orders,
                ctr=m["ctr"],
                ctor=m["ctor"],
                aov=m["aov"],
            )
        )

    cards, watch, tech = _cards(
        snapshot,
        config,
        titles=titles,
        cur_items=cur_items,
        ctx=ctx,
        as_of=as_of,
        live_ids=live,
        cur=cur,
        shop_cur=shop_cur,
        shop_prev=shop_prev,
    )
    error = load_json(snapshot / "diagnoses" / "_error.json")
    traffic_ids = list(
        dict.fromkeys([*(c.product_id for c in cards if c.product_id), *tech["traffic_diluted"]])
    )
    traffic = [
        _traffic_block(
            product_id,
            titles.get(product_id, product_id),
            has_card=product_id not in tech["traffic_diluted"],
            attribution=attribution.get(product_id)
            or attribute_traffic(
                product_id, cur_items.get(product_id), prev_items.get(product_id), config
            ),
            discounts=discounts.get(product_id, blank_discounts),
            promotions=promotions.for_product(product_id) if promotions else [],
            appearances=appearances.get(product_id, []),
        )
        for product_id in traffic_ids
    ]
    verdict_ids = list(dict.fromkeys([*traffic_ids, *top_ids]))
    tech.update(
        {
            "traffic_verdicts": {
                i: attribution[i].verdict if i in attribution else UNCLEAR for i in verdict_ids
            },
            "traffic_top_sources": {
                i: attribution[i].top_impression_source if i in attribution else ""
                for i in verdict_ids
            },
            "traffic_min_channel_impressions": config.traffic_min_channel_impressions,
            "traffic_spike_ratio": config.traffic_spike_ratio,
            "traffic_ctr_drop": config.traffic_ctr_drop,
            "traffic_ctr_stable": config.traffic_ctr_stable,
            "platform_discount_note_share": config.platform_discount_note_share,
            "platform_discount_min_lines": config.platform_discount_min_lines,
            "discount_window_orders": sum(
                p.current.lines + p.previous.lines for p in discounts.values()
            ),
            "promotions_status": promotions_status,
            "live_status": live_video_status["live"],
            "videos_status": live_video_status["videos"],
            "universe": len(live) + len(excluded_ids),
            "live_products": len(live),
            "top_ids": top_ids,
            "rest_live_products": len(rest_ids),
            "exclude_title_patterns": list(config.exclude_title_patterns),
            "gap_threshold_median": config.gap_threshold_median,
            "gap_threshold_trend": config.gap_threshold_trend,
            "min_peers_for_median": config.min_peers_for_median,
            "max_open_cards_per_shop": config.max_open_cards_per_shop,
        }
    )
    diagnosis_rows = _diagnosis_rows(snapshot, titles, excluded_ids)
    diagnosis_rows.sort(
        key=lambda r: (-cur[r.product_id].gmv if r.product_id in cur else ZERO, r.code)
    )
    tech["diagnosis_codes"] = dict(Counter(r.code for r in diagnosis_rows))
    return ShopReport(
        shop_name=name,
        as_of=as_of.isoformat(),
        windows=windows,
        exclusions=counts,
        shop_rows=shop_rows,
        group_rows=group_rows,
        top_products=top_products,
        rest_products=rest_products,
        cards=cards,
        watch=watch,
        diagnoses=diagnosis_rows,
        diagnoses_error=(
            {str(k): str(v) for k, v in error.items()} if isinstance(error, dict) else None
        ),
        traffic=traffic,
        technical=tech,
    )


_STYLE = """:root{
  --bg:#f5f7f9; --surface:#ffffff; --fg:#17202a; --muted:#5d6b78; --line:#d8dfe6;
  --accent:#0b6e6e; --accent-soft:#dff1ef;
  --kpi:#8a4b00; --kpi-soft:#fff1dc;
  --ok:#1f6f3d; --ok-soft:#e1f3e7; --warn:#8a5a00; --warn-soft:#fff3d6;
  --off:#4a5a8a; --off-soft:#e8ecf7;
  --code-bg:#eef2f5;
  --display:"Manrope",system-ui,sans-serif; --body:"Be Vietnam Pro",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f1519; --surface:#161e24; --fg:#e8eef2; --muted:#9fb0bd; --line:#2a3640;
  --accent:#4fc1b7; --accent-soft:#143634; --kpi:#f0b35c; --kpi-soft:#3a2a12;
  --ok:#7fd49a; --ok-soft:#163a24; --warn:#f0c674; --warn-soft:#3a2f12;
  --off:#a9b8f0; --off-soft:#232b45;
  --code-bg:#1d272e; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f1519; --surface:#161e24; --fg:#e8eef2; --muted:#9fb0bd; --line:#2a3640;
  --accent:#4fc1b7; --accent-soft:#143634; --kpi:#f0b35c; --kpi-soft:#3a2a12;
  --ok:#7fd49a; --ok-soft:#163a24; --warn:#f0c674; --warn-soft:#3a2f12;
  --off:#a9b8f0; --off-soft:#232b45;
  --code-bg:#1d272e; color-scheme:dark}
body{
  background:var(--bg);
  color:var(--fg);
  font-family:var(--body);
  font-size:15px;
  line-height:1.6;
  padding-inline:16px;
  padding-block:32px 64px;
}
.wrap{max-width:960px;margin:0 auto;display:grid;gap:36px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0}
h1{font-size:clamp(28px,4vw,40px);font-weight:800;line-height:1.1}
h2{font-size:22px;font-weight:700}
h3{font-size:17px;font-weight:700}
p{margin:0;max-width:72ch}
.eyebrow{
  font-size:12px;
  letter-spacing:.08em;
  text-transform:uppercase;
  color:var(--muted);
  font-weight:600;
}
.lede{color:var(--muted);font-size:16px}
section{display:grid;gap:14px}
.tablewrap{
  overflow-x:auto;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
}
table{border-collapse:collapse;width:100%;font-size:14px;min-width:700px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{
  font-family:var(--display);
  font-size:12px;
  letter-spacing:.06em;
  text-transform:uppercase;
  color:var(--muted);
  white-space:nowrap;
}
tr:last-child td{border-bottom:0}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{
  display:inline-block;
  font-size:12px;
  font-weight:600;
  padding:2px 9px;
  border-radius:999px;
  white-space:nowrap;
}
.pill.kpi{background:var(--kpi-soft);color:var(--kpi)}
.pill.ok{background:var(--ok-soft);color:var(--ok)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.pill.off{background:var(--off-soft);color:var(--off)}
.pill.sc{background:var(--accent-soft);color:var(--accent)}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.legend div{
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
  padding:14px;
  display:grid;
  gap:8px;
  align-content:start;
  font-size:14px;
}
.legend p{color:var(--muted)}
.card{
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:18px;
  display:grid;
  gap:14px;
}
.card header{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:baseline}
.card .n{
  font-family:var(--display);
  font-weight:800;
  font-size:28px;
  color:var(--accent);
  line-height:1;
}
.card h3{flex:1 1 320px;min-width:0}
.fields{display:grid;grid-template-columns:150px 1fr;gap:10px 16px;font-size:14.5px;margin:0}
.fields dt{color:var(--muted);font-weight:600}
.fields dd{margin:0;min-width:0}
.goal{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.goal div{
  background:var(--bg);
  border:1px solid var(--line);
  border-radius:8px;
  padding:10px 12px;
  font-size:13px;
}
.goal div b{
  display:block;
  font-family:var(--display);
  font-size:18px;
  font-weight:800;
  color:var(--kpi);
  font-variant-numeric:tabular-nums;
}
.goal div span{color:var(--muted)}
.note{font-size:13.5px;color:var(--muted)}
.ref{font-size:12px;color:var(--muted)}
.tl{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.tl div{
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
  padding:12px 14px;
  font-size:13.5px;
  display:grid;
  gap:4px;
  align-content:start;
}
.tl .w{
  font-family:var(--display);
  font-weight:800;
  font-size:12px;
  color:var(--muted);
  letter-spacing:.05em;
}
ul.plain{margin:0;padding-left:18px;display:grid;gap:6px;font-size:14.5px}
.tech{
  background:var(--surface);
  border:1px dashed var(--line);
  border-radius:12px;
  padding:18px;
  display:grid;
  gap:16px;
}
.tech h3{font-size:15px}
.tech ol{margin:0;padding-left:20px;display:grid;gap:8px;font-size:13.5px}
code{
  font-family:var(--mono);
  font-size:12.5px;
  background:var(--code-bg);
  padding:1px 5px;
  border-radius:4px;
  overflow-wrap:anywhere;
}
footer{font-size:12.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
@media (max-width:560px){.fields{grid-template-columns:1fr;gap:4px}.fields dd{margin-bottom:8px}}
td.name{min-width:220px;max-width:340px}
td.rowlabel,th.rowlabel{position:sticky;left:0;background:var(--surface);min-width:150px}
.sub{display:block;font-size:12px;color:var(--muted);font-weight:400;white-space:nowrap}
.cellhead{
  display:block;
  font-weight:600;
  text-transform:none;
  letter-spacing:0;
  font-size:12.5px;
  white-space:normal;
  min-width:150px;
  color:var(--fg);
}
.kpiv{font-variant-numeric:tabular-nums;white-space:nowrap}
"""


# --------------------------------------------------------------------------- HTML

_FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800'
    '&family=Be+Vietnam+Pro:wght@400;500;600&display=swap">'
)

_LEGEND = {
    STATUS_RULE: (
        "ok",
        "Juli thấy một chỉ số của sản phẩm tụt rõ (từ 20 % trở lên) và có đủ dữ liệu để đo kết "
        "quả sau khi thay đổi. Card này đi ra tự động mỗi đêm, bạn chỉ cần duyệt.",
    ),
    STATUS_NEEDS_CAP: (
        "warn",
        "Số liệu cho thấy sản phẩm có vấn đề ở bước từ lúc khách bấm vào đến lúc đặt đơn, và "
        "trang sản phẩm không có lỗi nào để sửa. Juli chỉ đề xuất giảm giá khi shop đã cho biết "
        "mức giảm tối đa chấp nhận được.",
    ),
    STATUS_NOT_ASKED: (
        "warn",
        "Số liệu cho thấy sản phẩm có vấn đề, nhưng công cụ chẩn đoán của TikTok chưa được chạy "
        "cho sản phẩm này; lần chạy đầy đủ tiếp theo sẽ hỏi. Juli sẽ không sửa đoán, nên chỉ "
        "đề xuất sau khi TikTok chỉ ra lỗi cụ thể.",
    ),
    STATUS_OWNER: (
        "off",
        "Thử nghiệm do bạn tự đặt ra. Juli không tự đề xuất card này, chỉ ghi lại số liệu hiện "
        "tại để so sánh sau khi thử.",
    ),
    STATUS_SC: (
        "sc",
        "Juli không tạo được công cụ này qua API; bạn tạo trên Seller Center theo hướng dẫn "
        "trên card. Card chỉ xuất hiện khi số liệu của shop cho thấy công cụ này có lý do để dùng.",
    ),
}
_COUNT_WORD = {1: "Một", 2: "Hai", 3: "Ba", 4: "Bốn", 5: "Năm"}


def _e(text: object) -> str:
    return html.escape(str(text))


def _dmy(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _table(head: list[str], body: list[str]) -> str:
    cols = "".join(f"<th>{h}</th>" for h in head)
    rows = "".join(body)
    return (
        '<div class="tablewrap"><table>'
        f"<thead><tr>{cols}</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _cell(kind: str, delta: Delta) -> str:
    return (
        f'<td class="num"><b>{_e(fmt_value(kind, delta.current))}</b>'
        f'<span class="sub">trước {_e(fmt_value(kind, delta.previous))} '
        f"({_e(fmt_pct_change(delta))})</span></td>"
    )


def _share_cell(pair: DiscountPair, *, platform: bool) -> str:
    def part(window: WindowShare) -> tuple[Decimal | None, int]:
        return (window.platform_share if platform else window.seller_share), window.lines

    cur, cur_lines = part(pair.current)
    prev, prev_lines = part(pair.previous)
    head = "—" if cur is None else f"{_vn(cur * 100, 0)} %"
    sub = NO_ORDERS_IN_WINDOW if cur is None else f"{cur_lines} món"
    before = "—" if prev is None else f"{_vn(prev * 100, 0)} %"
    return (
        f'<td class="num"><b>{head}</b><span class="sub">trước {before} '
        f"({sub}; trước đó {prev_lines} món)</span></td>"
    )


def _section(eyebrow: str, title: str, *parts: str) -> str:
    return (
        f'<section><div class="eyebrow">{eyebrow}</div><h2>{title}</h2>{"".join(parts)}</section>'
    )


def _legend(cards: list[ReportCard]) -> str:
    seen = [s for s in _LEGEND if any(c.status == s for c in cards)] or list(_LEGEND)
    items = "".join(
        f'<div><span class="pill {_LEGEND[s][0]}">{_e(s)}</span><p>{_e(_LEGEND[s][1])}</p></div>'
        for s in seen
    )
    return _section(
        "Đọc trạng thái",
        f"{_COUNT_WORD[len(seen)]} loại card",
        f'<div class="legend">{items}</div>',
    )


def _card_table(report: ShopReport) -> str:
    if not report.cards:
        return _section(
            "Tổng quan",
            "Card đề xuất",
            "<p>Lần này chưa có sản phẩm nào đủ điều kiện để Juli đề xuất card.</p>",
        )
    body = []
    for c in report.cards:
        pill = _LEGEND[c.status][0]
        dotted = c.main_kpi_value == NOT_ENOUGH_DATA or c.main_kpi not in KPI_NAMES
        value = f"· {c.main_kpi_value}" if dotted else c.main_kpi_value
        body.append(
            f'<tr><td class="num">{c.rank}</td><td class="name">{_e(c.title)}</td>'
            f'<td class="kpiv"><span class="pill kpi">{_e(c.main_kpi)}</span> '
            f"{_e(value)}</td><td>{_e(c.reason)}</td><td>{_e(c.change)}</td>"
            f'<td><span class="pill {pill}">{_e(c.status)}</span></td></tr>'
        )
    head = ["#", "Sản phẩm", "Chỉ số chính", "Lý do", "Thay đổi đề xuất", "Trạng thái"]
    return _section(
        "Tổng quan",
        f"{len(report.cards)} card theo thứ tự",
        _table(head, body),
        '<p class="note">Card dùng số liệu 14 ngày gần nhất so với 4 tuần trước đó. Mỗi card chỉ '
        "thay đổi một thứ.</p>",
    )


VERDICT_TEXT = {
    UNIFORM: "CTR giảm ở mọi kênh: nguyên nhân chung như ảnh bìa, giá hoặc tiêu đề",
    DILUTION: (
        "CTR chỉ giảm ở kênh có lượt hiển thị tăng mạnh: traffic loãng, chưa nên sửa trang sản phẩm"
    ),
    UNCLEAR: "Chưa đủ dữ liệu để kết luận",
}
VERDICT_PILL = {UNIFORM: "ok", DILUTION: "warn", UNCLEAR: "off"}


def _dm(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m") if iso else ""


def _per_day(value: Decimal) -> str:
    return _vn(value, 0 if value >= 10 else 1)


def _traffic_product(block: TrafficBlock) -> str:
    rows = []
    for c in block.channels:
        marks = []
        if not c.qualifies:
            marks.append("ít lượt hiển thị, không dùng để kết luận")
        elif c.spiking:
            marks.append("lượt hiển thị tăng mạnh")
        if c.qualifies and c.ctr_dropped:
            marks.append("CTR giảm rõ")
        note = f'<span class="sub">{_e("; ".join(marks))}</span>' if marks else ""
        rows.append(
            f"<tr><td>{_e(c.label)}{note}</td>"
            f'<td class="num">{_per_day(c.impressions_per_day_previous)} → '
            f"<b>{_per_day(c.impressions_per_day_current)}</b></td>"
            f'<td class="num">{_e(fmt_value("ratio", c.ctr_previous))} → '
            f"<b>{_e(fmt_value('ratio', c.ctr_current))}</b></td></tr>"
        )
    head = ["Kênh", "Lượt hiển thị mỗi ngày (trước → nay)", "CTR (trước → nay)"]
    table = _table(head, rows) if rows else "<p>Chưa có lượt hiển thị theo kênh.</p>"
    top = (
        f"<p>Lượt hiển thị tăng nhiều nhất từ <b>{_e(block.top_impression_source)}</b>.</p>"
        if block.top_impression_source
        else ""
    )
    withheld = (
        ""
        if block.has_card
        else '<p class="note"><b>Không có card cho sản phẩm này</b>; sản phẩm nằm trong danh sách '
        "cần theo dõi.</p>"
    )
    promos = "".join(
        f"<li>{_e(p.kind)}: {_e(p.title)}, {_e(_dm(p.begin))}"
        + (f" – {_e(_dm(p.end))}" if p.end else " trở đi")
        + (f", {_e(p.summary)}" if p.summary else "")
        + "</li>"
        for p in block.promotions
    )
    appear = "".join(
        f"<li>{_e(a.kind)} {_e(_dm(a.day))}: {_e(_truncate(a.title, 90))}"
        + (
            f", {a.impressions} lượt hiển thị, {a.orders} đơn"
            if a.kind == "LIVE" and a.impressions is not None
            else (f", bán {a.orders} món" if a.orders is not None else "")
        )
        + "</li>"
        for a in block.appearances
    )
    pair = block.discounts
    if pair.current.lines == 0 and pair.previous.lines == 0:
        discount_note = "Chưa có đơn trong dữ liệu để tính tỷ lệ giảm giá"
    else:
        discount_note = (
            f"{_discount_text(pair.current.platform_share)} số món trong 30 ngày qua "
            "có giảm giá của sàn (trước đó "
            f"{_discount_text(pair.previous.platform_share)}); "
            f"{_discount_text(pair.current.seller_share)} có giảm giá của shop"
        )
    promo_html = f"<ul class=plain>{promos}</ul>" if promos else "Không thấy"
    appear_html = f"<ul class=plain>{appear}</ul>" if appear else "Không có"
    fields = (
        f"<dt>Khuyến mãi của shop</dt><dd>{promo_html}</dd>"
        f"<dt>Giảm giá trên đơn</dt><dd>{_e(discount_note)}</dd>"
        f"<dt>LIVE và video</dt><dd>{appear_html}</dd>"
    )
    return (
        '<div class="card"><header>'
        f"<h3>{_e(block.title)}</h3>"
        f'<span class="pill {VERDICT_PILL[block.verdict]}">{_e(VERDICT_TEXT[block.verdict])}</span>'
        f'</header>{top}{table}{withheld}<dl class="fields">{fields}</dl></div>'
    )


def _discount_text(share: Decimal | None) -> str:
    return "chưa đủ đơn để tính" if share is None else f"{_vn(share * 100, 0)} %"


def _traffic_section(report: ShopReport) -> str:
    if not report.traffic:
        return ""
    t = report.technical
    missing = [
        text
        for text, key in (
            ("khuyến mãi của shop", "promotions_status"),
            ("LIVE", "live_status"),
            ("video", "videos_status"),
        )
        if t.get(key, {}).get("status") != "ok"
    ]
    notes = (
        f'<p class="note">Lần này chưa lấy được {_e(", ".join(missing))}; chi tiết ở phần cuối '
        "trang.</p>"
        if missing
        else ""
    )
    return _section(
        "Traffic",
        "Traffic đến từ đâu",
        '<p class="note">Với mỗi sản phẩm có card, Juli so lượt hiển thị và CTR của từng kênh '
        "trong 30 ngày qua với 30 ngày trước đó. Nếu CTR giảm ở hầu hết các kênh thì nguyên "
        "nhân nằm ở chính sản phẩm; nếu chỉ giảm ở kênh vừa đổ nhiều lượt hiển thị vào thì "
        "đó là traffic loãng và không nên sửa trang sản phẩm.</p>",
        *(_traffic_product(b) for b in report.traffic),
        notes,
    )


def _watch_table(report: ShopReport) -> str:
    if not report.watch:
        return ""
    body = [
        f'<tr><td class="name">{_e(w.title)}</td><td>{_e(w.reason)}</td>'
        f"<td>{_e(w.detail)}</td></tr>"
        for w in report.watch
    ]
    return _section(
        "Theo dõi",
        "Sản phẩm cần theo dõi",
        _table(["Sản phẩm", "Lý do chưa có card", "Số liệu"], body),
        '<p class="note">Những sản phẩm này có tín hiệu đáng chú ý nhưng Juli không đề xuất thay '
        "đổi lúc này.</p>",
    )


def _shop_table(report: ShopReport) -> str:
    body = [
        f'<tr><td class="rowlabel">{_e(r.label)}</td>'
        f'<td class="num">{_e(fmt_value(r.kind, r.delta.current))}</td>'
        f'<td class="num">{_e(fmt_value(r.kind, r.delta.previous))}</td>'
        f'<td class="num">{_e(fmt_abs_change(r.kind, r.delta))}</td>'
        f'<td class="num">{_e(fmt_pct_change(r.delta))}</td></tr>'
        for r in report.shop_rows
    ]
    head = ["Chỉ số", "30 ngày qua", "30 ngày trước đó", "Thay đổi", "Thay đổi (%)"]
    return _section(
        "Toàn shop",
        "Chỉ số trung bình của shop",
        _table(head, body),
        '<p class="note">Cộng gộp mọi sản phẩm đang bán của shop. Kênh thẻ sản phẩm là khách đến '
        "từ tìm kiếm, gợi ý và Shop Tab, không tính video và LIVE.</p>",
    )


def _group_table(report: ShopReport) -> str:
    body = []
    for r in report.group_rows:
        body.append(
            f'<tr><td class="rowlabel">{_e(r.label)}</td>'
            f"{_cell(r.kind, r.top)}{_cell(r.kind, r.rest)}</tr>"
        )
    head = ["Chỉ số", "Top 5 theo GMV", "Còn lại"]
    return _section(
        "So sánh nhóm",
        "Top 5 và phần còn lại",
        _table(head, body),
        '<p class="note">Top 5 là năm sản phẩm có GMV cao nhất trong 30 ngày qua; "còn lại" là '
        "mọi sản phẩm đang bán khác. Mỗi ô ghi số 30 ngày qua và so với 30 ngày trước đó.</p>",
    )


def _top_table(report: ShopReport) -> str:
    if not report.top_products:
        return _section(
            "Chủ lực",
            "Từng sản phẩm trong top 5",
            "<p>Chưa có sản phẩm nào phát sinh doanh thu trong 30 ngày qua.</p>",
        )
    head = ['<span class="cellhead">Chỉ số</span>'] + [
        f'<span class="cellhead">{i}. {_e(p.title)}</span>'
        for i, p in enumerate(report.top_products, start=1)
    ]
    first = report.top_products[0]
    body = []
    for index, row in enumerate(first.rows):
        cells = "".join(_cell(p.rows[index].kind, p.rows[index].delta) for p in report.top_products)
        body.append(f'<tr><td class="rowlabel">{_e(row.label)}</td>{cells}</tr>')
        if row.key == "gmv":
            share = "".join(_cell("ratio", p.gmv_share) for p in report.top_products)
            body.append(f'<tr><td class="rowlabel">Tỷ trọng GMV của shop</td>{share}</tr>')
    channels = []
    for p in report.top_products:
        parts = [
            f"{_e(label)} {'&lt; 1' if share < 1 else _e(_vn(share, 0))} %"
            for label, share in p.channels
        ]
        channels.append(f"<td>{'<br>'.join(parts) or '—'}</td>")
    body.append(
        f'<tr><td class="rowlabel">Tỷ trọng kênh (30 ngày qua)</td>{"".join(channels)}</tr>'
    )
    for label, platform in (("Đơn có giảm giá của sàn", True), ("Đơn có giảm giá của shop", False)):
        cells = "".join(_share_cell(p.discounts, platform=platform) for p in report.top_products)
        body.append(f'<tr><td class="rowlabel">{label}</td>{cells}</tr>')
    return _section(
        "Chủ lực",
        "Từng sản phẩm trong top 5",
        _table(head, body),
        '<p class="note">Mỗi ô ghi số 30 ngày qua và so với 30 ngày trước đó. Tỷ trọng kênh cho '
        "biết đơn của sản phẩm đến từ đâu; năm kênh cộng lại là 100 %. Tỷ lệ đơn có giảm giá "
        "tính trên số món bán ra; ô để trống khi cửa sổ đó chưa có đủ đơn trong dữ liệu.</p>",
    )


def _rest_table(report: ShopReport) -> str:
    if not report.rest_products:
        return _section(
            "Phần còn lại",
            "Các sản phẩm còn lại có traffic",
            "<p>Không có sản phẩm nào ngoài top 5 có lượt hiển thị trong 30 ngày qua.</p>",
        )
    body = [
        f'<tr><td class="name">{_e(r.title)}</td>'
        f'<td class="num">{_e(fmt_value("int", r.impressions))}</td>'
        f'<td class="num">{_e(fmt_value("int", r.clicks))}</td>'
        f'<td class="num">{_e(fmt_value("int", r.orders))}</td>'
        f'<td class="num">{_e(fmt_value("ratio", r.ctr))}</td>'
        f'<td class="num">{_e(fmt_value("ratio", r.ctor))}</td>'
        f'<td class="num">{_e(fmt_value("money", r.aov))}</td></tr>'
        for r in report.rest_products
    ]
    head = ["Sản phẩm", "Lượt hiển thị", "Lượt bấm", "Đơn", "CTR", "CTOR", "AOV"]
    return _section(
        "Phần còn lại",
        "Các sản phẩm còn lại có traffic",
        _table(head, body),
        f'<p class="note">Tối đa {REST_ROWS} sản phẩm ngoài top 5 có nhiều lượt hiển thị nhất, số '
        "liệu 30 ngày qua.</p>",
    )


def images_text(count: int) -> str:
    return f"{count} ảnh" if count else "Không"


def _diagnosis_table(report: ShopReport) -> str:
    if not report.diagnoses:
        text = (
            "TikTok chưa trả kết quả chẩn đoán lần này; chi tiết ở phần cuối trang."
            if report.diagnoses_error
            else "Chưa có dữ liệu chẩn đoán của TikTok cho shop này."
        )
        return _section("Chẩn đoán", "TikTok chỉ ra lỗi gì", f"<p>{text}</p>")
    body = [
        f'<tr><td class="name">{_e(r.title)}</td><td>{_e(r.part)}</td><td>{_e(r.how_to_solve)}</td>'
        f'<td class="num">{_e(images_text(r.suggested_images))}</td></tr>'
        for r in report.diagnoses
    ]
    head = ["Sản phẩm", "Phần", "Cách sửa", "Ảnh TikTok gợi ý"]
    return _section(
        "Chẩn đoán",
        "TikTok chỉ ra lỗi gì",
        _table(head, body),
        '<p class="note">Đây là lỗi do công cụ chẩn đoán của TikTok báo cho từng sản phẩm đang '
        "bán. Juli chỉ đề xuất sửa đúng chỗ TikTok chỉ ra.</p>",
    )


def _fetch_text(state: dict[str, Any], code: Any) -> str:
    status = state.get("status", "skipped")
    word = {"ok": "ok", "error": "lỗi", "skipped": "bỏ qua (không lấy trong lần chạy này)"}.get(
        status, status
    )
    extra = [f"{k}={v}" for k, v in state.items() if k not in ("status", "detail")]
    detail = f" — {state['detail']}" if state.get("detail") else ""
    return f"{code(status)} {word}" + (f" ({', '.join(extra)})" if extra else "") + _e(detail)


def _tech_traffic(report: ShopReport, code: Any) -> list[str]:
    t = report.technical
    verdicts = t.get("traffic_verdicts", {})
    sources = t.get("traffic_top_sources", {})
    titles = {c.product_id: c.title for c in report.cards}
    titles.update({p.product_id: p.title for p in report.top_products})
    titles.update({b.product_id: b.title for b in report.traffic})
    verdict_items = "".join(
        f"<li>{_e(_truncate(titles.get(pid, pid), 60))} ({code(pid)}): {code(verdict)}"
        + (
            f", nguồn tăng lượt hiển thị nhiều nhất: {_e(sources.get(pid))}"
            if sources.get(pid)
            else ""
        )
        + "</li>"
        for pid, verdict in verdicts.items()
    )
    diluted = t.get("traffic_diluted", [])
    return [
        "<h3>Kiểm tra nguồn traffic</h3><ol>",
        "<li>Sáu kênh từ khối A-34: thẻ sản phẩm (seller_product_card_performance), Shop Tab "
        "(shop_tab_performance), video của shop (seller_video_performance), LIVE của shop "
        "(seller_live_performance), video affiliate (affiliate_video_performance), LIVE affiliate "
        "(affiliate_live_performance); mỗi kênh so product_impressions và CTR giữa "
        f"{code('a34_30d_current')} và {code('a34_30d_previous')}.</li>",
        f"<li>Kênh được tính khi có từ {t.get('traffic_min_channel_impressions', 200)} lượt "
        f"hiển thị trở lên ở cả hai cửa sổ ({code('traffic_min_channel_impressions')}). "
        "Kênh &quot;tăng mạnh&quot; khi lượt hiển thị/ngày nay ÷ trước ≥ "
        f"{t.get('traffic_spike_ratio', 1.5)} "
        f"({code('traffic_spike_ratio')}). CTR &quot;giảm&quot; khi giảm tương đối ≥ "
        f"{fmt_value('ratio', t.get('traffic_ctr_drop', 0.15))} ({code('traffic_ctr_drop')}); "
        "&quot;ổn định&quot; khi lệch trong "
        f"±{fmt_value('ratio', t.get('traffic_ctr_stable', 0.1))} "
        f"({code('traffic_ctr_stable')}). Mặc định do chủ shop duyệt, chỉnh được trong "
        f"{code('StageDiagnosisConfig')}.</li>",
        f"<li>{code(UNIFORM)}: CTR giảm ở ≥ 2/3 số kênh được tính (tối thiểu 2 kênh); card vẫn "
        f"được phép. {code(DILUTION)}: mọi kênh có CTR giảm đều là kênh tăng mạnh và mọi kênh "
        f"còn lại ổn định; card theo CTR (ảnh bìa, tiêu đề) không được phát, sản phẩm vào danh "
        f"sách theo dõi. {code(UNCLEAR)}: các trường hợp còn lại, kể cả dưới 2 kênh được tính; "
        "card vẫn được phát và kiểm tra này không kết luận được. Kiểm tra áp dụng cho mọi card "
        "nhánh thẻ và card chờ, dù trigger là median hay xu hướng; card CTOR/AOV không bị ảnh "
        f"hưởng. Số sản phẩm bị giữ card vì traffic loãng: {len(diluted)}"
        + (f" ({code(', '.join(diluted))})" if diluted else "")
        + ".</li>",
        f"<li>Kết quả theo sản phẩm (card và top {TOP_N}):"
        f'<ul class="plain">{verdict_items}</ul></li>',
        "<li>Tỷ lệ đơn có giảm giá: các dòng không phải quà tặng của đơn không hủy trong "
        f"{code('orders.json')}, đặt vào cửa sổ theo {code('create_time')} của đơn (múi giờ "
        f"UTC+7; payload không có thời gian theo từng dòng); platform_discount &gt; 0 hoặc "
        f"seller_discount &gt; 0. Ghi lên card khi từ "
        f"{fmt_value('ratio', t.get('platform_discount_note_share', 0.5))} "
        f"({code('platform_discount_note_share')}); dưới "
        f"{t.get('platform_discount_min_lines', 10)} dòng trong cửa sổ thì không hiển thị "
        f"({code('platform_discount_min_lines')}). Số dòng đơn trong hai cửa sổ: "
        f"{t.get('discount_window_orders', 0)}"
        + (
            ""
            if t.get("orders_present") and t.get("discount_window_orders")
            else " — snapshot không có đơn nào rơi vào hai cửa sổ này nên chưa tính được"
        )
        + ".</li>",
        "<li><b>Điểm mù 1, chiến dịch của sàn:</b> Partner API không có endpoint đọc chiến dịch "
        "của sàn (campaign), nên Juli chỉ suy ra gián tiếp từ phần giảm giá của sàn trên đơn "
        "hàng; một chiến dịch không làm thay đổi giá trên đơn sẽ không thấy được.</li>",
        "<li><b>Điểm mù 2, quảng cáo và GMV Max:</b> shop chưa cấp quyền Business API, và A-34 "
        "không tách lưu lượng trả phí khỏi lưu lượng tự nhiên, nên quảng cáo và GMV Max nằm lẫn "
        "trong các kênh trên.</li>",
        f"<li>Khuyến mãi (Search Activities, Search Coupons, Get Activity): "
        f"{_fetch_text(t.get('promotions_status', {}), code)}.</li>",
        f"<li>LIVE của shop (danh sách phiên và sản phẩm theo phiên): "
        f"{_fetch_text(t.get('live_status', {}), code)}.</li>",
        f"<li>Video của shop (danh sách video và sản phẩm theo video): "
        f"{_fetch_text(t.get('videos_status', {}), code)}.</li></ol>",
    ]


def _dec(value: object, kind: str = "ratio") -> str:
    return "—" if value is None else fmt_value(kind, to_decimal(value))


def _gift_line(pid: str, d: dict[str, Any], code: Any) -> str:
    if d.get("gift_product_id"):
        reviews = d["gift_review_count"]
        shown = "chưa rõ số" if reviews is None else str(reviews)
        what = (
            f"chọn {code(d['gift_product_id'])}, giá {_dec(d['gift_price'], 'money')}, "
            f"tồn {d['gift_stock']}, {shown} đánh giá"
        )
    else:
        why = ", ".join(f"{k} {v}" for k, v in d.get("rejected", {}).items()) or "không có ứng viên"
        what = (
            f"không có sản phẩm phù hợp (trần giá {_dec(d.get('max_price'), 'money')}; "
            f"loại do {why})"
        )
    return f"<li>Quà cho {code(pid)}: {what}</li>"


def _tech_levers(report: ShopReport, code: Any) -> list[str]:
    t = report.technical
    cfg = StageDiagnosisConfig()
    win = t.get("order_window", {})
    ship = t.get("shipping_lever", {})
    gift = t.get("gift", {})
    flash = t.get("flash_sale", {})
    sc = t.get("seller_center", {})
    first_cur, last_cur = (date.fromisoformat(d) for d in report.windows["current_30d"])

    def dmy(iso: object) -> str:
        return _dmy(str(iso)) if iso else "—"

    if win.get("used"):
        used = (
            f"{win['used']} đơn trong khoảng thời gian, tạo từ {dmy(win.get('used_first'))} đến "
            f"{dmy(win.get('used_last'))}"
        )
    else:
        used = f"0 đơn trong khoảng thời gian ({NO_ORDERS_IN_WINDOW})"
    left_out = (
        f"; bỏ {win['excluded_out_of_window']} đơn tạo ngoài khoảng "
        f"{dmy(win.get('excluded_first'))} đến {dmy(win.get('excluded_last'))}"
        if win.get("excluded_out_of_window")
        else ""
    )
    fetch = win.get("fetch")
    if isinstance(fetch, dict) and fetch.get("slices"):
        per_slice = ", ".join(
            f"{x['from']}: {x['orders']}" + (" (chạm giới hạn trang)" if x["hit_page_cap"] else "")
            for x in fetch["slices"]
        )
        fetch_text = f"Lấy theo lát 7 ngày, số đơn mỗi lát: {per_slice}; " + (
            "có lát chạm giới hạn trang."
            if fetch.get("any_slice_hit_cap")
            else "không lát nào chạm giới hạn trang."
        )
    else:
        fetch_text = "Không có bản ghi lấy đơn trực tiếp (chạy lại từ snapshot)."
    out = [
        "<h3>Đòn bẩy giá và Seller Center</h3><ol>",
        f"<li><b>Cửa sổ đơn hàng:</b> mọi số liệu từ đơn đọc {code('orders.json')} và chỉ tính "
        f"đơn có {code('create_time')} (UTC+7) trong cửa sổ của nó: 30 ngày qua "
        f"{_dmy(first_cur.isoformat())} – {_dmy(last_cur.isoformat())} cho phân bố số món, "
        "ngưỡng mua nhiều giảm nhiều, tỷ lệ phí vận chuyển, quà tặng, cặp sản phẩm và voucher mức "
        "chi tiêu; 30 ngày trước đó cho so sánh giảm giá; "
        f"{flash.get('low_price_days', 14)} ngày cuối cho giá thấp nhất. Đơn đã dùng (60 ngày): "
        f"{used}{left_out}. Bản lấy trực tiếp lọc đơn theo {code('create_time_ge')} / "
        f"{code('create_time_lt')}, không theo {code('update_time')}. {fetch_text}</li>",
        f"<li><b>Giảm phí vận chuyển</b> ({code('SHIPPING_DISCOUNT')}, "
        f"{code('product_level = PRODUCT')}): sản phẩm cần từ {ship.get('min_orders', 20)} đơn "
        f"trong 30 ngày qua ({code('shipping_lever_min_orders')}) và từ "
        f"{_dec(ship.get('min_paid_share', 0.3))} số đơn có {code('payment.shipping_fee')} &gt; 0 "
        f"({code('shipping_lever_min_paid_share')}). Có {len(ship.get('passed', {}))} sản phẩm "
        f"đạt; {ship.get('insufficient_orders', 0)}/{ship.get('evaluated', 0)} sản phẩm "
        f"{NO_ORDERS_IN_WINDOW}. Thứ tự trong nhánh trang: mô tả, giảm giá sản phẩm, flash sale, "
        "giảm phí vận chuyển; mọi đòn bẩy giá cần shop đã đặt mức giảm giá tối đa.</li>",
        f"<li><b>Quà tặng kèm</b> ({code('gift_discount')}) thay mua nhiều giảm nhiều khi "
        f"{code('bmsm_threshold_unreached')}: sản phẩm khác của shop, còn hàng (tổng tồn kho SKU "
        f"&gt; {gift.get('min_stock', 50)}), chung ít nhất một {code('warehouse_id')} với sản "
        f"phẩm chính, giá bán ≤ {_dec(gift.get('max_price_share', 0.15))} AOV 30 ngày của sản "
        f"phẩm chính và ≤ {_dec(gift.get('max_price_vnd', 1500000), 'money')}, không phải hàng "
        "tặng hoặc không bán; ưu tiên sản phẩm ít đánh giá nhất nếu có ratings.json, nếu không "
        f"thì rẻ nhất. Ngưỡng: mua từ {gift.get('min_items', 2)} món "
        f"({code('MINIMAL_ITEM_QUANTITY')}).</li>",
        *(_gift_line(pid, d, code) for pid, d in gift.get("products", {}).items()),
    ]
    promo_note = (
        "dữ liệu khuyến mãi đã lấy"
        if flash.get("promotions_fetched")
        else "chưa lấy được dữ liệu khuyến mãi nên không bao giờ đề xuất flash sale"
    )
    out += [
        f"<li><b>Flash sale</b> ({code('FLASHSALE')}; ADR-106 bản đầu loại flash sale khỏi v1, "
        "amendment 5 đảo lại với các điều kiện): chỉ chọn khi giảm giá sản phẩm không dùng được "
        "(đang có giảm giá sản phẩm từ bất kỳ nguồn nào theo dữ liệu khuyến mãi, hoặc Juli đang "
        "trong 30 ngày chờ) và đủ mọi điều kiện: không có flash sale của sản phẩm trong "
        f"{flash.get('recent_days', 14)} ngày qua; giá đề xuất = giá thấp nhất khách đã trả trong "
        f"{flash.get('low_price_days', 14)} ngày × (1 − {_dec(flash.get('undercut', 0.01))}), "
        "làm tròn xuống 100 ₫, và mức giảm so với giá niêm yết của SKU đó không vượt mức giảm "
        f"giá tối đa của shop ({_dec(flash.get('max_discount_percent'), 'pct')}); thời lượng "
        f"1–3 ngày, mặc định {flash.get('default_days', 3)}. Giá khách đã trả = "
        f"{code('sale_price')} − {code('platform_discount')} của dòng đơn. Trạng thái: "
        f"{promo_note}. Điểm vi phạm không đọc được qua API: {code(FLASH_CONFIRM)}. Kênh LIVE "
        "không có trường khi tạo qua API.</li>",
    ]
    for pid, d in flash.get("chosen", {}).items():
        out.append(
            f"<li>Flash sale cho {code(pid)}: giá thấp nhất 14 ngày "
            f"{_dec(d['low_price_14d'], 'money')}, giá đề xuất "
            f"{_dec(d['proposed_price'], 'money')}, mức giảm {_dec(d['implied_discount'])}, "
            f"{d['days']} ngày; {code(d['note'])}.</li>"
        )
    blocked = flash.get("blocked_by", {})
    if flash.get("product_discount_running"):
        out.append(
            f"<li>Sản phẩm đang có giảm giá: {len(flash['product_discount_running'])}; điều kiện "
            "flash sale chưa đạt: "
            + (", ".join(f"{code(k)} {v}" for k, v in sorted(blocked.items())) or "không có")
            + ".</li>"
        )
    spend = sc.get("min_spend", {})
    review = sc.get("review_voucher", {})
    bundle = sc.get("bundle", {})
    spend_text = {
        "ok": "đạt điều kiện",
        "no_orders": NO_ORDERS_IN_WINDOW,
        "few_multi": f"dưới {_dec(cfg.min_spend_min_multi_share)} số đơn có từ 2 sản phẩm",
        "aov_not_down": "AOV của shop không giảm đủ so với 30 ngày trước",
    }.get(str(spend.get("verdict")), "")
    review_text = (
        f" (đã phát {review.get('emitted', 0)})"
        if review.get("status") == "ok"
        else " (bỏ qua: không có ratings.json)"
    )
    dropped = (
        f" (bỏ qua: {code(', '.join(sc['dropped_product_has_card']))})"
        if sc.get("dropped_product_has_card")
        else ""
    )
    no_orders = "" if bundle.get("orders") else f"; {NO_ORDERS_IN_WINDOW}"
    out += [
        f"<li><b>Card Seller Center</b> ({sc.get('emitted', 0)} card). Voucher đánh giá: sản "
        f"phẩm đang bán có từ 1 đơn/ngày trong 30 ngày và dưới {cfg.review_voucher_max_reviews} "
        f"đánh giá trong {code('ratings.json')}{review_text}. Ưu Đãi Theo Gói: cặp sản phẩm có "
        f"trong từ {cfg.bundle_min_pair_orders} đơn cùng nhau và từ "
        f"{_dec(cfg.bundle_min_share)} số đơn của một trong hai sản phẩm, tính trên "
        f"{bundle.get('orders', 0)} đơn của 30 ngày qua (đã tìm {bundle.get('pairs_found', 0)} "
        f"cặp, phát {bundle.get('emitted', 0)}){no_orders}. Voucher có mức chi tiêu tối thiểu: "
        f"từ {_dec(cfg.min_spend_min_multi_share)} số đơn của shop có từ 2 sản phẩm khác nhau và "
        f"AOV shop giảm từ {_dec(cfg.min_spend_aov_drop)} so với 30 ngày trước; mức = AOV 30 "
        f"ngày × {cfg.min_spend_aov_multiple}, làm tròn {cfg.min_spend_round_vnd} ₫. Hiện tại: "
        f"{spend_text} (đơn {spend.get('orders', 0)}, đơn nhiều sản phẩm "
        f"{spend.get('multi_orders', 0)}). Mỗi sản phẩm chỉ có một card: card đã có thì card "
        f"Seller Center nhường{dropped}.</li>",
        "<li><b>Đo kết quả card Seller Center:</b> Juli chỉ đo được nếu bạn ghi lại ngày bắt đầu "
        "chạy công cụ trên Seller Center.</li>",
        "<li><b>Năng lực API:</b> tạo được qua API: giảm giá sản phẩm, flash sale (không có "
        "trường kênh LIVE), mua nhiều giảm nhiều, quà tặng kèm, giảm phí vận chuyển. Chỉ đọc: "
        "coupon (search, get), chi tiết giá đơn hàng. Không có: tạo coupon, bundle deal, "
        "voucher / mua nhiều giảm nhiều / flash deal của sàn, chiến dịch của sàn, quảng cáo "
        "(Business API chỉ cho quảng cáo).</li></ol>",
    ]
    return out


def _tech(report: ShopReport) -> str:
    t = report.technical
    w = report.windows

    def span(key: str) -> str:
        return f"{_dmy(w[key][0])} – {_dmy(w[key][1])}"

    def code(text: object) -> str:
        return f"<code>{_e(text)}</code>"

    med = t.get("medians", {})
    peers = med.get("peers", {})

    def med_text(key: str, kind: str) -> str:
        value = med.get(key)
        shown = "chưa đủ peers" if value is None else fmt_value(kind, value)
        return f"{key.upper()} {shown} ({peers.get(key, 0)} peers)"

    ex = report.exclusions
    codes = t.get("diagnosis_codes", {})
    skip = t.get("skip_reasons", {})
    error = report.diagnoses_error
    lis = [
        "<h3>Nguồn dữ liệu</h3><ol>",
        f"<li>Số liệu sản phẩm: {code('GET /analytics/202605/shop_products/performance')} (A-34), "
        f"đọc qua credential production-read. Chi tiết sản phẩm: {code('GetProduct')}. "
        f"Chẩn đoán: {code('GET /product/202405/products/diagnoses')}.</li></ol>",
        "<h3>Cửa sổ thời gian</h3><ol>",
        f"<li>Bảng phân tích: 30 ngày qua {span('current_30d')} so với 30 ngày trước đó "
        f"{span('previous_30d')}.</li>",
        f"<li>Card: 14 ngày {span('card_current')} so với 28 ngày liền trước {span('card_prior')}; "
        f"GMV 28 ngày {span('card_last28')} dùng để xếp hạng.</li></ol>",
        "<h3>Công thức</h3><ol>",
        "<li>CTR = product_clicks ÷ product_impressions; CTOR = sku_orders ÷ product_clicks; "
        "AOV = gmv ÷ sku_orders; Món/đơn = items_sold ÷ sku_orders; Thêm giỏ/click = "
        "add_cart_count ÷ product_clicks; Hoàn tiền/GMV = refunds ÷ gmv; Đơn/ngày và GMV/ngày "
        "chia cho 30. Số của shop và của nhóm là tổng các số đếm rồi mới chia, không phải trung "
        "bình các tỷ lệ.</li>",
        "<li>Kênh thẻ sản phẩm = seller_product_card_performance + shop_tab_performance "
        "(impressions, clicks và attributed_sku_orders cộng lại; đơn Shop Tab = "
        "shop_tab_product_clicks × shop_tab_ctor_sku).</li>",
        "<li>Tỷ trọng kênh = đơn gán cho từng kênh ÷ tổng đơn gán của năm kênh: thẻ sản phẩm "
        "(seller_product_card_performance), Shop Tab, video của shop (seller_video_performance), "
        "LIVE của shop (seller_live_performance), affiliate "
        "(affiliate_total_performance). Tỷ trọng được chuẩn hóa trên năm khối kênh vì TikTok gán "
        "một số đơn cho nhiều hơn một khối, nên chia cho sku_orders sẽ vượt 100 %.</li></ol>",
        "<h3>Loại trừ</h3><ol>",
        f"<li>{ex['gift']} sản phẩm bị loại vì tiêu đề chứa một trong "
        f"{code(', '.join(t.get('exclude_title_patterns', [])))}; "
        f"{ex['inactive']} sản phẩm bị loại "
        f"vì trạng thái khác {code('ACTIVATE')}; {ex['no_detail']} sản phẩm không có chi tiết nên "
        f"giữ lại (không rõ trạng thái). Còn lại {t.get('live_products', 0)} sản phẩm đang bán, "
        f"trong đó {t.get('rest_live_products', 0)} ngoài top {TOP_N}.</li></ol>",
        "<h3>Card</h3><ol>",
        f"<li>{code(STATUS_RULE)}: stage diagnosis của ADR-106 phát card khi một yếu tố vượt "
        "volume floor (ADR-077 d.4) và max(gap_median, gap_trend) ≥ "
        f"{t.get('gap_threshold_median', 0.2)}. Tìm thấy "
        f"{t.get('rule_cards_found', 0)} sản phẩm như vậy. Dưới CTR khỏe, nhánh trang không rơi "
        "sang nhánh thẻ (ảnh bìa, tiêu đề); nhánh thẻ vẫn rơi sang nhánh trang.</li>",
        f"<li>{code(STATUS_NEEDS_CAP)}: gap vượt ngưỡng, đã có file chẩn đoán, không có mã mô tả "
        f"và shop chưa đặt mức giảm giá tối đa (skip reason {code('discount_cap_needed')}; mức "
        f"giảm tối đa: {'đã đặt' if t.get('discount_cap_set') else 'chưa đặt'}). Tìm thấy "
        f"{t.get('needs_cap_found', 0)} sản phẩm.</li>",
        f"<li>{code(STATUS_NOT_ASKED)}: gap vượt ngưỡng, không có bằng chứng cục bộ và không có "
        f"file chẩn đoán cho sản phẩm (skip reason {code('tiktok_not_asked')}, ADR-090 d.3). Tìm "
        f"thấy {t.get('not_asked_found', 0)} sản phẩm, xếp theo gap × GMV 28 ngày, chỉ lấp chỗ "
        "còn trống. Lý do lấy gap lớn nhất trong CTR thẻ sản phẩm và CTOR. Có file chẩn đoán "
        f"nhưng không có mã cho nhánh cần sửa: không card, vào danh sách theo dõi (skip reason "
        f"{code('tiktok_found_no_fault')}).</li>",
        f"<li>{code(STATUS_OWNER)}: {t.get('owner_tests', 0)} thử nghiệm từ "
        f"{code('owner_tests.json')}, xếp sau card của Juli theo thứ tự trong file. Một sản phẩm "
        "chỉ có một card; card của Juli thắng thử nghiệm của chủ shop trên cùng sản phẩm"
        + (
            f" (bỏ thử nghiệm: {code(', '.join(t['owner_tests_dropped_rule_card_wins']))})"
            if t.get("owner_tests_dropped_rule_card_wins")
            else ""
        )
        + f". Tối đa {t.get('max_open_cards_per_shop', 5)} card; phần vượt vào danh sách "
        "theo dõi. Thứ tự: Juli tự đề xuất, Cần mức giảm giá tối đa, Thử nghiệm theo kế hoạch "
        "của bạn, Bạn tự làm trên Seller Center, Chưa hỏi TikTok.</li>",
        f"<li>{code(STATUS_SC)}: {t.get('seller_center', {}).get('emitted', 0)} card; xem mục "
        "&quot;Đòn bẩy giá và Seller Center&quot; bên dưới.</li>",
        "<li>Ngưỡng mua nhiều giảm nhiều: "
        + (
            f"{t.get('orders_counted', 0)} đơn không hủy tạo trong 30 ngày qua từ "
            f"{code('orders.json')}; số lượng = số "
            f"dòng không phải quà tặng của sản phẩm trong đơn; q = trung vị số lượng + 1, chỉ phát "
            f"card khi ít nhất {fmt_value('ratio', t.get('bmsm_min_share_at_threshold', 0.05))} "
            f"đơn đã mua từ q (skip reason {code('bmsm_threshold_unreached')}); dưới "
            f"{t.get('bmsm_min_orders_for_histogram', 20)} đơn của sản phẩm thì "
            "q = floor(món/đơn trung bình) + 1, tối thiểu 2."
            if t.get("orders_present")
            else f"{NO_ORDERS_IN_WINDOW} (không có đơn nào tạo trong 30 ngày qua trong "
            f"{code('orders.json')}) nên mọi sản phẩm dùng q = floor(món/đơn trung bình) + 1, "
            "tối thiểu 2."
        )
        + "".join(
            f" {code(pid)}: q = {d['threshold_items']} ({_e(d['source'])}, {d['orders']} đơn)."
            for pid, d in t.get("bmsm", {}).items()
        )
        + "</li>",
        "<li>Điểm đánh giá: "
        + (
            f"đã áp dụng {t.get('ratings_count', 0)} sản phẩm từ {code('ratings.json')} (nguồn: "
            f"nhập tay / FastMoss); dưới {t.get('min_rating_for_demand_levers')} sao không có "
            "card ở mọi góc độ."
            if t.get("ratings_applied")
            else "không áp dụng (không có ratings.json)."
        )
        + "</li>",
        "<li>Chỉ số chính dưới volume floor của 14 ngày hiển thị "
        f"{code(NOT_ENOUGH_DATA)} thay vì một con số.</li>",
        f"<li>Shop median: {med_text('ctr', 'ratio')}, {med_text('ctor', 'ratio')}, "
        f"{med_text('aov', 'money')} "
        f"(cần ≥ {t.get('min_peers_for_median', 3)} peers vượt volume floor, ADR-106 Amendment 1). "
        f"Card xét {t.get('card_products', 0)} sản phẩm có bán trong 14 ngày, "
        f"{t.get('card_excluded', 0)} bị loại.</li>",
        "<li>Skip reasons: "
        + (", ".join(f"{code(k)} {v}" for k, v in sorted(skip.items())) or "không có")
        + ".</li></ol>",
        *_tech_levers(report, code),
        *_tech_traffic(report, code),
        "<h3>Mã chẩn đoán của TikTok</h3><ol>",
        "<li>Khớp theo tiền tố, không theo danh sách cố định: ảnh bìa = "
        f"{code('MAIN_IMG_*')}; tiêu đề = {code('TITLE_*')} hoặc {code('SEO_DIAGNOSTIC_ITEM')}; "
        f"mô tả = {code('DESC_*')} hoặc {code('DESCRIPTION_*')}; còn lại là Khác.</li>",
        "<li>Mã đã nhận: "
        + (", ".join(f"{code(k)} ×{v}" for k, v in sorted(codes.items())) or "không có")
        + ".</li>",
    ]
    if error:
        lis.append(
            f"<li>Lần gọi chẩn đoán lỗi: {code(error.get('error_class', ''))} "
            f"{_e(error.get('message', ''))}</li>"
        )
    lis.append("</ol>")
    return (
        '<section class="tech" aria-labelledby="tech-h">'
        '<div class="eyebrow">Dành cho đội kỹ thuật</div>'
        '<h2 id="tech-h">Chú thích kỹ thuật</h2>' + "".join(lis) + "</section>"
    )


def render_html(report: ShopReport) -> str:
    """A content fragment for the Artifact viewer: title, fonts, style, markup."""
    header = (
        '<header style="display:grid;gap:12px">'
        f'<div class="eyebrow">{_e(report.shop_name)} · '
        f"số liệu đến ngày {_e(_dmy(report.as_of))}</div>"
        f"<h1>Báo cáo tối ưu {_e(report.shop_name)}</h1>"
        '<p class="lede">Các card bên dưới dùng số liệu 14 ngày gần nhất so với 4 tuần liền trước. '
        "Mọi bảng phân tích còn lại so 30 ngày gần nhất với 30 ngày liền trước đó. Sản phẩm quà "
        "tặng, hàng không bán và sản phẩm đã ngừng bán không được tính.</p></header>"
    )
    markup = (
        '<div class="wrap">'
        + header
        + _legend(report.cards)
        + _card_table(report)
        + _traffic_section(report)
        + _watch_table(report)
        + _shop_table(report)
        + _group_table(report)
        + _top_table(report)
        + _rest_table(report)
        + _diagnosis_table(report)
        + _tech(report)
        + "<footer>Mọi con số là ước tính trên dữ liệu TikTok cập nhật trễ một ngày. Không có thay "
        "đổi nào được ghi lên TikTok khi lập báo cáo này.</footer></div>"
    )
    title = f"<title>Báo cáo tối ưu {_e(report.shop_name)}</title>"
    return f"{title}\n{_FONTS}\n<style>\n{_STYLE}</style>\n{markup}\n"
