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
  KPI, no target.
- ``tiktok_codes``: labels of diagnosis codes TikTok itself returned. Juli's
  local reading of the same codes is named in ``reason_full`` as "Juli đánh
  giá", never as TikTok's (OP-NFR-2).
- ``before_after``: only complete pairs -- the latest run's recorded writes
  (``run_write_values``). A pending card's "after" does not exist yet (Juli
  drafts it in the run), so it has none.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, InventoryItem, Product, WorkflowRun
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.agent.tools.diagnosis_labels import diagnosis_label_vi

WORKFLOW_LABEL_VI = "Tối ưu sản phẩm"
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
}

#: The listing field each Juli-executed lever changes.
_LEVER_FIELDS: Mapping[str, tuple[str, str]] = {
    "cover_image": ("main_images", "Ảnh bìa"),
    "title": ("title", "Tiêu đề"),
    "description": ("description", "Mô tả"),
}

_FIELD_LABELS_VI: Mapping[str, str] = {"title": "Tiêu đề", "description": "Mô tả"}

_KPI_LABELS_VI: Mapping[str, str] = {
    "ctr": "CTR - Thẻ sản phẩm",
    "ctor": "CTOR - Thẻ sản phẩm",
    "aov": "AOV (SKU)",
}

#: ≤ 6 words, by the stage the diagnosis found weak.
_REASON_SHORT_VI: Mapping[str, str] = {
    "card": "Ít người bấm vào sản phẩm",
    "page": "Khách xem nhưng ít đặt hàng",
    "basket": "Mỗi đơn mua ít món",
}

_GMV_METHOD_VI: Mapping[str, str] = {
    "ctr": (
        "lượt hiển thị × (CTR mục tiêu − CTR hiện tại) × CTOR × AOV, "
        "trung bình 30 ngày, ước tính theo quy tắc"
    ),
    "ctor": (
        "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, "
        "trung bình 30 ngày, ước tính theo quy tắc"
    ),
    "aov": (
        "đơn hàng SKU × (AOV mục tiêu − AOV hiện tại), trung bình 30 ngày, ước tính theo quy tắc"
    ),
}


@dataclass
class CardContext:
    """What the database knows about one card beyond its payload."""

    product: Product | None = None
    seller_skus: list[str] = field(default_factory=list)
    sku_count: int = 0
    latest_run: WorkflowRun | None = None
    writes: list[RunWriteValue] = field(default_factory=list)


def _product_uuid(card: ActionCard) -> uuid.UUID | None:
    if card.subject_type != "product" or not card.subject_id:
        return None
    try:
        return uuid.UUID(card.subject_id)
    except ValueError:
        return None


async def load_card_contexts(
    session: AsyncSession, shop_id: uuid.UUID, cards: Iterable[ActionCard]
) -> dict[uuid.UUID, CardContext]:
    """One context per card, read in four shop-scoped queries."""
    cards = list(cards)
    contexts = {card.id: CardContext() for card in cards}
    product_ids = {pid for card in cards if (pid := _product_uuid(card)) is not None}
    products: dict[uuid.UUID, Product] = {}
    if product_ids:
        product_rows = await session.execute(
            select(Product).where(Product.shop_id == shop_id, Product.id.in_(product_ids))
        )
        products = {p.id: p for p in product_rows.scalars()}
    skus: dict[str, list[InventoryItem]] = defaultdict(list)
    tiktok_ids = {p.tiktok_product_id for p in products.values()}
    if tiktok_ids:
        sku_rows = await session.execute(
            select(InventoryItem)
            .where(
                InventoryItem.shop_id == shop_id,
                InventoryItem.tiktok_product_id.in_(tiktok_ids),
            )
            .order_by(InventoryItem.tiktok_sku_id.asc())
        )
        for item in sku_rows.scalars():
            skus[item.tiktok_product_id].append(item)
    card_ids = [card.id for card in cards]
    latest_runs: dict[uuid.UUID, WorkflowRun] = {}
    if card_ids:
        run_rows = await session.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.shop_id == shop_id,
                WorkflowRun.action_card_id.in_(card_ids),
                WorkflowRun.reverts_run_id.is_(None),
            )
            .order_by(WorkflowRun.created_at.asc())
        )
        for run in run_rows.scalars():
            if run.action_card_id is not None:
                latest_runs[run.action_card_id] = run
    writes: dict[uuid.UUID, list[RunWriteValue]] = defaultdict(list)
    run_ids = [run.id for run in latest_runs.values()]
    if run_ids:
        write_rows = await session.execute(
            select(RunWriteValue)
            .where(RunWriteValue.shop_id == shop_id, RunWriteValue.workflow_run_id.in_(run_ids))
            .order_by(RunWriteValue.recorded_at.asc(), RunWriteValue.id.asc())
        )
        for row in write_rows.scalars():
            writes[row.workflow_run_id].append(row)
    for card in cards:
        context = contexts[card.id]
        pid = _product_uuid(card)
        context.product = products.get(pid) if pid is not None else None
        if context.product is not None:
            items = skus.get(context.product.tiktok_product_id, [])
            context.sku_count = len(items)
            context.seller_skus = [i.seller_sku for i in items if i.seller_sku]
        context.latest_run = latest_runs.get(card.id)
        if context.latest_run is not None:
            context.writes = writes.get(context.latest_run.id, [])
    return contexts


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
            return "applied"
        return "running"
    since = card.surfaced_at or card.computed_at
    if since is not None:
        aware = since.replace(tzinfo=UTC) if since.tzinfo is None else since
        if now - aware >= timedelta(days=PROPOSAL_VALIDITY_DAYS):
            return "expired"
    product = context.product
    proposed_title = diagnosis.get("product_title")
    if product is not None and isinstance(proposed_title, str) and proposed_title:
        if (product.title or product.name) != proposed_title:
            return "expired"
    return "pending"


def _main_kpi(diagnosis: Mapping[str, Any]) -> dict[str, Any]:
    basis = diagnosis.get("recoverable_gmv_basis")
    if isinstance(basis, Mapping) and basis.get("stage_rate") in _KPI_LABELS_VI:
        key = str(basis["stage_rate"])
        return {
            "key": key,
            "label": _KPI_LABELS_VI[key],
            "current": _num(basis.get("current_rate")),
            "target": _num(basis.get("reference_rate")),
            "unit": "vnd" if key == "aov" else "ratio",
        }
    main = diagnosis.get("main_kpi")
    main = main if isinstance(main, Mapping) else {}
    key = str(main.get("key") or "ctor")
    return {
        "key": key,
        "label": _KPI_LABELS_VI.get(key, key.upper()),
        "current": _num(main.get("raw")),
        "target": None,
        "unit": "vnd" if key == "aov" else "ratio",
    }


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


def _before_after(context: CardContext) -> list[dict[str, Any]]:
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
    product = context.product
    title = (product.title or product.name) if product is not None else None
    field_code, field_label = _LEVER_FIELDS.get(lever_code, (lever_code, lever_label))
    first_sku = context.seller_skus[0] if context.seller_skus else None
    return {
        "seller_sku": first_sku,
        "seller_sku_more": max(context.sku_count - 1, 0) if first_sku else 0,
        "product_title": title or diagnosis.get("product_title"),
        "workflow_label": WORKFLOW_LABEL_VI,
        "updated_at": _iso(card.computed_at or card.updated_at),
        "status": _status(card, diagnosis, context, now),
        "main_kpi": kpi,
        "expected_gmv_per_month": round(per_day * 30) if per_day is not None else None,
        "reason_short": _REASON_SHORT_VI.get(str(stage_code), "Chỉ số sản phẩm giảm"),
        "reason_full": _reason_full(diagnosis, kpi, local, tiktok),
        "tiktok_codes": tiktok,
        "lever": {"code": lever_code, "label": lever_label, "executor": executor},
        "change_fields": [{"field": field_code, "label": field_label}],
        "before_after": _before_after(context),
        "gmv_method": _GMV_METHOD_VI.get(str(kpi["key"])) if per_day is not None else None,
        "adjusted_by_history": diagnosis.get("adjusted_by_history") is True,
    }


__all__ = [
    "LEVERS",
    "PROPOSAL_VALIDITY_DAYS",
    "WORKFLOW_LABEL_VI",
    "CardContext",
    "build_card_block",
    "load_card_contexts",
]
