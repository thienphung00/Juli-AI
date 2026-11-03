"""P90 step 2 acceptance on a real order export. PRINTS COUNTS AND AGGREGATE TOTALS ONLY.

    python scripts/shopee_orders_acceptance.py ORDER.xlsx --shop-stats STATS.xlsx \\
        [--conversions SellerConversionReport.csv] [--window 2026-10-01:2026-10-28]

Reads the order export only through ``scripts.shopee_exports.orders`` (the PII-stripping parser:
buyer columns are never decoded) and asserts it. The order id exists only as the keyed hash
(``JULI_ORDER_REF_KEY``, else a random per-run key: the join to the affiliate lane works within
the run). Nothing but counts, sums and ratios is printed: no cell value, name, id or status of a
single order.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts.shopee_exports import orders, parse


def _key() -> bytes:
    return os.environ.get("JULI_ORDER_REF_KEY", "").strip().encode() or os.urandom(32)


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _money(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _bases() -> dict[str, Callable[[orders.OrderSummary], bool]]:
    return {
        "placed (every order)": lambda o: True,
        "excluding cancelled": lambda o: o.status != orders.CANCELLED,
        "paid (has paid time)": lambda o: o.paid,
        "delivered or refund-accepted": lambda o: o.status in orders.PROFIT_STATUSES,
    }


def shop_stats_sales(path: Path, window: tuple[date, date]) -> dict[str, Decimal]:
    """Σ ``Tổng doanh số`` per order type from a shop-stats file, over ``window`` (daily rows)
    or, for a monthly roll-up, its period row."""
    parsed = parse.Parsed()
    parse.parse_shop_stats(path, parsed)
    totals: dict[str, Decimal] = {}
    for post in parsed.posts:
        if post.dataset not in ("shop_overview", "shop_overview_period"):
            continue
        order_type = str(post.body.get("order_type"))
        for row in post.body["rows"]:
            if "sales" not in row:
                continue
            when = row.get("date")
            if when is not None and not window[0] <= _day(when) <= window[1]:
                continue
            totals[order_type] = totals.get(order_type, Decimal(0)) + Decimal(str(row["sales"]))
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("order_export", type=Path)
    ap.add_argument("--shop-stats", type=Path, required=True)
    ap.add_argument("--conversions", type=Path)
    ap.add_argument("--window", required=True, help="YYYY-MM-DD:YYYY-MM-DD, by order date")
    args = ap.parse_args(argv)
    start, end = (_day(part) for part in args.window.split(":"))
    key = _key()

    export = orders.read_order_export(args.order_export, key)
    # (a) no buyer column was read
    read = export.value_columns_read
    assert read <= set(orders.READ), "a column outside the allowlist was read"
    assert not read & orders.BUYER_HEADERS, "a buyer column was read"
    print(
        f"(a) headers {len(read) + len(export.ignored_headers)}; values read from {len(read)} "
        f"allowlisted; never read {len(export.ignored_headers)} (buyer / id / free text / names); "
        f"buyer columns read: {len(read & orders.BUYER_HEADERS)}"
    )

    # (b) orders and lines
    all_orders = list(export.orders.values())
    print(f"(b) order lines {len(export.rows)}, distinct orders {len(all_orders)}")
    print("    raw status strings (lines): ", dict(sorted(export.raw_status_counts.items())))
    mapped = Counter(o.status for o in all_orders)
    print("    mapped status (orders):     ", dict(sorted(mapped.items())))
    in_window = [o for o in all_orders if start <= o.ordered_at.date() <= end]
    print(f"    orders dated {start:%d/%m}-{end:%d/%m}: {len(in_window)}")
    print(
        "    basis -> orders | AOV by order value | by buyer total | by GMV (deal x qty) | "
        "by GMV - shop voucher"
    )
    for name, test in _bases().items():
        sel = [o for o in in_window if test(o)]
        n = len(sel) or 1
        values = (
            sum(o.order_value for o in sel),
            sum(o.buyer_total for o in sel),
            sum(o.gmv for o in sel),
            sum(o.gmv - o.shop_voucher for o in sel),
        )
        print(f"    {name:<30}{len(sel):>5} | " + " | ".join(_money(v / n) for v in values))

    paid = [o for o in in_window if o.paid]
    if paid:
        gmv, voucher = sum(o.gmv for o in paid), sum(o.shop_voucher for o in paid)
        cancelled_paid = sum(1 for o in paid if o.status == orders.CANCELLED)
        print(
            f"    paid basis exactly: {len(paid)} orders ({cancelled_paid} later cancelled), "
            f"Σ GMV {_money(gmv)}, Σ shop voucher {_money(voucher)}, "
            f"Σ GMV - voucher {_money(gmv - voucher)}, AOV {(gmv - voucher) / len(paid):,.2f}"
        )

    # (c) GMV vs shop-stats
    stats = shop_stats_sales(args.shop_stats, (start, end))
    line_by_order = {o.ref: o for o in in_window}
    print(
        f"(c) shop-stats Tổng doanh số {start:%d/%m}-{end:%d/%m}: "
        + ", ".join(f"{k} {_money(v)}" for k, v in sorted(stats.items()))
    )
    for name, test in _bases().items():
        gmv = sum(o.gmv for o in in_window if test(o))
        for kind, total in sorted(stats.items()):
            if total:
                gap = (gmv - total) / total * 100
                print(f"    Σ line GMV [{name}] {_money(gmv)} vs {kind}: {gap:+.2f}%")
    assert line_by_order is not None

    # (d) fees
    delivered = [o for o in in_window if o.status in orders.PROFIT_STATUSES]
    filled = sum(1 for o in delivered if o.fees_filled)
    totals: Counter[str] = Counter()
    for row in export.rows:
        ref_day = date.fromisoformat(row["ordered_at"][:10])
        if start <= ref_day <= end:
            for name in ("fee_fixed", "fee_service", "fee_payment"):
                totals[name] += Decimal(str(row.get(name, 0)))
    share = (filled / len(delivered) * 100) if delivered else 0.0
    print(
        f"(d) delivered orders {len(delivered)}, fee columns filled {filled} ({share:.1f}%); "
        f"Σ fixed {_money(totals['fee_fixed'])}, service {_money(totals['fee_service'])}, "
        f"transaction {_money(totals['fee_payment'])}"
    )

    # (e) affiliate join
    if args.conversions is not None:
        parsed = parse.Parsed(order_ref_key=key)
        parse.parse_seller_conversions(args.conversions, parsed)
        refs = {
            row["order_ref"]
            for post in parsed.posts
            if post.dataset == "affiliate_order_lines"
            for row in post.body["rows"]
        }
        matched = len(refs & set(export.orders))
        placed_days = [o.ordered_at.date() for o in all_orders]
        outside = sum(
            1
            for post in parsed.posts
            if post.dataset == "affiliate_order_lines"
            for row in post.body["rows"]
            if row["order_ref"] not in export.orders
            and not min(placed_days) <= _day(row["ordered_at"][:10]) <= max(placed_days)
        )
        print(f"    unmatched lines ordered outside the export's own period: {outside}")
        print(
            f"(e) affiliate orders {len(refs)}: matched to order lines {matched}, "
            f"unmatched {len(refs) - matched}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
