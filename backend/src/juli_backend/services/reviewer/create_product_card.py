"""The "Tạo sản phẩm" card of the partner reviewer's sandbox shop (fast track P64, D73.3/D73.4).

On Juli's own TikTok Shop SANDBOX shop, the reviewer's Quyết định always holds one active
"Tạo sản phẩm" card while the shop has a synced product: :func:`ensure_create_product_card`
(called by ``GET /v1/demo/decisions`` for a reviewer on the writable sandbox pin only)
stores a real ``action_cards`` row -- workflow ``create_product``, subject the shop's
best-selling synced product, executor ``juli`` -- surfaced like every other card. Approving
it is the seller's own approve (``services/agent/approval``: reviewer + sandbox shop + daily
cap); the run creates the listing on TikTok (``services/agent/tools/catalog_create.py``).

No other shop and no seller ever sees it: the decisions reads exclude the workflow unless
the caller asks for it (``services/demo_decisions/read.py`` ``include_reviewer_cards``).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, Product
from juli_backend.services.agent.playbooks import (
    CREATE_PRODUCT_LEVER,
    CREATE_PRODUCT_WORKFLOW_KEY,
)

logger = logging.getLogger(__name__)

LEVER_LABEL_VI = "Tạo sản phẩm"
STAGE = {"code": "catalog", "label": "Danh mục sản phẩm"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _source_product(session: AsyncSession, shop_id: uuid.UUID) -> Product | None:
    """The shop's best-selling synced product that is not a gift item."""
    from juli_backend.services.optimize_product.eligibility import stored_product_gift_reason

    rows = (
        await session.execute(
            select(Product)
            .where(Product.shop_id == shop_id, Product.tiktok_product_id != "")
            .order_by(Product.units_sold.desc(), Product.revenue.desc(), Product.id)
            .limit(20)
        )
    ).scalars()
    for product in rows:
        if stored_product_gift_reason(product) is None:
            return product
    return None


def card_payload(product: Product) -> dict[str, Any]:
    title = product.title or product.name
    return {
        "workflow_key": CREATE_PRODUCT_WORKFLOW_KEY,
        "diagnosis": {
            "version": "p64-create-product-v1",
            "as_of": _now().date().isoformat(),
            "rank": 1,
            "status": "proposal",
            "status_label": "Đề xuất",
            "stage": STAGE,
            "lever": {
                "code": CREATE_PRODUCT_LEVER,
                "label": LEVER_LABEL_VI,
                "action": "Tạo một sản phẩm mới trên TikTok từ sản phẩm bán chạy nhất",
                "detail": (
                    "Juli chọn danh mục TikTok, soạn tiêu đề và mô tả tiếng Việt, kiểm tra "
                    "điều kiện đăng bán rồi tạo sản phẩm sau khi bạn xác nhận"
                ),
            },
            "main_kpi": {"key": "products", "label": "Sản phẩm trên TikTok", "value": "+1"},
            "trigger": {
                "code": "catalog_extension",
                "gap": 0.0,
                "sentence": f"Mở rộng danh mục từ sản phẩm bán chạy «{title}»",
            },
            "product_title": title,
            "tiktok_product_id": product.tiktok_product_id,
        },
    }


async def ensure_create_product_card(
    session: AsyncSession, shop_id: uuid.UUID
) -> ActionCard | None:
    """The shop's one active "Tạo sản phẩm" card, created when none is active. Flush only.

    The caller has already established that this is a reviewer request on the writable
    sandbox pin; the caller's transaction (the shop's own RLS scope) holds the write.
    """
    active = (
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id,
                    ActionCard.workflow_key == CREATE_PRODUCT_WORKFLOW_KEY,
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
                ActionCard.workflow_key == CREATE_PRODUCT_WORKFLOW_KEY,
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
        workflow_key=CREATE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=subject_id,
        revision=revision + 1,
        priority=0,
        severity="medium",
        title=f"Tạo sản phẩm mới từ «{title}»"[:255],
        description=(
            f"Tạo một sản phẩm mới trên TikTok Shop sandbox từ sản phẩm bán chạy «{title}»: "
            "Juli chọn danh mục, soạn tiêu đề và mô tả, kiểm tra điều kiện đăng bán, "
            "rồi tạo sản phẩm sau khi bạn xác nhận."
        ),
        recommendation_payload=json.dumps(card_payload(product), ensure_ascii=False),
        status="active",
        computed_at=now,
        surfaced_at=now,
    )
    session.add(card)
    await session.flush()
    logger.info(
        "reviewer_create_product_card_created",
        extra={"shop_id": str(shop_id), "card": str(card.id)},
    )
    return card


__all__ = ["LEVER_LABEL_VI", "card_payload", "ensure_create_product_card"]
