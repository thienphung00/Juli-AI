"""The contract 7 worked example as a shop (P90 step 8 acceptance through the API).

One product, one SKU (list 200.000đ, giá vốn 100.000, đóng gói 3.000), thirty orders of one
unit at 200.000đ -- one per day for thirty days -- no voucher, and a platform fee formula of
15 % of what the buyer pays. A voucher of 15.000đ against today's 10.000đ at a minimum spend of
200.000đ costs 150.000đ more over the thirty days; each order earns 54.250đ (29,3 %) under it;
break-even is ceil(150.000 / 54.250) = 3 extra orders. All figures are the contract's.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shopee_profit import PlatformFeeFormula, PlatformItemSnapshot
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import NOW, Seeded, _line, _src
from tests.support.shopee_reco import rule

AS_OF = date(2026, 10, 30)
ITEM = "9001"
SKU = "S1"


async def seed_worked_example(session: AsyncSession) -> Seeded:
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee", shop_name="Worked Example Shop")
    sid = shop.id
    session.add(
        PlatformItem(
            shop_id=sid,
            item_id=ITEM,
            variation_id="",
            name="Sản phẩm mẫu",
            seller_sku=SKU,
            status="Đang hoạt động",
            extra={},
            **_src(),
        )
    )
    session.add(
        PlatformFeeFormula(
            id=uuid.uuid4(),
            platform="shopee",
            category_path=[],
            effective_from=date(2026, 1, 1),
            components=[
                {"code": "commission", "kind": "pct", "base": "buyer_paid", "rate": "0.15"}
            ],
        )
    )
    lines = [
        _line(
            sid,
            n + 1,
            AS_OF - timedelta(days=29 - n),
            SKU,
            original=200_000,
            deal=200_000,
            promo_kind="none",
            fees=None,
        )
        for n in range(30)
    ]
    session.add_all(lines)
    for n in range(30):
        day = AS_OF - timedelta(days=29 - n)
        session.add(
            PlatformDailyMetric(
                shop_id=sid,
                dataset="shop_overview",
                day=day,
                item_id="",
                stream="total",
                segment="all",
                order_type="confirmed",
                orders=Decimal(1),
                gmv=Decimal(200_000),
                extra={},
                confidence="high",
                **_src(),
            )
        )
    session.add(rule(sid, "sku_cost", SKU, 100_000))
    session.add(rule(sid, "packaging_cost", SKU, 3_000))
    session.add(rule(sid, "min_margin_pct", "", 10))
    session.add(rule(sid, "daily_marketing_cap", "", 5_000_000))
    session.add(
        PlatformItemSnapshot(
            shop_id=sid,
            platform="shopee",
            item_id=ITEM,
            variation_id="",
            captured_at=datetime(2026, 10, 30, 12, 0),
            title="Sản phẩm mẫu",
            image_urls=[],
            image_hashes=[],
            list_price=Decimal(200_000),
            current_price=Decimal(200_000),
            stock=500,
            rating=Decimal("4.8"),
            rating_count=10,
            category_path=["Danh mục mẫu"],
            status="Đang hoạt động",
            source="extension",
            source_rank=1,
        )
    )
    await session.flush()
    return Seeded(sid, user, shop, {ln.order_ref for ln in lines}, lines)


__all__ = ["AS_OF", "ITEM", "NOW", "SKU", "seed_worked_example"]
