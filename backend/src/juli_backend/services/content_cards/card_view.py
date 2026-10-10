"""The ``recommendation.card`` block of a content card (contract ``p14-content-cards.md`` §1).

Same shape as P10's card (``demo_decisions.card_view``) plus ``content``; built
at read time from the stored payload and what only the database knows now
(seller SKUs, the card's status, its latest run).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from juli_backend.models.models import ActionCard
from juli_backend.services.content_cards.constants import (
    CHIP_VI,
    EXECUTOR_JULI_DRAFTS,
    SPEC_BY_WORKFLOW,
)
from juli_backend.services.content_cards.emission import card_expired


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


def _status(card: ActionCard, context: Any, now: datetime) -> str:
    if card.status == "dismissed":
        return "rejected"
    if card.status == "withdrawn":
        return "expired"
    if card.status in ("approved", "executing"):
        run = getattr(context, "latest_run", None)
        if run is not None and run.status == "completed" and run.stop_reason == "final_response":
            return "applied"
        return "running"
    if card_expired(card, now=now):
        return "expired"
    return "pending"


def build_content_card_block(
    card: ActionCard,
    payload: Mapping[str, Any],
    context: Any | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The contract §1 ``card`` block for one content card, else ``None``."""
    content = payload.get("content")
    spec = SPEC_BY_WORKFLOW.get(card.workflow_key)
    if not isinstance(content, Mapping) or spec is None:
        return None
    now = now or datetime.now(UTC)
    product = getattr(context, "product", None)
    seller_skus = list(getattr(context, "seller_skus", []) or [])
    sku_count = int(getattr(context, "sku_count", 0) or 0)
    first_sku = seller_skus[0] if seller_skus else None
    title = (product.title or product.name) if product is not None else None
    per_day = _num(content.get("recoverable_gmv_per_day"))
    will = content.get("will_draft")
    return {
        "seller_sku": first_sku,
        "seller_sku_more": max(sku_count - 1, 0) if first_sku else 0,
        "product_title": title or content.get("product_title"),
        "workflow_label": spec.workflow_label,
        "updated_at": _iso(card.computed_at or card.updated_at),
        "status": _status(card, context, now),
        "main_kpi": {
            "key": spec.kpi_key,
            "label": spec.kpi_label,
            "current": _num(content.get("current")),
            "target": _num(content.get("target")),
            "unit": "ratio",
        },
        "expected_gmv_per_month": round(per_day * 30) if per_day is not None else None,
        "reason_short": str(content.get("reason_short") or spec.reason_short),
        "reason_full": str(content.get("reason_full") or ""),
        "tiktok_codes": [],
        "lever": {
            "code": spec.lever_code,
            "label": spec.action_label,
            "executor": EXECUTOR_JULI_DRAFTS,
        },
        "change_fields": [{"field": spec.lever_code, "label": spec.action_label}],
        "before_after": [],
        "gmv_method": spec.gmv_method if per_day is not None else None,
        "content": {
            "kind": spec.kind,
            "action_label": spec.action_label,
            "chip": CHIP_VI,
            "will_draft": [str(line) for line in will] if isinstance(will, list) else [],
            "measure": str(content.get("measure") or ""),
        },
    }


__all__ = ["build_content_card_block"]
