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

**Only for a product TikTok would accept (P66, D16).** Before the card is shown it is
checked with the same TikTok reads the run makes
(``promotion_create.first_promotable_product``: the product is selling, in stock and held
by no running or upcoming price promotion overlapping Juli's default window). A card
whose product no longer qualifies is retired (``expired``) and the next qualifying
product gets it; when none qualifies, or TikTok cannot be read, no new card is emitted.
An active card is re-checked at most every :data:`VERIFY_TTL`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
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


#: P66 (D16): how long an active card's TikTok eligibility check stays good.
VERIFY_TTL = timedelta(minutes=5)
#: P66 (D16): how many of the shop's products are tried for a new card.
MAX_PRODUCTS_TRIED = 5
#: The status a card whose product no longer qualifies is retired with.
RETIRED_STATUS = "expired"

#: card id -> when its product was last confirmed eligible on TikTok.
_verified_at: dict[uuid.UUID, datetime] = {}


def reset_cache() -> None:
    _verified_at.clear()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _promotion_resources(session: AsyncSession, shop_id: uuid.UUID) -> Any:
    """The sandbox shop's TikTok resources the run reads through (a seam for tests)."""
    from juli_backend.services.agent.composition import build_read_resources

    return await build_read_resources(session, shop_id)


async def _first_promotable(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_ids: list[str]
) -> tuple[bool, str | None]:
    """``(verified, first eligible TikTok id)``; ``verified`` is False when TikTok (or the
    shop's credential) could not be read -- nothing is known then."""
    from juli_backend.services.agent.tools.promotion_create import first_promotable_product

    if not tiktok_ids:
        return True, None
    try:
        resources = await _promotion_resources(session, shop_id)
        found = await asyncio.to_thread(first_promotable_product, resources, tiktok_ids)
    except Exception:
        # Any failure to read (credential, TikTok, network): unknown, never "eligible".
        logger.warning(
            "reviewer_promotion_card_unverified", extra={"shop_id": str(shop_id)}, exc_info=True
        )
        return False, None
    return True, found


async def _source_products(session: AsyncSession, shop_id: uuid.UUID) -> list[Product]:
    """The shop's best-selling synced, non-gift products -- those with synced stock first.

    Stock is what Juli synced (``inventory_items`` / ``products.inventory``); TikTok
    decides (:func:`_first_promotable`) and the run re-reads it before proposing anything.
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
    with_stock = [p for p in products if p.tiktok_product_id in stocked or (p.inventory or 0) > 0]
    rest = [p for p in products if p not in with_stock]
    return (with_stock + rest)[:MAX_PRODUCTS_TRIED]


async def _active_card_still_eligible(session: AsyncSession, card: ActionCard) -> bool:
    """Whether the active card's product still qualifies (re-read at most every
    :data:`VERIFY_TTL`). Unknown (TikTok unread) keeps the card: it is not retired on a
    guess, and the run re-checks before proposing anything."""
    checked = _verified_at.get(card.id)
    if checked is not None and _now() - checked < VERIFY_TTL:
        return True
    try:
        tiktok_id = json.loads(card.recommendation_payload or "{}")["diagnosis"][
            "tiktok_product_id"
        ]
    except (ValueError, KeyError, TypeError):
        tiktok_id = None
    if not tiktok_id:
        return True
    verified, found = await _first_promotable(session, card.shop_id, [str(tiktok_id)])
    if not verified:
        return True
    if found is None:
        return False
    _verified_at[card.id] = _now()
    return True


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
        if await _active_card_still_eligible(session, active):
            return active
        # P66 (D16): its product is now in a price promotion (or out of stock).
        active.status = RETIRED_STATUS
        _verified_at.pop(active.id, None)
        await session.flush()
        logger.info(
            "reviewer_create_promotion_card_retired",
            extra={"shop_id": str(shop_id), "card": str(active.id)},
        )
    products = await _source_products(session, shop_id)
    verified, found = await _first_promotable(
        session, shop_id, [p.tiktok_product_id for p in products]
    )
    product = next((p for p in products if p.tiktok_product_id == found), None)
    if product is None:
        # P66 (D16): no product a new price promotion can be created for (or TikTok
        # could not tell): no card, rather than one the run can only decline.
        logger.info(
            "reviewer_create_promotion_card_not_emitted",
            extra={"shop_id": str(shop_id), "verified": verified},
        )
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
    _verified_at[card.id] = _now()
    logger.info(
        "reviewer_create_promotion_card_created",
        extra={"shop_id": str(shop_id), "card": str(card.id)},
    )
    return card


__all__ = [
    "LEVER_LABEL_VI",
    "card_payload",
    "card_title",
    "ensure_create_promotion_card",
    "reset_cache",
]
