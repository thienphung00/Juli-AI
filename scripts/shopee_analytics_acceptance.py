"""P90 step 7 acceptance on loaded data. PRINTS COUNTS AND AGGREGATES ONLY.

    python scripts/shopee_analytics_acceptance.py --database-url postgresql://...@127.0.0.1/... \\
        --shop-id UUID [--month 2026-10] [--end-day 28]

The shop's Shopee files must be loaded first (``scripts/load_shopee_exports.py``). Local database
only (the same host rule as the loader). Every check prints PASS / FAIL with the numbers it
compared; no order id, name, SKU text or row value is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.services.shopee_analytics import loaders, queries, service
from juli_backend.services.shopee_analytics.windows import Window

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FAILS: list[str] = []


def money(value: object) -> str:
    return f"{Decimal(str(value or 0)):,.0f}".replace(",", ".")


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        FAILS.append(name)


async def ads_group_sums(
    session: AsyncSession, shop_id: uuid.UUID, expected_total: Decimal | None
) -> None:
    """Per report window, per campaign with product rows: Σ product spend vs the campaign row."""
    rows = (
        (
            await session.execute(
                select(PlatformPeriodMetric).where(
                    PlatformPeriodMetric.shop_id == shop_id,
                    PlatformPeriodMetric.dataset == "ads_campaign_period",
                    PlatformPeriodMetric.order_type == "placed",
                )
            )
        )
        .scalars()
        .all()
    )
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r.period_start, r.period_end, r.segment)
        g = groups.setdefault(key, {"head": None, "items": [], "name": r.platform_source or ""})
        spend = Decimal(str((r.extra or {}).get("ads_expense") or 0))
        gmv = Decimal(str(r.gmv or 0))
        if r.item_id:
            g["items"].append((spend, gmv))
        else:
            g["head"] = (spend, gmv)
    for (start, end, _), g in sorted(groups.items()):
        if not g["items"] or "Nhóm" not in g["name"]:
            continue
        item_spend = sum((s for s, _ in g["items"]), Decimal(0))
        item_gmv = sum((m for _, m in g["items"]), Decimal(0))
        if g["head"] is None:
            roas = item_gmv / item_spend if item_spend else Decimal(0)
            check(
                f"Chiến dịch Nhóm {start:%d/%m}-{end:%d/%m}: Σ sản phẩm = tổng chiến dịch",
                abs(item_spend - Decimal(expected_total)) <= Decimal(2),
                f"{len(g['items'])} sản phẩm (file không có dòng chiến dịch), "
                f"Σ {money(item_spend)} "
                f"vs {money(expected_total)}, ROAS {roas:.2f}",
            )
            continue
        head_spend, head_gmv = g["head"]
        roas = head_gmv / head_spend if head_spend else Decimal(0)
        check(
            f"Chiến dịch Nhóm {start:%d/%m}-{end:%d/%m}: Σ chi phí theo sản phẩm = chiến dịch",
            abs(item_spend - head_spend) <= Decimal(len(g["items"])),
            f"{len(g['items'])} sản phẩm, Σ {money(item_spend)} vs chiến dịch {money(head_spend)}, "
            f"ROAS {roas:.2f}",
        )


async def vouchers(session: AsyncSession, shop_id: uuid.UUID, ctx: loaders.ShopContext) -> None:
    """Every voucher month Nov 2025 - Oct 2026: seller cost = value x confirmed orders.

    The value is read from the voucher's own name ("Ory 5k"); a voucher the ads service made
    for the shop ("Voucher Thông Minh", ``created_by_shopee``) pays a seller share that is not
    a fixed value, so it is counted apart. Where an order export covers the month, the file's
    orders per value are compared with the order lines' (cancelled orders keep a voucher in the
    file but carry 0 on the line, so the file may exceed the lines by at most the cancelled ones).
    """
    months = [date(2025 + (10 + i) // 12, (10 + i) % 12 + 1, 1) for i in range(12)]
    for first in months:
        last = date(first.year + first.month // 12, first.month % 12 + 1, 1) - date.resolution
        window = Window(first, last)
        load = await loaders.load_vouchers(session, shop_id, window)
        if not load.rows:
            print(f"----  voucher {first:%m/%Y}: no voucher rows")
            continue
        shop_made = [v for v in load.rows if not v.by_shopee]
        named = [v for v in shop_made if v.value_hint is not None]
        mismatches = [v for v in named if v.value_hint * v.orders != v.cost]
        whole = [v for v in shop_made if v.orders == 0 or v.cost % v.orders == 0]
        ads_made = [v for v in load.rows if v.by_shopee]
        check(
            f"voucher {first:%m/%Y}: chi phí = giá trị × đơn",
            not mismatches and len(whole) == len(shop_made),
            f"{len(shop_made)} voucher của shop ({len(named)} đọc được giá trị từ tên, lệch "
            f"{len(mismatches)}, chi phí chia hết cho số đơn {len(whole)}/{len(shop_made)}), "
            f"Σ {money(sum(v.cost for v in shop_made))}; {len(ads_made)} voucher do dịch vụ "
            f"hiển thị tạo, Σ {money(sum(v.cost for v in ads_made))} "
            f"({load.choice.basis}, {load.choice.covered_days} ngày)",
        )
        view = await service.load_view(session, shop_id, ctx, window)
        if not (view.line_orders and view.data.lines.covers_window):
            continue
        line_total = sum((ln.shop_voucher_share for ln, _ in view.pairs), Decimal(0))
        file_total = sum((v.cost for v in shop_made), Decimal(0))
        cancelled = len({ln.order_id for ln, pb in view.pairs if pb.excluded_reason})
        gap = file_total - line_total
        top = max((v.value_hint or Decimal(0) for v in shop_made), default=Decimal(0))
        check(
            f"voucher {first:%m/%Y}: chi phí file = voucher trên dòng đơn + đơn đã huỷ",
            0 <= gap <= cancelled * top,
            f"file {money(file_total)}đ; dòng đơn {money(line_total)}đ; chênh {money(gap)}đ "
            f"≤ {cancelled} đơn đã huỷ có thanh toán × {money(top)}đ "
            "(đơn huỷ giữ voucher trong file, dòng đơn ghi 0)",
        )


async def main_async(args: argparse.Namespace) -> int:
    engine = create_async_engine(async_database_url(args.database_url))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with with_shop_scope(session, args.shop_id):
                ctx = await loaders.load_context(session, args.shop_id)
                first = date.fromisoformat(args.month + "-01")
                window = Window(first, first.replace(day=args.end_day))
                now = await service.load_view(session, args.shop_id, ctx, window)
                before = await service.load_view(session, args.shop_id, ctx, window.previous())

                print(f"== đơn hàng {window.start:%d/%m/%Y}-{window.end:%d/%m/%Y}")
                orders = now.line_orders
                gmv = now.line_gmv
                voucher = sum((ln.shop_voucher_share for ln, _ in now.pairs), Decimal(0))
                aov = (gmv - voucher) / orders if orders else Decimal(0)
                print(f"     đơn xác nhận {orders}; GMV dòng đơn {money(gmv)}; AOV {aov:,.0f}")
                check("số đơn xác nhận", orders == args.orders, f"{orders} (kỳ vọng {args.orders})")
                check(
                    "AOV Seller Centre",
                    abs(aov - Decimal(args.aov)) <= Decimal(1),
                    f"{aov:,.2f} (kỳ vọng {args.aov})",
                )
                shopee = now.data.totals
                if shopee.gmv:
                    gap = (gmv - shopee.gmv) / shopee.gmv * 100
                    check(
                        "GMV dòng đơn khớp Doanh số Shopee (±2 %)",
                        abs(gap) <= 2,
                        f"{money(gmv)} vs {money(shopee.gmv)} ({gap:+.2f} %, {shopee.basis})",
                    )

                print("== Nhóm: chi phí theo sản phẩm")
                await ads_group_sums(session, args.shop_id, args.nhom_total)

                print("== luồng cộng đủ GMV shop")
                for kind in ("7d", "30d", "90d"):
                    w = await service.resolve(session, args.shop_id, period=kind, as_of=window.end)
                    view = await service.load_view(session, args.shop_id, ctx, w)
                    t = view.flows.shop if view.flows else None
                    if t is None:
                        print(f"----  {kind}: no flow data")
                        continue
                    res = t.residual
                    check(
                        f"luồng {kind} + chênh lệch nguồn = GMV shop",
                        t.gmv_sum == t.total_gmv,
                        f"Σ {money(t.gmv_sum)} vs shop {money(t.total_gmv)}; chênh lệch nguồn "
                        f"{money(res.gmv) if res else 0} ({view.data.traffic.basis}, "
                        f"{view.data.traffic.days_covered}/{w.days} ngày)",
                    )
                t = now.flows.shop if now.flows else None
                if t is not None:
                    check(
                        f"luồng {args.month} + chênh lệch nguồn = GMV shop",
                        t.gmv_sum == t.total_gmv,
                        f"Σ {money(t.gmv_sum)} vs shop {money(t.total_gmv)}",
                    )

                print("== ưu đãi cộng đủ")
                body = await queries.overview(
                    session, args.shop_id, period="custom", start=window.start, end=window.end
                )
                lv = body["levers"]
                check(
                    "4 ưu đãi cộng đủ GMV dòng đơn",
                    lv["adds_up"],
                    f"Σ {money(lv['gmv_sum'])} vs {money(lv['gmv_total'])}",
                )

                print("== lợi nhuận và độ phủ giá vốn")
                p = body["profit"]
                cov = p["cost_coverage"]
                print(
                    f"     lợi nhuận {money(p['profit_vnd'])}; biên {p['margin_pct']} %; "
                    f"giá vốn thật {cov['real_pct']} %, giả định {cov['assumed_pct']} %, "
                    f"chưa biết {cov['unknown_pct']} %; QC tổng {money(p['ad_spend']['total'])}, "
                    f"theo sản phẩm {money(p['ad_spend']['by_product'])}, "
                    f"không gắn sản phẩm {money(p['ad_spend']['unattributed'])}"
                )
                check(
                    "độ phủ giá vốn có mặt (tỷ lệ giả định)",
                    cov["assumed_pct"] is not None and cov["real_pct"] is not None,
                    f"giả định {cov['assumed_pct']} %",
                )
                ad = p["ad_spend"]
                check(
                    "Σ QC theo sản phẩm + QC không gắn sản phẩm = tổng chi QC",
                    abs(
                        Decimal(str(ad["by_product"]))
                        + Decimal(str(ad["unattributed"]))
                        - Decimal(str(ad["total"]))
                    )
                    <= Decimal(1),
                    f"{money(ad['by_product'])} + {money(ad['unattributed'])} "
                    f"= {money(ad['total'])}",
                )
                aff = body["affiliate"]
                print(
                    f"     liên kết: {aff['kols']} KOL, {money(aff['partner_orders'])} đơn, "
                    f"GMV {money(aff['partner_gmv'])}; dòng đơn {aff['order_lines']['orders']} đơn"
                )

                print("== voucher theo tháng")
                await vouchers(session, args.shop_id, ctx)
                del before
    finally:
        await engine.dispose()
    print(f"\n{len(FAILS)} FAIL" if FAILS else "\nall checks passed")
    return 1 if FAILS else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--shop-id", type=uuid.UUID, required=True)
    parser.add_argument("--month", default="2026-10", help="YYYY-MM of the order export")
    parser.add_argument("--end-day", type=int, default=28)
    parser.add_argument("--orders", type=int, default=121)
    parser.add_argument("--aov", type=float, default=172025)
    parser.add_argument(
        "--nhom-total", type=int, default=8146632, help="Chiến Dịch Nhóm total, 02/08-02/11"
    )
    args = parser.parse_args(argv)
    host = urlparse(args.database_url).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit("local databases only (client data stays local, ADR-117 6)")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
