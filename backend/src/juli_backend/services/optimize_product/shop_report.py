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
"""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from juli_backend.services.optimize_product.cards import (
    ANGLE_ACTION,
    build_cards,
    gap_reason_sentence,
)
from juli_backend.services.optimize_product.catalog_scan import (
    a34_index,
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
    Label,
    Skip,
    Trigger,
)
from juli_backend.services.optimize_product.funnel import ZERO, FunnelWindow, to_decimal
from juli_backend.services.optimize_product.listing_signals import (
    is_description_code,
    is_image_code,
    is_title_code,
    listing_signals_from_product,
)

WINDOW_DAYS = 30
TOP_N = 5
REST_ROWS = 10
HOW_TO_SOLVE_MAX = 140

STATUS_RULE = "Juli tự đề xuất"
STATUS_PENDING = "Chờ TikTok chỉ ra lỗi"

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


@dataclass(frozen=True)
class DiagnosisRow:
    product_id: str
    title: str
    part: str
    how_to_solve: str
    suggested_images: int
    code: str


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
    diagnoses: list[DiagnosisRow]
    diagnoses_error: dict[str, str] | None
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
    """Share (%) of a product's orders by channel, non-zero channels only."""

    def block(name: str) -> dict:
        value = item.get(name)
        return value if isinstance(value, dict) else {}

    total = to_decimal((item.get("total_performance") or {}).get("sku_orders"))
    if total <= 0:
        return []
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


def _cards(snapshot: Path, config: StageDiagnosisConfig) -> tuple[list[ReportCard], dict[str, Any]]:
    """Rule cards, then pending cards, through the one shared pipeline."""
    funnels, _signals, evidence_by_id, excluded = build_inputs(snapshot, config)
    medians, diagnoses, skips = diagnose_all(funnels, evidence_by_id, excluded, config)
    by_id = {d.product_id: d for d in diagnoses}
    funnel_by_id = {f.product_id: f for f in funnels}
    limit = config.max_open_cards_per_shop

    cards: list[ReportCard] = []
    for card in build_cards(diagnoses, config)[:limit]:
        diag = by_id[card.product_id]
        if diag.label is Label.CTOR:
            kpi, value = "CTOR", fmt_value("ratio", diag.gaps["ctor"].value)
        else:
            kpi, value = "AOV", fmt_value("money", diag.gaps["aov"].value)
        if diag.angle is Angle.MUA_NHIEU_GIAM_NHIEU and diag.bmsm:
            text = f"Mua nhiều giảm nhiều, từ {diag.bmsm.threshold_items} món"
        else:
            text = ANGLE_ACTION[diag.angle]
        cards.append(
            ReportCard(
                rank=len(cards) + 1,
                product_id=card.product_id,
                title=card.title,
                main_kpi=kpi,
                main_kpi_value=value,
                reason=card.reason,
                change=text,
                status=STATUS_RULE,
                rank_score=diag.rank_score,
            )
        )

    pending: list[tuple[Decimal, Decimal, Gap, Skip]] = []
    for skip in skips:
        if skip.reason != "no_diagnosis_codes":
            continue
        # This skip only arises under the CTOR label, whose gaps are CTR and CTOR.
        firing = [g for g in (skip.gaps["ctr"], skip.gaps["ctor"]) if g.fires(config)]
        if not firing:
            continue
        gap = max(firing, key=lambda g: g.gap)
        pending.append((gap.gap * funnel_by_id[skip.product_id].gmv_28d, gap.gap, gap, skip))
    pending.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for score, _size, gap, skip in pending[: max(limit - len(cards), 0)]:
        gaps = skip.gaps
        branch = Branch.CARD if gaps["ctr"].gap >= gaps["ctor"].gap else Branch.PAGE
        first = BRANCH_ORDER[branch][0]
        cards.append(
            ReportCard(
                rank=len(cards) + 1,
                product_id=skip.product_id,
                title=skip.title,
                main_kpi="CTOR",
                main_kpi_value=fmt_value("ratio", gaps["ctor"].value),
                reason=gap_reason_sentence(
                    gap,
                    gap.trigger or Trigger.SHOP_MEDIAN,
                    full_median_peers=config.full_median_peers,
                ),
                change=f"{ANGLE_ACTION[first]}, nếu TikTok chỉ ra lỗi",
                status=STATUS_PENDING,
                rank_score=score,
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
        "rule_cards_found": len(diagnoses),
        "pending_cards_found": len(pending),
        "skip_reasons": dict(Counter(s.reason.split(":")[0] for s in skips)),
    }
    return cards, tech


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

    cards, tech = _cards(snapshot, config)
    error = load_json(snapshot / "diagnoses" / "_error.json")
    tech.update(
        {
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
        windows=report_windows(as_of, config),
        exclusions=counts,
        shop_rows=shop_rows,
        group_rows=group_rows,
        top_products=top_products,
        rest_products=rest_products,
        cards=cards,
        diagnoses=diagnosis_rows,
        diagnoses_error=(
            {str(k): str(v) for k, v in error.items()} if isinstance(error, dict) else None
        ),
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
    STATUS_PENDING: (
        "warn",
        "Số liệu cho thấy sản phẩm có vấn đề, nhưng Juli kiểm tra trang sản phẩm chưa thấy lỗi "
        "nào. Juli sẽ không sửa đoán. Card chờ công cụ chẩn đoán của TikTok báo lỗi cụ thể (ảnh, "
        "tiêu đề, mô tả) rồi mới đề xuất sửa đúng chỗ đó.",
    ),
}
_COUNT_WORD = {1: "Một", 2: "Hai", 3: "Ba"}


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
        pill = "ok" if c.status == STATUS_RULE else "warn"
        body.append(
            f'<tr><td class="num">{c.rank}</td><td class="name">{_e(c.title)}</td>'
            f'<td class="kpiv"><span class="pill kpi">{_e(c.main_kpi)}</span> '
            f"{_e(c.main_kpi_value)}</td><td>{_e(c.reason)}</td><td>{_e(c.change)}</td>"
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
    body.append(f'<tr><td class="rowlabel">Kênh ra đơn (30 ngày qua)</td>{"".join(channels)}</tr>')
    return _section(
        "Chủ lực",
        "Từng sản phẩm trong top 5",
        _table(head, body),
        '<p class="note">Mỗi ô ghi số 30 ngày qua và so với 30 ngày trước đó. Kênh ra đơn cho biết '
        "đơn của sản phẩm đến từ đâu; các kênh có thể chồng lên nhau nên tổng không nhất thiết là "
        "100 %.</p>",
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
        "<li>Kênh ra đơn = đơn gán cho từng kênh ÷ sku_orders của total_performance: thẻ sản phẩm "
        "(seller_product_card_performance), Shop Tab, video của shop (seller_video_performance), "
        "LIVE của shop (seller_live_performance), affiliate "
        "(affiliate_total_performance).</li></ol>",
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
        f"{t.get('rule_cards_found', 0)} sản phẩm như "
        f"vậy; tối đa {t.get('max_open_cards_per_shop', 5)} card.</li>",
        f"<li>{code(STATUS_PENDING)}: gap vượt ngưỡng nhưng không có mã chẩn đoán "
        f"(skip reason {code('no_diagnosis_codes')}, ADR-090 d.3). Tìm thấy "
        f"{t.get('pending_cards_found', 0)} sản phẩm, xếp theo gap × GMV 28 ngày, lấp chỗ "
        "còn trống. "
        "Lý do lấy gap lớn nhất trong CTR thẻ sản phẩm và CTOR; đề xuất là góc độ đầu tiên của "
        "nhánh tương ứng.</li>",
        f"<li>Shop median: {med_text('ctr', 'ratio')}, {med_text('ctor', 'ratio')}, "
        f"{med_text('aov', 'money')} "
        f"(cần ≥ {t.get('min_peers_for_median', 3)} peers vượt volume floor, ADR-106 Amendment 1). "
        f"Card xét {t.get('card_products', 0)} sản phẩm có bán trong 14 ngày, "
        f"{t.get('card_excluded', 0)} bị loại.</li>",
        "<li>Skip reasons: "
        + (", ".join(f"{code(k)} {v}" for k, v in sorted(skip.items())) or "không có")
        + ".</li></ol>",
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
