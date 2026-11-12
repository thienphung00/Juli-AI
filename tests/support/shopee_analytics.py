"""A synthetic Shopee shop for the analytics read APIs (P90 step 7).

Three products, two windows of seven days (``CUR`` = 2026-10-01..07, ``PREV`` = the seven
days before it), order lines (delivered, paid-then-cancelled, never paid; shop voucher, programme
discount, combo, none; actual fees on some, none on others), the shop's daily Doanh số, the
daily traffic rows whose five flows add up to the shop GMV minus a fixed 5.000đ per day (so the
"Chênh lệch nguồn" row is exercised), ads (daily + a group campaign with its products), vouchers,
an item-by-source period and product period rows. Every figure is invented.

The order refs are 32-hex strings made here; the tests assert none of them ever reaches a
response.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import (
    PlatformItem,
    PlatformPeriodMetric,
    PlatformPromotion,
)
from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.models.shopee_profit import PlatformItemSnapshot, ShopeeOrderLine
from tests.support.builders import make_shop, make_user

CUR_START, CUR_END = date(2026, 10, 1), date(2026, 10, 7)
PREV_START, PREV_END = date(2026, 9, 24), date(2026, 9, 30)
NOW = datetime(2026, 10, 8, 3, 0)
DAILY_SHOP_GMV = Decimal(275_000)
DAILY_FLOW_GMV = Decimal(270_000)  # card 170k + trang shop 30k + video 20k + lien ket 50k
ITEMS = {
    "1001": ("Găng tay tự hủy sinh học STAHAUS", "G1"),
    "1002": ("Nước rửa chén Ory 500ml", "N1"),
    "1003": ("Túi rác tự hủy sinh học", "T1"),
}


@dataclass
class Seeded:
    shop_id: uuid.UUID
    user: Any
    shop: Any
    order_refs: set[str] = field(default_factory=set)
    lines: list[ShopeeOrderLine] = field(default_factory=list)


def _ref(n: int) -> str:
    return f"{n:032x}"


def _src(**values: Any) -> dict[str, Any]:
    return {
        "platform": "shopee",
        "source": "file",
        "source_rank": 1,
        "source_version": "test",
        "captured_at": NOW,
        "updated_at": NOW,
        **values,
    }


def _line(
    shop_id: uuid.UUID,
    n: int,
    day: date,
    sku: str,
    *,
    qty: int = 1,
    original: int = 100_000,
    deal: int = 90_000,
    voucher: int = 0,
    bundle: int = 0,
    status: str = "delivered",
    paid: bool = True,
    promo_kind: str = "discount",
    fees: tuple[int, int, int] | None = (13_500, 0, 5_400),
    affiliate: bool = False,
    commission: int | None = None,
    sku_only: bool = True,
) -> ShopeeOrderLine:
    when = datetime.combine(day, datetime.min.time()).replace(hour=10, minute=n % 50)
    return ShopeeOrderLine(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        order_ref=_ref(n),
        line_no=0,
        ordered_at=when,
        status=status,
        item_id=f"sku:{sku}" if sku_only else sku,
        variation_id="",
        qty=qty,
        original_price=Decimal(original),
        deal_price=Decimal(deal),
        shop_voucher_share=Decimal(voucher),
        bundle_discount=Decimal(bundle),
        promo_kind=promo_kind,
        affiliate=affiliate,
        commission=None if commission is None else Decimal(commission),
        fee_fixed=None if fees is None else Decimal(fees[0]),
        fee_service=None if fees is None else Decimal(fees[1]),
        fee_payment=None if fees is None else Decimal(fees[2]),
        source="file",
        source_version="test",
        sku=sku,
        variation_sku=None,
        paid_at=when if paid else None,
    )


def order_lines(shop_id: uuid.UUID) -> list[ShopeeOrderLine]:
    """Current window (n 1..14) and previous window (n 101..106)."""
    days = [CUR_START + timedelta(days=i) for i in range(7)]
    out = [
        _line(shop_id, 1, days[0], "G1", qty=2, deal=90_000, voucher=2_000),
        _line(shop_id, 2, days[0], "N1", original=60_000, deal=54_000),
        _line(shop_id, 3, days[1], "G1", deal=100_000, promo_kind="none"),
        _line(shop_id, 4, days[1], "T1", original=50_000, deal=45_000, fees=None),
        _line(shop_id, 5, days[2], "N1", original=60_000, deal=54_000, voucher=1_000),
        _line(shop_id, 6, days[2], "G1", deal=90_000, bundle=5_000),
        _line(shop_id, 7, days[3], "G1", qty=3, deal=85_000, affiliate=True, commission=8_000),
        _line(shop_id, 8, days[3], "T1", original=50_000, deal=45_000),
        _line(shop_id, 9, days[4], "N1", original=60_000, deal=54_000, status="cancelled"),
        _line(shop_id, 10, days[4], "G1", status="cancelled", paid=False),
        _line(shop_id, 11, days[5], "G1", deal=90_000),
        _line(shop_id, 12, days[5], "N1", original=60_000, deal=54_000, fees=None),
        _line(shop_id, 13, days[6], "G1", deal=90_000, voucher=2_000),
        _line(shop_id, 14, days[6], "T1", original=50_000, deal=45_000),
    ]
    prev = [PREV_START + timedelta(days=i) for i in range(7)]
    out += [
        _line(shop_id, 101, prev[0], "G1", deal=95_000),
        _line(shop_id, 102, prev[2], "N1", original=60_000, deal=57_000),
        _line(shop_id, 103, prev[3], "G1", deal=95_000),
        _line(shop_id, 104, prev[4], "T1", original=50_000, deal=48_000),
        _line(shop_id, 105, prev[5], "G1", deal=95_000),
        _line(shop_id, 106, prev[6], "N1", original=60_000, deal=57_000),
    ]
    return out


def _daily(
    shop_id: uuid.UUID,
    day: date,
    stream: str,
    segment: str,
    *,
    impressions: int | None = None,
    clicks: int | None = None,
    orders: int = 0,
    gmv: int = 0,
    dataset: str = "traffic_overview",
    order_type: str = "confirmed",
    extra: dict[str, Any] | None = None,
    item_id: str = "",
) -> PlatformDailyMetric:
    return PlatformDailyMetric(
        shop_id=shop_id,
        dataset=dataset,
        day=day,
        item_id=item_id,
        stream=stream,
        segment=segment,
        order_type=order_type,
        impressions=None if impressions is None else Decimal(impressions),
        clicks=None if clicks is None else Decimal(clicks),
        orders=Decimal(orders),
        gmv=Decimal(gmv),
        extra=extra or {},
        confidence="high",
        **_src(),
    )


def daily_rows(shop_id: uuid.UUID) -> list[PlatformDailyMetric]:
    rows: list[PlatformDailyMetric] = []
    for window_start in (CUR_START, PREV_START):
        for i in range(7):
            day = window_start + timedelta(days=i)
            rows += [
                _daily(
                    shop_id,
                    day,
                    "total",
                    "all",
                    orders=5,
                    gmv=int(DAILY_SHOP_GMV),
                    dataset="shop_overview",
                ),
                _daily(
                    shop_id,
                    day,
                    "product_card",
                    "all",
                    impressions=1000,
                    clicks=50,
                    orders=3,
                    gmv=200_000,
                ),
                _daily(
                    shop_id,
                    day,
                    "product_card",
                    "shop_page",
                    impressions=100,
                    clicks=10,
                    orders=1,
                    gmv=30_000,
                ),
                _daily(
                    shop_id,
                    day,
                    "product_card",
                    "search",
                    impressions=600,
                    clicks=30,
                    orders=1,
                    gmv=90_000,
                ),
                _daily(
                    shop_id,
                    day,
                    "product_card",
                    "recommend",
                    impressions=300,
                    clicks=10,
                    orders=1,
                    gmv=80_000,
                ),
                _daily(
                    shop_id, day, "product_card", "cart", impressions=0, clicks=0, orders=0, gmv=0
                ),
                _daily(
                    shop_id,
                    day,
                    "seller_video",
                    "all",
                    impressions=40,
                    clicks=8,
                    orders=1,
                    gmv=20_000,
                ),
                _daily(
                    shop_id,
                    day,
                    "affiliate",
                    "all",
                    impressions=60,
                    clicks=12,
                    orders=1,
                    gmv=50_000,
                ),
                _daily(
                    shop_id,
                    day,
                    "ads",
                    "ads_roas_custom",
                    impressions=2000,
                    clicks=40,
                    orders=2,
                    gmv=150_000,
                    order_type="placed",
                    extra={"ads_expense": 30_000},
                ),
            ]
    return rows


def period_row(shop_id: uuid.UUID, dataset: str, start: date, end: date, **values: Any) -> Any:
    return PlatformPeriodMetric(
        shop_id=shop_id,
        dataset=dataset,
        period_start=start,
        period_end=end,
        variation_id="",
        confidence="high",
        **_src(),
        **{"order_type": "confirmed", "stream": "total", "segment": "all", **values},
    )


def period_rows(shop_id: uuid.UUID) -> list[PlatformPeriodMetric]:
    rows: list[PlatformPeriodMetric] = []
    # product totals (item-level rows) and item x source for the current window
    totals = {"1001": (700_000, 8), "1002": (400_000, 5), "1003": (180_000, 3)}
    for item, (gmv, orders) in totals.items():
        rows.append(
            period_row(
                shop_id,
                "product_period",
                CUR_START,
                CUR_END,
                item_id=item,
                gmv=Decimal(gmv),
                orders=Decimal(orders),
            )
        )
        rows.append(
            period_row(
                shop_id,
                "item_by_source_period",
                CUR_START,
                CUR_END,
                item_id=item,
                stream="product_card",
                impressions=Decimal(5000),
                clicks=Decimal(200),
                orders=Decimal(orders - 1),
                gmv=Decimal(gmv - 100_000),
            )
        )
        rows.append(
            period_row(
                shop_id,
                "item_by_source_period",
                CUR_START,
                CUR_END,
                item_id=item,
                stream="affiliate",
                impressions=Decimal(300),
                clicks=Decimal(40),
                orders=Decimal(1),
                gmv=Decimal(80_000),
            )
        )
    # a group campaign: head row + one row per product (spend sums to the campaign)
    spend = {"1001": 60_000, "1002": 25_000, "1003": 15_000}
    for item, cost in spend.items():
        rows.append(
            period_row(
                shop_id,
                "ads_campaign_period",
                CUR_START,
                CUR_END,
                item_id=item,
                order_type="placed",
                stream="ads",
                platform_source="Chiến dịch nhóm",
                segment="cgroup1",
                orders=Decimal(2),
                gmv=Decimal(cost * 5),
                impressions=Decimal(1000),
                clicks=Decimal(30),
                extra={"ads_expense": cost, "direct_sales": cost * 4, "running": True},
            )
        )
    rows.append(
        period_row(
            shop_id,
            "ads_campaign_period",
            CUR_START,
            CUR_END,
            item_id="",
            order_type="placed",
            stream="ads",
            platform_source="Chiến dịch nhóm",
            segment="cgroup1",
            orders=Decimal(6),
            gmv=Decimal(500_000),
            impressions=Decimal(3000),
            clicks=Decimal(90),
            extra={"ads_expense": 100_000, "direct_sales": 400_000, "running": True},
        )
    )
    rows.append(
        period_row(
            shop_id,
            "affiliate_partner_period",
            CUR_START,
            CUR_END,
            item_id="",
            order_type="none",
            stream="affiliate",
            platform_source="kol_one",
            segment="akol1",
            orders=Decimal(2),
            gmv=Decimal(120_000),
            clicks=Decimal(30),
            extra={"est_commission": 6_000},
        )
    )
    return rows


def voucher_rows(shop_id: uuid.UUID) -> list[PlatformPromotion]:
    def one(name: str, orders: int, cost: int, shopee: bool = False) -> PlatformPromotion:
        return PlatformPromotion(
            shop_id=shop_id,
            promo_type="voucher",
            program_name=name,
            starts_at=datetime(2026, 9, 1),
            ordinal=0,
            period_start=CUR_START,
            period_end=CUR_END,
            order_type="confirmed",
            gmv=Decimal(orders * 90_000),
            orders=Decimal(orders),
            extra={"voucher_cost": cost, "usage_rate": 0.25, "created_by_shopee": shopee},
            **_src(),
        )

    return [
        one("Ory 2k", 2, 4_000),
        one("Ory 1k", 1, 1_000),
        one("Voucher Thông Minh", 1, 700, True),
    ]


async def seed_shopee_shop(
    session: AsyncSession, *, rules: bool = False, materialized: bool = True
) -> Seeded:
    """The synthetic Shopee shop. ``materialized`` (P99b): its stored daily rows are built, as the
    ingest hook does in production -- a screen's window without them is the missing-rows state."""
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee", shop_name="Synthetic Shopee Shop")
    shop_id = shop.id
    for item, (name, sku) in ITEMS.items():
        session.add(
            PlatformItem(
                shop_id=shop_id,
                item_id=item,
                variation_id="",
                name=name,
                seller_sku=sku,
                status="Đang hoạt động",
                extra={},
                **_src(),
            )
        )
    lines = order_lines(shop_id)
    session.add_all(lines)
    session.add_all(daily_rows(shop_id))
    session.add_all(period_rows(shop_id))
    session.add_all(voucher_rows(shop_id))
    if rules:
        for key, scope, value in (
            ("sku_cost", "G1", 30_000),
            ("product_cost", "1002", 20_000),
            ("packaging_cost", "G1", 1_000),
            ("min_margin_pct", "", 60),
            ("daily_marketing_cap", "", 10_000),
        ):
            session.add(
                ShopRule(
                    shop_id=shop_id,
                    rule_key=key,
                    scope_ref=scope,
                    value=value,
                    set_by="seller",
                    set_at=NOW,
                )
            )
    await session.flush()
    if materialized:
        from juli_backend.services.shopee_analytics import materialize

        await materialize.backfill_shop(session, shop_id)
        await session.flush()
    return Seeded(shop_id, user, shop, {ln.order_ref for ln in lines}, lines)


def snapshot(shop_id: uuid.UUID, item_id: str, **over: Any) -> PlatformItemSnapshot:
    values: dict[str, Any] = {
        "shop_id": shop_id,
        "platform": "shopee",
        "item_id": item_id,
        "variation_id": "",
        "captured_at": datetime(2026, 10, 4, 12, 0),
        "title": ITEMS[item_id][0],
        "image_urls": ["https://img.example/synthetic.jpg"],
        "image_hashes": ["h1"],
        "list_price": Decimal(100_000),
        "current_price": Decimal(90_000),
        "stock": 120,
        "rating": Decimal("4.8"),
        "rating_count": 55,
        "category_path": ["Nhà cửa & Đời sống", "Dụng cụ nhà bếp", "Tạp dề & găng tay nấu nướng"],
        "status": "Đang hoạt động",
        "source": "extension",
        "source_rank": 1,
    }
    values.update(over)
    return PlatformItemSnapshot(**values)


def keyword(shop_id: uuid.UUID, text: str, role: str, item_id: str = "1001") -> ShopKeywordSeed:
    return ShopKeywordSeed(
        shop_id=shop_id,
        platform="shopee",
        keyword=text,
        pattern="type_function",
        item_ids=[item_id],
        role=role,
        item_scope=item_id,
        enabled=True,
    )
