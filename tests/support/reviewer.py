"""Partner reviewer fixtures (fast track P32-A, D42).

A reference shop that looks like Fujiwa (brand in the name, TikTok ids, a product
title, a seller SKU, an Optimize Product card on the desk), a second seller's
shop, and real HS256 reviewer / seller tokens -- the gate lives inside
``get_current_user``, so these tests must NOT override it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import forget_cached_reviewer_users
from juli_backend.models.models import ActionCard, InventoryItem, Product, Shop, User
from juli_backend.models.ops import OpsReviewerAccount
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer import create_promotion_card as reviewer_promotion_card
from juli_backend.services.reviewer import pin_cache as reviewer_pin_cache

JWT_SECRET = "reviewer-test-jwt-secret"
SHOP_NAME = "Fujiwa Vietnam Store"
TIKTOK_SHOP_ID = "7494012345678901234"
PRODUCT_TITLE = "Nồi chiên không dầu Fujiwa FJ-AF55 5.5L"
TIKTOK_PRODUCT_ID = "1729384756102938475"
SELLER_SKU = "FJW-AF55-BLK"
TIKTOK_SKU_ID = "1729384756102938999"
#: Strings that must never reach a reviewer.
SECRETS = (
    SHOP_NAME,
    "Fujiwa",
    "fujiwa",
    TIKTOK_SHOP_ID,
    PRODUCT_TITLE,
    TIKTOK_PRODUCT_ID,
    SELLER_SKU,
)


def naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def token(
    user_id: uuid.UUID,
    *,
    platform: str | None = "shopee",
    session_id: str | None = "sess-1",
    email: str = "shopee-review@app-juli.com",
) -> str:
    """A Supabase-shaped HS256 access token; ``platform=None`` → an ordinary user."""
    claims: dict = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "email": email,
        "email_verified": True,
        "app_metadata": {"provider": "email"},
    }
    if platform is not None:
        claims["app_metadata"].update({"juli_role": "reviewer", "juli_platform": platform})
    if session_id is not None:
        claims["session_id"] = session_id
    return pyjwt.encode(claims, JWT_SECRET, algorithm="HS256")


def card_payload(lever: str = "title") -> str:
    return json.dumps(
        {
            "diagnosis": {
                "version": "adr106-v1",
                "as_of": "2026-10-13",
                "rank": 1,
                "status": "weak",
                "status_label": "Yếu",
                "stage": {"code": "card", "label": "Thẻ sản phẩm"},
                "lever": {"code": lever, "label": "Tiêu đề", "action": "Viết lại tiêu đề"},
                "main_kpi": {"key": "ctr", "label": "CTR", "value": "1,2%", "raw": 0.012},
                "trigger": {"code": "below_median", "gap": 0.3, "sentence": "CTR thấp"},
                "recoverable_gmv_per_day": 1250000.0,
                "product_title": PRODUCT_TITLE,
                "tiktok_product_id": TIKTOK_PRODUCT_ID,
            }
        }
    )


@dataclass
class ReferenceShop:
    owner: User
    shop: Shop
    product: Product
    card: ActionCard


async def seed_reference_shop(
    session: AsyncSession, *, name: str = SHOP_NAME, tiktok_shop_id: str = TIKTOK_SHOP_ID,
    title: str = PRODUCT_TITLE, product_id: str = TIKTOK_PRODUCT_ID, seller_sku: str = SELLER_SKU,
) -> ReferenceShop:  # fmt: skip
    owner = User(id=uuid.uuid4(), email=f"owner-{uuid.uuid4().hex[:6]}@gmail.com")
    session.add(owner)
    await session.flush()
    shop = Shop(id=uuid.uuid4(), user_id=owner.id, shop_name=name, tiktok_shop_id=tiktok_shop_id)
    session.add(shop)
    await session.flush()
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=product_id,
        title=title,
        name=title,
        status="ACTIVATE",
        update_time=naive_now(),
        revenue=123456789,
        units_sold=4321,
    )
    session.add(product)
    session.add(
        InventoryItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=product_id,
            tiktok_sku_id=TIKTOK_SKU_ID if product_id == TIKTOK_PRODUCT_ID else product_id + "9",
            quantity=10,
            update_time=naive_now(),
            seller_sku=seller_sku,
        )
    )
    await session.flush()
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        subject_type="product",
        subject_id=str(product.id),
        priority=1,
        severity="medium",
        title=f"Tối ưu tiêu đề: {title}",
        description=f"Sản phẩm {title} ({product_id}) có CTR thấp hơn trung vị của shop.",
        recommendation_payload=card_payload(),
        status="active",
        surfaced_at=naive_now(),
        computed_at=naive_now(),
        revision=1,
    )
    session.add(card)
    await session.flush()
    return ReferenceShop(owner=owner, shop=shop, product=product, card=card)


async def make_reviewer(
    session: AsyncSession,
    *,
    platform: str = "shopee",
    expires_in: timedelta = timedelta(days=30),
    revoked: bool = False,
    email: str = "shopee-review@app-juli.com",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    session.add(
        OpsReviewerAccount(
            id=uuid.uuid4(),
            user_id=user_id,
            email=email,
            role="reviewer",
            platform=platform,
            expires_at=naive_now() + expires_in,
            revoked_at=naive_now() if revoked else None,
            created_by="owner@app-juli.com",
        )
    )
    await session.flush()
    await session.commit()
    return user_id


def reset_caches() -> None:
    reviewer_accounts.forget_cached()
    reviewer_catalog.forget_cached()
    # P69: the reviewer's users row and the pinned shop's facts.
    forget_cached_reviewer_users()
    reviewer_pin_cache.forget_cached()
    reviewer_promotion_card.reset_cache()
