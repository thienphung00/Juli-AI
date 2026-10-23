"""The "Tạo khuyến mãi" card of the partner reviewer's sandbox shop (fast track P65, D74).

On Juli's own TikTok Shop SANDBOX shop, the reviewer's Quyết định holds one active
"Tạo khuyến mãi giảm giá" card while the shop has a synced product:
:func:`ensure_create_promotion_card` (called by ``GET /v1/demo/decisions`` for a reviewer
on the writable sandbox pin only) stores a real ``action_cards`` row -- workflow
``create_promotion``, subject the shop's best-selling product (synced stock first),
executor ``juli``.
Approving it is the seller's own approve (``services/agent/approval``: reviewer +
sandbox shop + daily cap); the run creates the discount on TikTok
(``services/agent/tools/promotion_create.py``).

No other shop and no seller ever sees it: the decisions reads exclude the workflow unless
the caller asks for it (``services/demo_decisions/read.py`` ``include_reviewer_cards``).
The card claims no ROI: the sandbox has no real buyers.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.services.agent.playbooks import (
    CREATE_PROMOTION_LEVER,
    CREATE_PROMOTION_WORKFLOW_KEY,
)

logger = logging.getLogger(__name__)

LEVER_LABEL_VI = "Tạo khuyến mãi"
STAGE = {"code": "promotion", "label": "Khuyến mãi"}


def card_title(title: str) -> str:
    return f"Tạo khuyến mãi giảm giá cho «{title}»"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _source_product(session: AsyncSession, shop_id: uuid.UUID) -> Product | None:
    """The shop's best-selling synced, non-gift product -- one with synced stock first.

    Stock is what Juli synced (``inventory_items`` / ``products.inventory``); the run
    re-reads it from TikTok before proposing anything.
    """
    from juli_backend.services.optimize_product.eligibility import stored_product_gift_reason

    rows = (
        await session.execute(
            select(Product)
            .where(Product.shop_id == shop_id, Product.tiktok_product_id != "")
            .order_by(Product.units_sold.desc(), Product.revenue.desc(), Product.id)
            .limit(20)
        )
    ).scalars()
    products = [p for p in rows if stored_product_gift_reason(p) is None]
    stocked = set(
        (
            await session.execute(
                select(InventoryItem.tiktok_product_id).where(
                    InventoryItem.shop_id == shop_id, InventoryItem.quantity > 0
                )
            )
        ).scalars()
    )
    for product in products:
        if product.tiktok_product_id in stocked or (product.inventory or 0) > 0:
            return product
    return products[0] if products else None


def card_payload(product: Product) -> dict[str, Any]:
    title = product.title or product.name
    return {
        "workflow_key": CREATE_PROMOTION_WORKFLOW_KEY,
        "diagnosis": {
            "version": "p65-create-promotion-v1",
            "as_of": _now().date().isoformat(),
            "rank": 1,
            "status": "proposal",
            "status_label": "Đề xuất",
            "stage": STAGE,
            "lever": {
                "code": CREATE_PROMOTION_LEVER,
                "label": LEVER_LABEL_VI,
                "action": "Tạo một khuyến mãi giảm giá sản phẩm trên TikTok",
                "detail": (
                    "Juli chọn sản phẩm còn hàng, mức giảm trong quy tắc của shop và ngày kết "
                    "thúc, kiểm tra điều kiện rồi tạo khuyến mãi sau khi bạn xác nhận. Shop "
                    "sandbox không có người mua thật nên Juli không đo hiệu quả"
                ),
            },
            "main_kpi": {"key": "promotion", "label": "Khuyến mãi trên TikTok", "value": "+1"},
            "trigger": {
                "code": "promotion_demo",
                "gap": 0.0,
                "sentence": f"Tạo khuyến mãi giảm giá cho sản phẩm bán chạy «{title}»",
            },
            "product_title": title,
            "tiktok_product_id": product.tiktok_product_id,
        },
    }


async def ensure_create_promotion_card(
    session: AsyncSession, shop_id: uuid.UUID
) -> ActionCard | None:
    """The shop's one active "Tạo khuyến mãi" card, created when none is active. Flush only.

    The caller has already established that this is a reviewer request on the writable
    sandbox pin; the caller's transaction (the shop's own RLS scope) holds the write.
    """
    active = (
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id,
                    ActionCard.workflow_key == CREATE_PROMOTION_WORKFLOW_KEY,
                    ActionCard.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    product = await _source_product(session, shop_id)
    if product is None:
        return None
    subject_id = str(product.id)
    revision = (
        await session.execute(
            select(func.max(ActionCard.revision)).where(
                ActionCard.shop_id == shop_id,
                ActionCard.workflow_key == CREATE_PROMOTION_WORKFLOW_KEY,
                ActionCard.subject_type == "product",
                ActionCard.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none() or 0
    now = datetime.now(UTC)  # computed_at / surfaced_at are timestamptz
    title = product.title or product.name
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=CREATE_PROMOTION_WORKFLOW_KEY,
        subject_type="product",
        subject_id=subject_id,
        revision=revision + 1,
        priority=0,
        severity="medium",
        title=card_title(title)[:255],
        description=(
            f"Tạo một khuyến mãi giảm giá trên TikTok Shop sandbox cho «{title}»: Juli chọn "
            "sản phẩm còn hàng, mức giảm trong quy tắc của shop và ngày kết thúc, kiểm tra "
            "điều kiện, rồi tạo khuyến mãi sau khi bạn xác nhận. Shop sandbox không có người "
            "mua thật nên Juli không đo hiệu quả."
        ),
        recommendation_payload=json.dumps(card_payload(product), ensure_ascii=False),
        status="active",
        computed_at=now,
        surfaced_at=now,
    )
    session.add(card)
    await session.flush()
    logger.info(
        "reviewer_create_promotion_card_created",
        extra={"shop_id": str(shop_id), "card": str(card.id)},
    )
    return card


__all__ = ["LEVER_LABEL_VI", "card_payload", "card_title", "ensure_create_promotion_card"]
