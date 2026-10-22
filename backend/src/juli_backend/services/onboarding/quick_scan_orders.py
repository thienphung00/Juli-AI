"""The quick scan for the zero-analytics sandbox shop, by paid orders (fast track P64, D73.3).

TikTok Analytics (A-34) answers all zeros for a sandbox shop, so the quick scan
(``quick_scan``) found no product with GMV or clicks and wrote no card. For a
shop read through its OWN ``sandbox_write`` credential whose 14-day A-34 rows are
all zero, the scan instead:

1. ranks the products by revenue (then units) of the shop's real paid synced
   order lines over the last :data:`ORDERS_WINDOW_DAYS` days
   (``shop_diagnosis_daily.orders_source``: unpaid / cancelled / returned excluded);
2. asks TikTok's listing diagnosis for those products (one call, as usual) and
   reads each chosen product's listing (Get Product) -- both real reads;
3. picks the title lever when TikTok (or Juli's reading of the listing) flags the
   title, else the description lever when it flags the description -- the levers
   Juli writes itself (executor ``juli``); the cover image needs the seller's photo
   and is not proposed here;
4. stores a rule-based proposal (``diagnosis.listing_proposal``: field, before,
   after) built ONLY from the listing's own facts (its title, brand, leaf category,
   SKU variant names, its existing description), so Duyệt shows Trước / Sau and
   Thực thi has content. No LLM (D24.1), nothing invented.

The card's KPI is the product's real AOV from those orders; no funnel number
(CTR / CTOR / recoverable GMV) is claimed. Real shops never take this path.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from juli_backend.services.optimize_product.cards import ANGLE_ACTION
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.decision_cards import STATUS_CODE_RULE, CardProposal
from juli_backend.services.optimize_product.diagnosis import Angle, Branch, Label, Trigger
from juli_backend.services.optimize_product.funnel import FunnelWindow, ProductFunnel
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    EvidenceSource,
    derive_local_evidence,
    is_description_code,
    is_title_code,
    listing_signals_from_product,
)
from juli_backend.services.shop_diagnosis_daily.orders_source import OrderLine

#: The orders the ranking reads (a sandbox gets few orders, so a month, not 14 days).
ORDERS_WINDOW_DAYS = 30
QUICK_SCAN_ORDERS_LABEL = f"Đề xuất nhanh · dựa trên đơn hàng {ORDERS_WINDOW_DAYS} ngày"
QUICK_SCAN_ORDERS_BASIS = (
    f"Sản phẩm chọn theo doanh thu từ đơn hàng TikTok đã thanh toán ({ORDERS_WINDOW_DAYS} ngày "
    "gần nhất); nội dung đề xuất lấy từ chính trang sản phẩm"
)
#: ``diagnosis.quick_scan.source`` of these cards (the card view reads it).
SOURCE_ORDERS = "orders"
TITLE_MAX_CHARS = 255
_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ProductSales:
    """One product's paid order totals over the window."""

    product_id: str
    revenue: Decimal
    units: int
    orders: int


def rank_by_orders(lines: Iterable[OrderLine], limit: int) -> list[ProductSales]:
    """Products by paid revenue, then units (best first), at most ``limit``."""
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    units: dict[str, int] = defaultdict(int)
    orders: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        revenue[line.product_id] += Decimal(str(line.revenue))
        units[line.product_id] += line.quantity
        orders[line.product_id].add(line.order_id)
    ranked = sorted(revenue, key=lambda pid: (revenue[pid], units[pid], pid), reverse=True)
    return [
        ProductSales(pid, revenue[pid], units[pid], len(orders[pid]))
        for pid in ranked
        if revenue[pid] > 0 or units[pid] > 0
    ][:limit]


def funnel_from_sales(sales: ProductSales, title: str, *, days: int) -> ProductFunnel:
    """The product's window from its orders: sales only, no traffic (never derived)."""
    window = FunnelWindow(
        days=days,
        sku_orders=Decimal(sales.orders),
        items_sold=Decimal(sales.units),
        gmv=sales.revenue,
    )
    return ProductFunnel(
        product_id=sales.product_id, title=title, current=window, prior=None, gmv_28d=window.gmv
    )


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def _leaf_category(detail: Mapping[str, Any]) -> str:
    chains = [c for c in detail.get("category_chains") or [] if isinstance(c, Mapping)]
    leaf = next((c for c in chains if c.get("is_leaf")), chains[-1] if chains else None)
    return _clean(str((leaf or {}).get("local_name") or ""))


def _brand(detail: Mapping[str, Any]) -> str:
    """The listing's brand -- only when its own title already names it (D73.5).

    The shop's built-in listing rule (``shop_rules.SOURCE_NAMES_RULE_VI``): no brand,
    manufacturer or shop name the source title does not carry. A brand the title lacks
    (or a "No brand" placeholder) is never written into a proposal.
    """
    from juli_backend.services.agent.tools.listing_rules import source_terms_not_in

    brand = detail.get("brand")
    name = _clean(str(brand.get("name") or "")) if isinstance(brand, Mapping) else ""
    if not name or name in source_terms_not_in(detail, str(detail.get("title") or "")):
        return ""
    return name


def _variants(detail: Mapping[str, Any], limit: int = 4) -> list[str]:
    """Distinct SKU variant values (``sales_attributes[].value_name``), in listing order."""
    seen: list[str] = []
    for sku in detail.get("skus") or []:
        if not isinstance(sku, Mapping):
            continue
        for attr in sku.get("sales_attributes") or []:
            value = _clean(str(attr.get("value_name") or "")) if isinstance(attr, Mapping) else ""
            if value and value.lower() not in {v.lower() for v in seen}:
                seen.append(value)
    return seen[:limit]


def propose_title(detail: Mapping[str, Any]) -> str | None:
    """The current title + the listing's own brand / category / variants it lacks.

    ``None`` when the listing has nothing the title does not already say.
    """
    title = _clean(str(detail.get("title") or ""))
    if not title:
        return None
    lower = title.lower()
    extras: list[str] = []
    for part in (_brand(detail), _leaf_category(detail)):
        if part and part.lower() not in lower and part.lower() not in " ".join(extras).lower():
            extras.append(part)
    variants = [v for v in _variants(detail) if v.lower() not in lower]
    if variants:
        extras.append(", ".join(variants))
    if not extras:
        return None
    proposed = f"{title} - {' - '.join(extras)}"
    if len(proposed) > TITLE_MAX_CHARS:
        proposed = proposed[:TITLE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" -,")
    return proposed if proposed != title else None


def _paragraphs(description: str) -> list[str]:
    """The existing description as plain paragraphs (a one-block text split by sentence)."""
    text = html.unescape(_TAG_RE.sub("\n", description))
    blocks = [_clean(b) for b in text.split("\n") if _clean(b)]
    if len(blocks) == 1:
        blocks = [_clean(s) for s in _SENTENCE_RE.split(blocks[0]) if _clean(s)]
    return blocks


def propose_description(detail: Mapping[str, Any]) -> str | None:
    """A structured description from the listing's facts and its existing text.

    The title as the opening line, a short list (category, brand, variants) and the
    existing description split into paragraphs. ``None`` when that adds nothing.
    """
    title = _clean(str(detail.get("title") or ""))
    existing = str(detail.get("description") or "")
    facts = [
        (label, value)
        for label, value in (
            ("Danh mục", _leaf_category(detail)),
            ("Thương hiệu", _brand(detail)),
            ("Phân loại", ", ".join(_variants(detail, limit=8))),
        )
        if value
    ]
    parts: list[str] = []
    if title:
        parts.append(f"<p>{html.escape(title)}</p>")
    if facts:
        items = "".join(f"<li>{label}: {html.escape(value)}</li>" for label, value in facts)
        parts.append(f"<ul>{items}</ul>")
    parts.extend(f"<p>{html.escape(p)}</p>" for p in _paragraphs(existing))
    proposed = "".join(parts)
    if not proposed or proposed == existing.strip():
        return None
    return proposed


def _money(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}".replace(",", ".") + " ₫"


def orders_proposal(
    sales: ProductSales,
    detail: Mapping[str, Any],
    tiktok_evidence: list[Evidence],
    config: StageDiagnosisConfig,
    *,
    levers: tuple[str, ...] = ("title", "description"),
) -> CardProposal | None:
    """A title or description card for a best-selling product, or ``None``.

    The lever needs a reason on the listing itself: a TikTok diagnosis code first,
    else Juli's reading of the listing (local evidence, named as Juli's). ``levers``
    narrows the choice (P64: the description when the title's chain is taken).
    """
    signals = listing_signals_from_product(dict(detail), config)
    if signals.excluded_reason:
        return None
    local = derive_local_evidence(signals, config)
    evidence = list(tiktok_evidence) + [
        e for e in local if e.code not in {t.code for t in tiktok_evidence}
    ]
    title_evidence = [e for e in evidence if is_title_code(e.code)]
    desc_evidence = [e for e in evidence if is_description_code(e.code)]
    before = str(detail.get("title") or "")
    choice: tuple[Angle, Branch, str, list[Evidence], str] | None = None
    if "title" in levers and title_evidence and (after := propose_title(detail)):
        choice = (Angle.TIEU_DE, Branch.CARD, "title", title_evidence, after)
    elif "description" in levers and desc_evidence and (after := propose_description(detail)):
        before = str(detail.get("description") or "")
        choice = (Angle.MO_TA, Branch.PAGE, "description", desc_evidence, after)
    if choice is None:
        return None
    angle, branch, field_code, lever_evidence, after = choice
    aov = sales.revenue / sales.orders if sales.orders else None
    reason = (
        f"Sản phẩm bán chạy nhất theo đơn hàng TikTok {ORDERS_WINDOW_DAYS} ngày qua: "
        f"{sales.orders} đơn, {sales.units} sản phẩm, doanh thu {_money(sales.revenue)}"
    )
    detail_vi = (
        "Viết lại tiêu đề từ thương hiệu, danh mục và phân loại có trên trang sản phẩm"
        if angle is Angle.TIEU_DE
        else "Sắp xếp lại mô tả thành từng đoạn, thêm danh mục, thương hiệu và phân loại"
    )
    return CardProposal(
        rank=0,
        product_id=sales.product_id,
        title=str(detail.get("title") or sales.product_id),
        status=STATUS_CODE_RULE,
        label=Label.AOV,
        stage=branch,
        lever=angle,
        trigger=Trigger.SHOP_MEDIAN,
        gap=Decimal(0),
        main_kpi_value=_money(aov) if aov is not None else "—",
        main_kpi_raw=aov,
        reason=reason,
        action=ANGLE_ACTION[angle],
        lever_detail=detail_vi,
        lever_confirmed=any(e.source is EvidenceSource.TIKTOK for e in lever_evidence),
        evidence=tuple(lever_evidence),
        rank_score=sales.revenue,
        listing_proposal={"field": field_code, "before": before, "after": after},
    )


def orders_quick_block(scanned_at: datetime) -> dict[str, Any]:
    """``diagnosis.quick_scan`` of an orders-based quick card."""
    return {
        "label": QUICK_SCAN_ORDERS_LABEL,
        "confidence": "Tham khảo",
        "window_days": ORDERS_WINDOW_DAYS,
        "scanned_at": scanned_at.isoformat(),
        "basis": QUICK_SCAN_ORDERS_BASIS,
        "source": SOURCE_ORDERS,
    }


__all__ = [
    "ORDERS_WINDOW_DAYS",
    "QUICK_SCAN_ORDERS_BASIS",
    "QUICK_SCAN_ORDERS_LABEL",
    "SOURCE_ORDERS",
    "ProductSales",
    "funnel_from_sales",
    "orders_proposal",
    "orders_quick_block",
    "propose_description",
    "propose_title",
    "rank_by_orders",
]
