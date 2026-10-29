"""The recommendation card block of a Quyết định item (fast track P10-A, ADR-109 am. 1 d.1-2).

Contract ``fasttrack/contracts/p10-quyet-dinh.md`` §1: ``recommendation.card`` --
everything the approved card layout shows, built at read time from the ADR-106
card payload plus what only the database knows now (the product's seller SKUs,
the card's status, a run's before/after values). Additive: every existing
field of the item is unchanged; a card without an ADR-106 ``diagnosis`` gets no
block.

Field rules, where the contract leaves a choice:

- ``status``: ``dismissed`` → ``rejected``; ``approved`` / ``executing`` →
  ``applied`` once the card's latest run finished ``completed`` having written
  something, else ``running``; ``withdrawn`` / ``expired`` → ``expired``;
  ``active`` → ``expired`` when it was surfaced :data:`PROPOSAL_VALIDITY_DAYS`
  (7, D24.17) or more ago (``computed_at`` for a card never surfaced) or the
  product's title changed since it was proposed, else ``pending``.
- ``adjusted_by_history`` (P14-B, D24.6): the card's rank was weighted by the
  shop's history for the lever (calibration or seller reasons), so the UI can
  say "đã điều chỉnh theo kết quả trước". The shown GMV stays the rule-based
  estimate.
- ``main_kpi``: the weak stage the GMV estimate is built on
  (``recoverable_gmv_basis``), ``target`` = its ``reference_rate`` so the KPI
  and ``expected_gmv_per_month`` agree. Without a basis: the diagnosis's main
  KPI, no target. A pre-D29 card (no ``kpi``) that the re-score could not reach
  has its target capped at 3 × a fallback band (``optimize_product.rescore``) and
  its GMV estimate scaled with it -- never the uncapped shop median.
- ``tiktok_codes``: labels of diagnosis codes TikTok itself returned. Juli's
  local reading of the same codes is named in ``reason_full`` as "Juli đánh
  giá", never as TikTok's (OP-NFR-2).
- ``quick_scan`` (fast track P17, D26): a quick-scan card's label, confidence
  ("Tham khảo"), window and basis, else ``None``; its ``gmv_method`` names the
  14-day window.
- ``before_after``: only complete pairs -- the latest run's recorded writes
  (``run_write_values``). A pending card's "after" does not exist yet (Juli
  drafts it in the run), so it has none -- except a card that stored a
  rule-based ``diagnosis.listing_proposal`` (P64, D73.3: the sandbox shop's
  orders-based quick cards), which shows it until a run records writes.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    WRITE_MODE_SIMULATED,
    ActionCard,
    InventoryItem,
    Product,
    WorkflowRun,
)
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.agent.tools.diagnosis_labels import diagnosis_label_vi
from juli_backend.services.optimize_product.rescore import cap_legacy_target, has_d29_kpi
from juli_backend.services.product_name import (
    is_seller_visible_sku,
    known_product_name,
    short_product_name,
)

WORKFLOW_LABEL_VI = "Tối ưu sản phẩm"
#: P64 (D73.3): the sandbox "Tạo sản phẩm" card reads as a creation, like its run header.
CREATE_PRODUCT_LABEL_VI = "Tạo sản phẩm"
#: P65 (D74): the sandbox "Tạo khuyến mãi" card reads "Khuyến mãi · Cập nhật …".
CREATE_PROMOTION_LABEL_VI = "Khuyến mãi"
#: D24.17: a card is valid 7 days from surfacing.
PROPOSAL_VALIDITY_DAYS = 7

#: Lever code -> (Vietnamese label, who carries it out).
LEVERS: Mapping[str, tuple[str, str]] = {
    "cover_image": ("Ảnh bìa", "juli_with_photo"),
    "title": ("Tiêu đề", "juli"),
    "description": ("Mô tả", "juli"),
    "product_discount": ("Giảm giá sản phẩm", "seller_center"),
    "flash_sale": ("Flash sale", "seller_center"),
    "shipping_discount": ("Giảm phí vận chuyển", "seller_center"),
    "buy_more_save_more": ("Mua nhiều giảm nhiều", "seller_center"),
    # P64 (D73.3): the sandbox reviewer's "Tạo sản phẩm" -- Juli creates the listing.
    "create_product": ("Tạo sản phẩm", "juli"),
    # P65 (D74): the sandbox reviewer's "Tạo khuyến mãi" -- Juli creates the discount.
    "create_promotion": ("Tạo khuyến mãi", "juli"),
}

#: The listing field each Juli-executed lever changes.
_LEVER_FIELDS: Mapping[str, tuple[str, str]] = {
    "cover_image": ("main_images", "Ảnh bìa"),
    "title": ("title", "Tiêu đề"),
    "description": ("description", "Mô tả"),
    "create_product": ("new_listing", "Sản phẩm mới"),
    "create_promotion": ("product_discount", "Giảm giá"),
}

_FIELD_LABELS_VI: Mapping[str, str] = {"title": "Tiêu đề", "description": "Mô tả"}

_KPI_LABELS_VI: Mapping[str, str] = {
    "ctr": "CTR - Thẻ sản phẩm",
    "ctor": "CTOR - Thẻ sản phẩm",
    "aov": "AOV (SKU)",
    # P23 (D29): a GMV fall explained by impressions targets Hiển thị.
    "impressions": "Lượt hiển thị",
    # P65 (D74): the "Tạo khuyến mãi" card's KPI is the promotion itself (no ROI).
    "promotion": "Khuyến mãi",
    # P64 (D73.3): the "Tạo sản phẩm" card's KPI is the new listing itself.
    "products": "Sản phẩm",
}

#: A KPI key the copy table does not know: never the raw key on screen.
UNKNOWN_KPI_LABEL_VI = "Chỉ số khác"

#: ≤ 6 words, by the stage the diagnosis found weak.
_REASON_SHORT_VI: Mapping[str, str] = {
    "card": "Ít người bấm vào sản phẩm",
    "page": "Khách xem nhưng ít đặt hàng",
    "basket": "Mỗi đơn mua ít món",
    # P64 (D73.3): the "Tạo sản phẩm" card.
    "catalog": "Mở rộng danh mục",
    # P65 (D74): the "Tạo khuyến mãi" card (no ROI claim).
    "promotion": "Thử giảm giá",
}

#: P64 (D73.3): an orders-based quick card claims no funnel stage, only sales.
_REASON_SHORT_ORDERS_VI = "Sản phẩm bán chạy theo đơn hàng"

#: D61: the card's GMV line is a plain sentence; Juli's formula, window and rules stay internal.
_GMV_SENTENCE_VI = (
    "Juli ước tính GMV có thể lấy lại từ lượt hiển thị, CTR, CTOR "
    "và giá trị đơn hiện tại của sản phẩm"
)
_GMV_METHOD_VI: Mapping[str, str] = {
    key: _GMV_SENTENCE_VI for key in ("ctr", "ctor", "aov", "impressions")
}


@dataclass
class CardContext:
    """What the database knows about one card beyond its payload."""

    product: Product | None = None
    seller_skus: list[str] = field(default_factory=list)
    sku_count: int = 0
    latest_run: WorkflowRun | None = None
    writes: list[RunWriteValue] = field(default_factory=list)
    #: P30 (D34.8): the seller sentence of the card's group key, once measured.
    group_result: str | None = None


def _product_uuid(card: ActionCard) -> uuid.UUID | None:
    from juli_backend.services.action_cards.subjects import card_product_uuid

    return card_product_uuid(card)


async def load_card_contexts(
    session: AsyncSession, shop_id: uuid.UUID, cards: Iterable[ActionCard]
) -> dict[uuid.UUID, CardContext]:
    """One context per card, read in two shop-scoped queries (P69; was four).

    Each product with its SKUs (one outer join), and each card's runs with their
    recorded writes (one outer join): ~197 ms per round trip in production.
    """
    cards = list(cards)
    contexts = {card.id: CardContext() for card in cards}
    product_ids = {pid for card in cards if (pid := _product_uuid(card)) is not None}
    products: dict[uuid.UUID, Product] = {}
    skus: dict[str, list[InventoryItem]] = defaultdict(list)
    if product_ids:
        product_rows = await session.execute(
            select(Product, InventoryItem)
            .outerjoin(
                InventoryItem,
                and_(
                    InventoryItem.shop_id == shop_id,
                    InventoryItem.tiktok_product_id == Product.tiktok_product_id,
                ),
            )
            .where(Product.shop_id == shop_id, Product.id.in_(product_ids))
            .order_by(InventoryItem.tiktok_sku_id.asc())
        )
        seen_items: set[uuid.UUID] = set()
        for product, item in product_rows.all():
            products[product.id] = product
            # Two products sharing a TikTok id join the same SKUs twice; keep one.
            if item is not None and item.id not in seen_items:
                seen_items.add(item.id)
                skus[item.tiktok_product_id].append(item)
    card_ids = [card.id for card in cards]
    latest_runs: dict[uuid.UUID, WorkflowRun] = {}
    run_writes: dict[uuid.UUID, list[RunWriteValue]] = defaultdict(list)
    if card_ids:
        run_rows = await session.execute(
            select(WorkflowRun, RunWriteValue)
            .outerjoin(
                RunWriteValue,
                and_(
                    RunWriteValue.shop_id == shop_id,
                    RunWriteValue.workflow_run_id == WorkflowRun.id,
                ),
            )
            .where(
                WorkflowRun.shop_id == shop_id,
                WorkflowRun.action_card_id.in_(card_ids),
                WorkflowRun.reverts_run_id.is_(None),
            )
            .order_by(
                WorkflowRun.created_at.asc(),
                WorkflowRun.id.asc(),
                RunWriteValue.recorded_at.asc(),
                RunWriteValue.id.asc(),
            )
        )
        for run, write in run_rows.all():
            if run.action_card_id is not None:
                latest_runs[run.action_card_id] = run
            if write is not None:
                run_writes[run.id].append(write)
    writes = {run.id: run_writes.get(run.id, []) for run in latest_runs.values()}
    sentences = await _group_sentences(session, shop_id, cards)
    for card in cards:
        context = contexts[card.id]
        context.group_result = sentences.get(card.id)
        pid = _product_uuid(card)
        context.product = products.get(pid) if pid is not None else None
        if context.product is not None:
            items = skus.get(context.product.tiktok_product_id, [])
            context.seller_skus = [
                sku for i in items if (sku := i.seller_sku) and is_seller_visible_sku(sku)
            ]
            # Every variant counts toward "+N" (a SKU without a seller code is still a
            # variant); only Juli's own internal SKUs are left out (P69).
            context.sku_count = sum(
                1 for i in items if not i.seller_sku or is_seller_visible_sku(i.seller_sku)
            )
        context.latest_run = latest_runs.get(card.id)
        if context.latest_run is not None:
            context.writes = writes.get(context.latest_run.id, [])
    return contexts


async def _group_sentences(
    session: AsyncSession, shop_id: uuid.UUID, cards: list[ActionCard]
) -> dict[uuid.UUID, str]:
    """Card id -> its group key's seller sentence (P30, D34.8), when a group was measured.

    One query on ``card_groups`` and only when a card carries a D29 group key.
    """
    from juli_backend.services.action_cards.card_groups import card_group_key, seller_sentences

    keyed = {card.id: info[0].text for card in cards if (info := card_group_key(card))}
    if not keyed:
        return {}
    by_key = await seller_sentences(session, shop_id)
    return {card_id: by_key[key] for card_id, key in keyed.items() if key in by_key}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _fmt(value: float, unit: str) -> str:
    if unit == "vnd":
        return f"{round(value):,}".replace(",", ".") + " ₫"
    return f"{value * 100:.1f}".replace(".", ",") + " %"


#: Quick-scan cards (14 days) say the same; the card's quick-scan line names the window.
_GMV_METHOD_14D_VI: Mapping[str, str] = dict(_GMV_METHOD_VI)


def _quick_scan(diagnosis: Mapping[str, Any]) -> dict[str, Any] | None:
    block = diagnosis.get("quick_scan")
    if not isinstance(block, Mapping):
        return None
    return {
        "label": block.get("label"),
        "confidence": block.get("confidence"),
        "window_days": block.get("window_days"),
        "basis": block.get("basis"),
    }


def _from_orders(diagnosis: Mapping[str, Any]) -> bool:
    """P64 (D73.3): a quick card the sandbox shop's paid orders chose (no funnel stage)."""
    block = diagnosis.get("quick_scan")
    return isinstance(block, Mapping) and block.get("source") == "orders"


def _status(
    card: ActionCard, diagnosis: Mapping[str, Any], context: CardContext, now: datetime
) -> str:
    if card.status == "dismissed":
        return "rejected"
    if card.status in ("withdrawn", "expired"):
        return "expired"
    if card.status in ("approved", "executing"):
        run = context.latest_run
        if run is not None and run.status == "completed" and context.writes:
            # P61-B (D71.2): writes on the sandbox merchant never read as
            # "Đã áp dụng" -- the seller's shop did not change.
            simulated = getattr(run, "write_mode", None) == WRITE_MODE_SIMULATED
            return "simulated" if simulated else "applied"
        return "running"
    since = card.surfaced_at or card.computed_at
    if since is not None:
        aware = since.replace(tzinfo=UTC) if since.tzinfo is None else since
        if now - aware >= timedelta(days=PROPOSAL_VALIDITY_DAYS):
            return "expired"
    product = context.product
    proposed_title = diagnosis.get("product_title")
    # P71: a placeholder ("Unknown") on either side is not a title change.
    if product is not None and known_product_name(_text(proposed_title)) is not None:
        current = known_product_name(product.title, product.name)
        if current is not None and current != proposed_title:
            return "expired"
    return "pending"


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


#: P23: aov in VND, impressions a count, CTR / CTOR ratios.
_KPI_UNITS: Mapping[str, str] = {"aov": "vnd", "impressions": "count"}


#: D32: a KPI read on all channels names the metric alone (not "Thẻ sản phẩm").
_KPI_LABELS_ALL_CHANNELS_VI: Mapping[str, str] = {
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV (SKU)",
    "impressions": "Lượt hiển thị",
}


def _main_kpi_label(key: str, channel: object) -> str:
    """The card's KPI label; D32 names the channel the KPI is measured on.

    A card from before D32 (no ``channel``) keeps its label.
    """
    if channel == "total":
        return _KPI_LABELS_ALL_CHANNELS_VI[key]
    if channel in ("video", "live"):
        return f"{_KPI_LABELS_ALL_CHANNELS_VI[key]} - {'Video' if channel == 'video' else 'LIVE'}"
    return _KPI_LABELS_VI[key]


def _main_kpi(diagnosis: Mapping[str, Any]) -> dict[str, Any]:
    basis = diagnosis.get("recoverable_gmv_basis")
    if isinstance(basis, Mapping) and basis.get("stage_rate") in _KPI_LABELS_VI:
        key = str(basis["stage_rate"])
        return {
            "key": key,
            "label": _main_kpi_label(key, basis.get("channel")),
            "current": _num(basis.get("current_rate")),
            "target": _num(basis.get("reference_rate")),
            "unit": _KPI_UNITS.get(key, "ratio"),
        }
    main = diagnosis.get("main_kpi")
    main = main if isinstance(main, Mapping) else {}
    key = str(main.get("key") or "ctor")
    return {
        "key": key,
        "label": _KPI_LABELS_VI.get(key, UNKNOWN_KPI_LABEL_VI),
        "current": _num(main.get("raw")),
        "target": None,
        "unit": "vnd" if key == "aov" else "ratio",
    }


def _capped_legacy(
    kpi: dict[str, Any], per_day: float | None
) -> tuple[dict[str, Any], float | None]:
    """A pre-D29 card the re-score could not reach: its target never above the 3× cap.

    The GMV estimate is linear in the target, so it shrinks by the same share.
    """
    current, target = kpi.get("current"), kpi.get("target")
    capped = cap_legacy_target(current, target)
    if capped is None or target is None or current is None or capped >= target:
        return kpi, per_day
    if per_day is not None and target > current:
        per_day = per_day * (capped - current) / (target - current)
    return {**kpi, "target": capped}, per_day


def _evidence(diagnosis: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(TikTok's code labels, Juli's local-reading labels), de-duplicated, in order."""
    lever = diagnosis.get("lever")
    entries = lever.get("evidence") if isinstance(lever, Mapping) else None
    tiktok: list[str] = []
    local: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("code"), str):
            continue
        label = diagnosis_label_vi(entry["code"])
        target = tiktok if entry.get("source") == "tiktok" else local
        if label not in target:
            target.append(label)
    return tiktok, local


def _reason_full(
    diagnosis: Mapping[str, Any], kpi: Mapping[str, Any], local: list[str], tiktok: list[str]
) -> str:
    trigger = diagnosis.get("trigger")
    sentence = trigger.get("sentence") if isinstance(trigger, Mapping) else None
    parts = [f"{sentence}." if isinstance(sentence, str) and sentence else ""]
    basis = diagnosis.get("recoverable_gmv_basis")
    current, target = kpi.get("current"), kpi.get("target")
    if current is not None and target is not None:
        against = (
            "mức giữa của các sản phẩm trong shop"
            if isinstance(basis, Mapping) and basis.get("reference") == "shop_median"
            else "mức của chính sản phẩm 4 tuần trước"
        )
        unit = str(kpi.get("unit"))
        parts.append(
            f"{kpi['key'].upper()} hiện tại {_fmt(current, unit)}, mục tiêu {_fmt(target, unit)} "
            f"({against})."
        )
    if tiktok:
        parts.append("TikTok chẩn đoán: " + "; ".join(tiktok) + ".")
    if local:
        parts.append("Juli đánh giá: " + "; ".join(local) + ".")
    lever = diagnosis.get("lever")
    detail = lever.get("detail") if isinstance(lever, Mapping) else None
    if isinstance(detail, str) and detail:
        parts.append(f"Đề xuất: {detail}.")
    return " ".join(p for p in parts if p)


def _stored_proposal(diagnosis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """P64 (D73.3): the card's stored rule-based listing edit as one Trước / Sau pair."""
    stored = diagnosis.get("listing_proposal")
    if not isinstance(stored, Mapping):
        return []
    field_code = str(stored.get("field") or "")
    before, after = stored.get("before"), stored.get("after")
    label = _FIELD_LABELS_VI.get(field_code)
    if label is None or not isinstance(before, str) or not isinstance(after, str) or not after:
        return []
    return [{"field": field_code, "label": label, "before": before, "after": after}]


def _before_after(
    context: CardContext, diagnosis: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    if not context.writes and diagnosis is not None:
        return _stored_proposal(diagnosis)
    merged: dict[str, dict[str, Any]] = {}
    for row in context.writes:
        if row.field not in _FIELD_LABELS_VI:
            continue
        first = merged.get(row.field)
        merged[row.field] = {
            "field": row.field,
            "label": _FIELD_LABELS_VI[row.field],
            "before": first["before"] if first is not None else row.before_value,
            "after": row.after_value,
        }
    return [
        pair
        for pair in merged.values()
        if isinstance(pair["before"], str) and isinstance(pair["after"], str)
    ]


def build_card_block(
    card: ActionCard,
    payload: Mapping[str, Any],
    context: CardContext | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The contract §1 ``card`` block for one ADR-106 card, else ``None``."""
    diagnosis = payload.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        return None
    context = context or CardContext()
    now = now or datetime.now(UTC)
    lever = diagnosis.get("lever")
    lever_code = str(lever.get("code")) if isinstance(lever, Mapping) and lever.get("code") else ""
    lever_label, executor = LEVERS.get(lever_code, (lever_code, "seller_center"))
    stage = diagnosis.get("stage")
    stage_code = stage.get("code") if isinstance(stage, Mapping) else None
    kpi = _main_kpi(diagnosis)
    tiktok, local = _evidence(diagnosis)
    per_day = _num(diagnosis.get("recoverable_gmv_per_day"))
    if not has_d29_kpi(payload):
        kpi, per_day = _capped_legacy(kpi, per_day)
    product = context.product
    title = known_product_name(product.title, product.name) if product is not None else None
    field_code, field_label = _LEVER_FIELDS.get(lever_code, (lever_code, lever_label))
    first_sku = context.seller_skus[0] if context.seller_skus else None
    quick = _quick_scan(diagnosis)
    # P71: never "Unknown" in a seller-facing title -- the synced name, the name the card
    # was made with, else the seller's SKU code.
    product_title = (
        title
        or known_product_name(_text(diagnosis.get("product_title")))
        or (f"SKU {first_sku}" if first_sku else None)
    )
    workflow_label = WORKFLOW_LABEL_VI
    if lever_code == "create_product":
        workflow_label = CREATE_PRODUCT_LABEL_VI
        if product_title:
            product_title = f"Tạo sản phẩm mới từ {short_product_name(product_title)}"
    elif lever_code == "create_promotion":
        workflow_label = CREATE_PROMOTION_LABEL_VI
        if product_title:
            product_title = f"Tạo khuyến mãi giảm giá cho {short_product_name(product_title)}"
    tiktok_product_id = (
        (product.tiktok_product_id if product is not None else None)
        or _text(diagnosis.get("tiktok_product_id"))
        or None
    )
    return {
        "seller_sku": first_sku,
        "seller_sku_more": max(context.sku_count - 1, 0) if first_sku else 0,
        "product_title": product_title,
        # P75c: the card's own product, so the reviewer mask aliases its title by THIS
        # product (a seller SKU code or a title can be shared by several listings).
        "tiktok_product_id": tiktok_product_id,
        "workflow_label": workflow_label,
        "updated_at": _iso(card.computed_at or card.updated_at),
        "status": _status(card, diagnosis, context, now),
        "main_kpi": kpi,
        "expected_gmv_per_month": round(per_day * 30) if per_day is not None else None,
        "reason_short": (
            _REASON_SHORT_ORDERS_VI
            if _from_orders(diagnosis)
            else _REASON_SHORT_VI.get(str(stage_code), "Chỉ số sản phẩm giảm")
        ),
        "reason_full": _reason_full(diagnosis, kpi, local, tiktok),
        "tiktok_codes": tiktok,
        "lever": {"code": lever_code, "label": lever_label, "executor": executor},
        "change_fields": [{"field": field_code, "label": field_label}],
        "before_after": _before_after(context, diagnosis),
        "gmv_method": (
            (_GMV_METHOD_14D_VI if quick else _GMV_METHOD_VI).get(str(kpi["key"]))
            if per_day is not None
            else None
        ),
        "quick_scan": quick,
        "adjusted_by_history": diagnosis.get("adjusted_by_history") is True,
        # P30 (D34.8): "Nhóm 6 sản phẩm đổi ảnh bìa: …" once the group has a verdict.
        "group_result": context.group_result,
    }


__all__ = [
    "LEVERS",
    "PROPOSAL_VALIDITY_DAYS",
    "WORKFLOW_LABEL_VI",
    "CardContext",
    "build_card_block",
    "load_card_contexts",
]
