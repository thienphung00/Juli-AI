#!/usr/bin/env python3
"""Read-only evidence pull for a shop's AOV / combo / review strategy.

Answers three questions with the shop's own data, nothing written to TikTok:

1. **Basket**: how many SKU units per order, how often an order holds more
   than one line, which products are bought together (co-purchase pairs),
   and the share of multi-line orders — the evidence a BMSM or a bundle
   decision needs.
2. **Trend**: six weekly A-34 windows per product, so hero and long-tail
   products can be compared on orders, GMV, AOV, CTR, CTOR and add-to-cart
   week by week instead of one 14-vs-28-day diff.
3. **Refunds**: refunded items and refund GMV per product from A-34, the
   closest trust proxy the Partner API exposes (reviews have no read
   endpoint; use FastMoss or Seller Center for review counts).

Sources: ``POST /order/202309/orders/search`` paginated over the lookback
(line items carry ``product_id``, ``sku_id``, ``sale_price``), and
``GET /analytics/202605/shop_products/performance`` per weekly window. Both
go through ``ProductionReadClientFactory`` (read-only transport guard).

Usage (owner shell, where DATABASE_URL is exported; env file holds the
TikTok app keys)::

    set -a && source /Users/macos/Juli-AI-v2/juli/.env && set +a
    PYTHONPATH=backend/src python scripts/optimize_product_strategy_evidence.py \\
        --as-of 2026-10-05 --lookback-days 90 --out-dir out/fujiwa-strategy

Outputs ``orders_raw.json`` (snapshot), ``weekly_a34.json`` (snapshot),
``evidence.json`` and ``report.md``.

The orders resource caps pagination (it logs ``tiktok_pagination_max_pages_reached``
and returns what it has, ~1,000 orders), so on a busy shop the basket figures
are a sample of the lookback, not the whole of it; the report states the
order count and the time span it actually covers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Any

HERO_MIN_ORDERS_PER_DAY = 1.0
EXCLUDE_TITLE_PATTERNS = ("quà tặng", "hàng tặng", "không bán", "không tham gia")


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _amount(value: Any) -> Decimal:
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


# --------------------------------------------------------------------------- live fetch


async def fetch_live(out: Path, *, as_of: date, lookback_days: int, sleep_s: float) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    from juli_backend.core.async_db import async_database_url
    from juli_backend.core.config import require_env
    from juli_backend.core.security import resolve_production_read_credential
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.integrations.tiktok.factories import (
        ClientFactoryConfig,
        ProductionReadClientFactory,
    )
    from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID

    app_key, app_secret = require_env("TIKTOK_APP_KEY"), require_env("TIKTOK_APP_SECRET")
    factory = ensure_worker_session_factory(async_database_url(require_env("DATABASE_URL")))
    async with factory() as session:
        credential = await resolve_production_read_credential(session)
    resources = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=credential.shop_cipher,
        )
    )

    # Orders: update_time window in epoch seconds, paginated by the resource.
    end = datetime.combine(as_of + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    start = end - timedelta(days=lookback_days)
    orders = resources.orders.search_all(
        update_time_from=int(start.timestamp()), update_time_to=int(end.timestamp())
    )
    _dump(
        out / "orders_raw.json", {"orders": orders, "window": [start.isoformat(), end.isoformat()]}
    )
    time.sleep(sleep_s)

    # Six weekly A-34 windows ending at as_of.
    weekly: list[dict] = []
    week_end = as_of + timedelta(days=1)
    for _ in range(6):
        week_start = week_end - timedelta(days=7)
        products = resources.analytics.list_product_performance_all(
            start_date_ge=week_start.isoformat(), end_date_lt=week_end.isoformat()
        )
        weekly.append(
            {"start": week_start.isoformat(), "end": week_end.isoformat(), "products": products}
        )
        week_end = week_start
        time.sleep(sleep_s)
    _dump(out / "weekly_a34.json", {"weeks": list(reversed(weekly))})

    # Titles for every product seen, from the newest weekly window (cheap: no GetProduct).
    _dump(out / "meta.json", {"as_of": as_of.isoformat(), "lookback_days": lookback_days})


# --------------------------------------------------------------------------- analysis


def analyse(out: Path) -> dict:
    orders_payload = json.loads((out / "orders_raw.json").read_text())
    weekly_payload = json.loads((out / "weekly_a34.json").read_text())
    orders = orders_payload["orders"]
    weeks = weekly_payload["weeks"]

    # ---- titles and hero/tail split from the latest two weeks of A-34
    titles: dict[str, str] = {}
    recent_orders: Counter[str] = Counter()
    for week in weeks[-2:]:
        for p in week["products"]:
            total = p.get("total_performance") or {}
            titles.setdefault(str(p["id"]), str(p.get("title") or p.get("product_name") or ""))
            recent_orders[str(p["id"])] += int(total.get("sku_orders") or 0)
    for o in orders:
        for li in o.get("line_items") or []:
            pid = str(li.get("product_id") or "")
            if pid and not titles.get(pid):
                titles[pid] = str(li.get("product_name") or "")
    excluded = {
        pid for pid, t in titles.items() if any(pat in t.lower() for pat in EXCLUDE_TITLE_PATTERNS)
    }
    hero = {
        pid
        for pid, n in recent_orders.items()
        if n / 14 >= HERO_MIN_ORDERS_PER_DAY and pid not in excluded
    }

    # ---- basket analysis on non-cancelled orders
    statuses: Counter[str] = Counter(str(o.get("status") or "") for o in orders)
    kept = [
        o
        for o in orders
        if str(o.get("status") or "").upper() not in ("CANCELLED", "CANCELED", "UNPAID")
    ]
    lines_per_order: Counter[int] = Counter()
    products_per_order: Counter[int] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    product_orders: Counter[str] = Counter()
    product_multi: Counter[str] = Counter()
    product_qty_hist: dict[str, Counter[int]] = defaultdict(Counter)
    order_values: list[Decimal] = []
    single_product_values: dict[str, list[Decimal]] = defaultdict(list)
    for o in kept:
        items = [li for li in (o.get("line_items") or []) if li.get("product_id")]
        if not items:
            continue
        pids = Counter(str(li["product_id"]) for li in items)
        lines_per_order[len(items)] += 1
        products_per_order[len(pids)] += 1
        value = sum((_amount(li.get("sale_price")) for li in items), Decimal("0"))
        order_values.append(value)
        for pid, qty in pids.items():
            product_orders[pid] += 1
            product_qty_hist[pid][qty] += 1
            if len(items) > 1:
                product_multi[pid] += 1
        if len(pids) == 1:
            single_product_values[next(iter(pids))].append(value)
        for a, b in combinations(sorted(pids), 2):
            pair_counts[(a, b)] += 1

    n_orders = sum(lines_per_order.values())
    multi_line = sum(c for k, c in lines_per_order.items() if k > 1)
    multi_product = sum(c for k, c in products_per_order.items() if k > 1)

    pairs = [
        {
            "a": a,
            "a_title": titles.get(a, a)[:60],
            "b": b,
            "b_title": titles.get(b, b)[:60],
            "orders": n,
            "share_of_a": n / product_orders[a] if product_orders[a] else 0,
            "share_of_b": n / product_orders[b] if product_orders[b] else 0,
            "hero_tail": ("hero" if a in hero else "tail")
            + "+"
            + ("hero" if b in hero else "tail"),
        }
        for (a, b), n in pair_counts.most_common(25)
    ]

    per_product = []
    for pid, n in product_orders.most_common():
        hist = product_qty_hist[pid]
        total_units = sum(k * c for k, c in hist.items())
        values = single_product_values.get(pid) or []
        per_product.append(
            {
                "product_id": pid,
                "title": titles.get(pid, pid)[:60],
                "segment": "hero" if pid in hero else ("excluded" if pid in excluded else "tail"),
                "orders": n,
                "orders_with_other_lines": product_multi[pid],
                "multi_line_share": product_multi[pid] / n if n else 0,
                "units_per_order": total_units / n if n else 0,
                "qty_2_plus_share": sum(c for k, c in hist.items() if k >= 2) / n if n else 0,
                "single_product_aov": (float(sum(values) / len(values)) if values else None),
            }
        )

    # ---- weekly trend per segment and per hero product
    def seg_rows(pids: set[str]) -> list[dict]:
        rows = []
        for week in weeks:
            agg: dict[str, Decimal] = defaultdict(Decimal)
            for p in week["products"]:
                if str(p["id"]) not in pids:
                    continue
                t = p.get("total_performance") or {}
                for key in (
                    "sku_orders",
                    "items_sold",
                    "product_impressions",
                    "product_clicks",
                    "add_cart_count",
                    "refunded_items",
                ):
                    agg[key] += _amount(t.get(key))
                agg["gmv"] += _amount(t.get("gmv"))
                agg["refunds"] += _amount(t.get("refunds"))
            o = agg["sku_orders"]
            rows.append(
                {
                    "week": f"{week['start']}→{week['end']}",
                    "orders_per_day": float(o / 7),
                    "gmv_per_day": float(agg["gmv"] / 7),
                    "aov": float(agg["gmv"] / o) if o else None,
                    "items_per_order": float(agg["items_sold"] / o) if o else None,
                    "ctr": float(agg["product_clicks"] / agg["product_impressions"])
                    if agg["product_impressions"]
                    else None,
                    "atc_rate": float(agg["add_cart_count"] / agg["product_clicks"])
                    if agg["product_clicks"]
                    else None,
                    "ctor": float(o / agg["product_clicks"]) if agg["product_clicks"] else None,
                    "refund_share": float(agg["refunds"] / agg["gmv"]) if agg["gmv"] else None,
                }
            )
        return rows

    tail = {pid for pid in titles if pid not in hero and pid not in excluded}
    weekly_segments = {"hero": seg_rows(hero), "tail": seg_rows(tail)}
    weekly_heroes = {
        titles.get(pid, pid)[:60]: seg_rows({pid})
        for pid in sorted(hero, key=lambda p: -recent_orders[p])
    }

    return {
        "orders_total": len(orders),
        "orders_kept": n_orders,
        "statuses": dict(statuses),
        "multi_line_share": multi_line / n_orders if n_orders else 0,
        "multi_product_share": multi_product / n_orders if n_orders else 0,
        "lines_per_order_hist": dict(sorted(lines_per_order.items())),
        "products_per_order_hist": dict(sorted(products_per_order.items())),
        "median_order_value": float(sorted(order_values)[len(order_values) // 2])
        if order_values
        else None,
        "hero_products": sorted(hero),
        "pairs": pairs,
        "per_product": per_product,
        "weekly_segments": weekly_segments,
        "weekly_heroes": weekly_heroes,
    }


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _fmt(value: Any, fmt: str) -> str:
    return "—" if value is None else fmt.format(value)


def _trend_rows(rows: list[dict], *, with_gmv: bool) -> list[str]:
    head = ["Tuần", "Đơn/ngày"] + (["GMV/ngày"] if with_gmv else [])
    head += ["AOV", "Món/đơn", "CTR", "Thêm giỏ/click", "CTOR", "Hoàn/GMV"]
    out = [_row(*head), _row(*(["---"] * len(head)))]
    for r in rows:
        cells = [r["week"], f"{r['orders_per_day']:.2f}"]
        if with_gmv:
            cells.append(f"{r['gmv_per_day']:,.0f}")
        cells += [
            _fmt(r["aov"], "{:,.0f}"),
            _fmt(r["items_per_order"], "{:.2f}"),
            _fmt(r["ctr"], "{:.2%}"),
            _fmt(r["atc_rate"], "{:.2%}"),
            _fmt(r["ctor"], "{:.2%}"),
            _fmt(r["refund_share"], "{:.1%}"),
        ]
        out.append(_row(*cells))
    return out


def write_report(out: Path, ev: dict) -> None:
    L: list[str] = []
    L.append("# Bằng chứng cho chiến lược AOV / combo / đánh giá (chỉ đọc)\n")
    L.append(
        f"Đơn trong cửa sổ: **{ev['orders_total']}**, giữ lại sau khi bỏ hủy/chưa thanh toán: "
        f"**{ev['orders_kept']}** · trạng thái: {ev['statuses']}\n"
    )
    L.append("## 1. Giỏ hàng hiện tại\n")
    L.append(
        f"- Đơn có **> 1 dòng**: {ev['multi_line_share']:.1%} · đơn có **> 1 sản phẩm khác "
        f"nhau**: {ev['multi_product_share']:.1%}"
    )
    L.append(
        f"- Phân bố số dòng/đơn: {ev['lines_per_order_hist']} · số sản phẩm/đơn: "
        f"{ev['products_per_order_hist']}"
    )
    L.append(f"- Giá trị đơn trung vị: {_fmt(ev['median_order_value'], '{:,.0f} ₫')}\n")
    L.append("### Theo sản phẩm\n")
    L.append(
        _row(
            "Sản phẩm",
            "Nhóm",
            "Đơn",
            "Đơn có dòng khác",
            "Món/đơn",
            "Đơn mua ≥2 cùng SKU",
            "AOV khi mua lẻ",
        )
    )
    L.append(_row(*(["---"] * 7)))
    for r in ev["per_product"][:20]:
        L.append(
            _row(
                r["title"],
                r["segment"],
                r["orders"],
                f"{r['multi_line_share']:.0%}",
                f"{r['units_per_order']:.2f}",
                f"{r['qty_2_plus_share']:.0%}",
                _fmt(r["single_product_aov"], "{:,.0f} ₫"),
            )
        )
    L.append("\n## 2. Sản phẩm được mua cùng nhau (cặp)\n")
    L.append(_row("A", "B", "Số đơn chung", "% đơn của A", "% đơn của B", "Nhóm"))
    L.append(_row(*(["---"] * 6)))
    for pr in ev["pairs"]:
        L.append(
            _row(
                pr["a_title"],
                pr["b_title"],
                pr["orders"],
                f"{pr['share_of_a']:.0%}",
                f"{pr['share_of_b']:.0%}",
                pr["hero_tail"],
            )
        )
    L.append("\n## 3. Xu hướng 6 tuần theo nhóm\n")
    for seg, rows in ev["weekly_segments"].items():
        L.append(f"\n**{'Chủ lực' if seg == 'hero' else 'Ít đơn'}**\n")
        L.extend(_trend_rows(rows, with_gmv=True))
    L.append("\n## 4. Xu hướng 6 tuần từng sản phẩm chủ lực\n")
    for title, rows in ev["weekly_heroes"].items():
        L.append(f"\n**{title}**\n")
        L.extend(_trend_rows(rows, with_gmv=False))
    L.append(
        "\nMọi số là dữ liệu D-1 của TikTok, chỉ đọc. Đánh giá sản phẩm không có trong "
        "Partner API; xem FastMoss hoặc Seller Center."
    )
    (out / "report.md").write_text("\n".join(L))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1)
    )
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument(
        "--replay",
        action="store_true",
        help="skip the live fetch; analyse files already in --out-dir",
    )
    args = parser.parse_args(argv)
    if not args.replay:
        asyncio.run(
            fetch_live(
                args.out_dir, as_of=args.as_of, lookback_days=args.lookback_days, sleep_s=args.sleep
            )
        )
    ev = analyse(args.out_dir)
    _dump(args.out_dir / "evidence.json", ev)
    write_report(args.out_dir, ev)
    print(
        f"orders={ev['orders_total']} kept={ev['orders_kept']} "
        f"multi_product_share={ev['multi_product_share']:.1%} "
        f"→ {args.out_dir / 'report.md'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
