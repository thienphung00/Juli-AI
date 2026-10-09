#!/usr/bin/env python3
"""Generate the demo's anonymous Phân tích sample — invented shop, invented numbers.

Builds a synthetic 60-day snapshot of "Cửa hàng Mẫu Hoa Mai" (an invented shop)
with the test helpers in ``tests/support/shop_diagnosis.py``, then runs the REAL
builders over it:

- ``build_report`` → ``apps/demo/src/lib/shop-analysis/sample-report.json``
  (the ``GET /v1/demo/analysis`` envelope the anonymous app shows);
- ``build_rankings`` → ``apps/demo/src/lib/shop-analysis/sample-rankings.json``
  (one ``GET /v1/demo/analysis/rankings`` envelope per stream × metric, keyed
  ``{stream: {metric: envelope}}``), including synthetic LIVE sessions and
  per-video 30/30 windows.

Never real shop data. Deterministic (seeded); floats are rounded (≥ 100 000 to
whole numbers, else 5 significant digits) to keep the bundle small::

    PYTHONPATH=backend/src:. python scripts/demo_analysis_sample.py
    PYTHONPATH=backend/src:. python scripts/demo_analysis_sample.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "apps" / "demo" / "src" / "lib" / "shop-analysis"
AS_OF = "2026-10-06"
BUILT_AT = "2026-10-07T01:15:00+07:00"
SHOP_NAME = "Cửa hàng Mẫu Hoa Mai"

TITLES = {
    "s1": "Bình giữ nhiệt inox 500ml",
    "s2": "Hộp cơm giữ nhiệt 3 tầng",
    "s3": "Ly sứ quai tròn 350ml",
    "s4": "Bộ đũa gỗ 10 đôi",
    "s5": "Khăn lau bếp sợi tre",
    "s6": "Giá úp bát 2 tầng",
    "s7": "Thớt gỗ tròn 30cm",
}
LIVE_TITLES = ("Xả kho đồ bếp", "Đồ bếp giá tốt", "Săn deal cuối tuần", "Giờ vàng đồ gia dụng")
VIDEO_TITLES = (
    "Mẹo giữ nóng cơm cả buổi",
    "Bình giữ nhiệt test 12 tiếng",
    "Bộ đũa gỗ dùng 1 năm",
    "Dọn bếp 5 phút",
    "Hộp cơm cho dân văn phòng",
    "So sánh ly sứ và ly thuỷ tinh",
    "Khăn tre thấm nước thế nào",
    "Góc bếp gọn gàng",
    "Unbox giá úp bát",
    "Thớt gỗ tròn có tốt không",
    "Combo quà tân gia",
    "Review hộp cơm 3 tầng",
)


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        if value == 0 or not math.isfinite(value):
            return value
        if abs(value) >= 1e5:
            return float(round(value))
        return float(f"{value:.5g}")
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


def build(folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(report envelope, rankings fixture) for the synthetic shop."""
    from juli_backend.services.shop_diagnosis import build_report, load_snapshot
    from juli_backend.services.shop_diagnosis.channels import Counts
    from juli_backend.services.shop_diagnosis.heroes import Ranking
    from juli_backend.services.shop_diagnosis.rankings import VideoWindowMetrics, build_rankings
    from juli_backend.services.shop_diagnosis.snapshot import Windows
    from tests.support.shop_diagnosis import (
        END,
        Block,
        DayRow,
        TabBlock,
        order,
        seconds,
        window_days,
        write_snapshot,
    )

    rng = random.Random(20261008)
    windows = Windows.ending(END, 30)
    last = set(windows.last_days())

    def block(imp: float, ctr: float, cart: float, ctor: float, aov: float) -> Block:
        imp = int(imp * rng.uniform(0.8, 1.2))
        clicks = int(imp * ctr * rng.uniform(0.85, 1.15))
        orders = int(round(clicks * ctor * rng.uniform(0.7, 1.3)))
        atc = max(orders, int(clicks * cart))
        return Block(imp, clicks, atc, orders, int(orders * aov * rng.uniform(0.95, 1.05)))

    daily: dict[date, list[DayRow]] = {}
    for day in window_days():
        rows = []
        in_last = day in last
        for n, pid in enumerate(TITLES):
            scale = [1.0, 0.7, 0.5, 0.35, 0.25, 0.15, 0.1][n]
            card_ctor = 0.038 if (in_last and pid == "s1") else 0.06
            card = block(
                2600 * scale * (1.25 if in_last else 1.0),
                0.045,
                0.14,
                card_ctor,
                189_000 - n * 15_000,
            )
            tab_imp = int(700 * scale * rng.uniform(0.8, 1.2))
            tab_clicks = int(tab_imp * 0.06)
            tab = TabBlock(
                tab_imp,
                tab_clicks,
                f"{0.07 * rng.uniform(0.8, 1.2):.4f}",
                int(tab_clicks * 0.07 * 170_000),
            )
            rows.append(
                DayRow(
                    pid,
                    card=card,
                    tab=tab,
                    seller_video=block(500 * scale, 0.03, 0.05, 0.05, 175_000),
                    seller_live=block((900 if in_last else 400) * scale, 0.05, 0.06, 0.08, 165_000),
                    affiliate_video=block(
                        6000 * scale * (1.1 if in_last else 1.0), 0.02, 0.1, 0.05, 180_000
                    ),
                    affiliate_live=block(1200 * scale, 0.025, 0.08, 0.04, 170_000),
                    refunds=int(20_000 * scale),
                )
            )
        daily[day] = rows

    orders = []
    for i, day in enumerate(window_days()):
        for k in range(6):
            pids = [rng.choice(list(TITLES))] if rng.random() < 0.8 else rng.sample(list(TITLES), 2)
            value = rng.choice([129_000, 159_000, 179_000, 189_000, 249_000, 320_000])
            orders.append(order(f"o{i}_{k}", day, pids, value))

    flash_start = windows.last_first + timedelta(days=4)
    activities = [
        {
            "id": "f1",
            "activity_type": "FLASHSALE",
            "status": "EXPIRED",
            "title": "Flash sale cuối tuần",
            "begin_time": seconds(flash_start, 0),
            "end_time": seconds(flash_start + timedelta(days=10)),
        },
        {
            "id": "d1",
            "activity_type": "FIXED_PRICE",
            "status": "ONGOING",
            "title": "Giảm giá sản phẩm",
            "begin_time": seconds(windows.prior_first, 0),
            "end_time": seconds(END + timedelta(days=30)),
        },
    ]
    details = {
        "f1": {
            "products": [
                {"id": "s1", "skus": [{"id": "k1", "activity_price": {"amount": "175000"}}]},
                {"id": "s2", "skus": [{"id": "k2", "activity_price": {"amount": "160000"}}]},
            ]
        },
        "d1": {
            "products": [
                {"id": "s1", "skus": [{"id": "k1", "activity_price": {"amount": "182000"}}]}
            ]
        },
    }
    coupons = [
        {
            "id": "c1",
            "title": "Giảm 15k",
            "status": "ONGOING",
            "claim_duration": {"start_time": seconds(windows.last_first + timedelta(days=12))},
            "threshold": {"min_spend": {"amount": "199000"}},
            "discount": {"reduction_amount": {"amount": "15000"}},
            "product_scope": "FULL_SHOP",
        },
        {
            "id": "c2",
            "title": "Giảm 30k đơn lớn",
            "status": "ONGOING",
            "claim_duration": {"start_time": seconds(windows.prior_first)},
            "threshold": {"min_spend": {"amount": "399000"}},
            "discount": {"reduction_amount": {"amount": "30000"}},
            "product_scope": "FULL_SHOP",
        },
    ]
    snap = write_snapshot(
        folder / "snap",
        daily,
        shop_name=SHOP_NAME,
        orders=orders,
        activities=activities,
        details=details,
        coupons=coupons,
        products={pid: {"title": title} for pid, title in TITLES.items()},
    )
    report = build_report(load_snapshot(snap), Ranking.COMBINED_60D)
    envelope = {
        "as_of": AS_OF,
        "built_at": BUILT_AT,
        "ranking": "60d",
        "report": rounded(json.loads(report.to_json())),
    }

    # LIVE sessions (two a week before, three a week lately) — rankings only.
    live_rng = random.Random(1010)
    sessions = []
    for n, day in enumerate(window_days()):
        recent = day in last
        if day.weekday() not in ((1, 3, 5) if recent else (2, 5)):
            continue
        impressions = int((4_800 if recent else 3_200) * live_rng.uniform(0.4, 1.6))
        clicks = int(impressions * 0.05 * live_rng.uniform(0.6, 1.4))
        sku_orders = int(round(clicks * 0.08 * live_rng.uniform(0.3, 1.7)))
        sessions.append(
            {
                "id": f"live{n:02d}",
                "title": LIVE_TITLES[n % len(LIVE_TITLES)],
                "start_time": str(seconds(day, 20)),
                "interaction_performance": {
                    "product_impressions": impressions,
                    "product_clicks": clicks,
                },
                "sales_performance": {"sku_orders": sku_orders, "gmv": sku_orders * 165_000},
            }
        )
    snapshot = replace(load_snapshot(snap), live_sessions=sessions)

    # Per-video 30/30 windows (window totals) — rankings only.
    video_rng = random.Random(2020)
    videos = []
    for n, title in enumerate(VIDEO_TITLES):
        posted = windows.prior_first + timedelta(days=5 * n)
        impressions = int(4_500 * video_rng.uniform(0.3, 1.8))
        clicks = int(impressions * 0.03 * video_rng.uniform(0.4, 1.6))
        sku_orders = float(int(round(clicks * 0.05 * video_rng.uniform(0.5, 1.5))))
        videos.append(
            VideoWindowMetrics(
                video_id=f"v{n + 1:02d}",
                title=title,
                posted_on=posted,
                last=Counts(impressions, clicks, None, sku_orders, sku_orders * 175_000),
                prior=None
                if posted >= windows.last_first
                else Counts(
                    impressions * 1.1, clicks * 1.1, None, sku_orders, sku_orders * 175_000
                ),
            )
        )

    fixture: dict[str, dict[str, Any]] = {}
    for table in build_rankings(snapshot, videos):
        fixture.setdefault(table.stream.value, {})[table.metric.value] = {
            "as_of": AS_OF,
            "built_at": BUILT_AT,
            "stream": table.stream.value,
            "metric": table.metric.value,
            "ranking": rounded(table.payload),
        }
    return envelope, fixture


def dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed files differ")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory() as tmp:
        envelope, fixture = build(Path(tmp))
    outputs = {
        OUT_DIR / "sample-report.json": dump(envelope),
        OUT_DIR / "sample-rankings.json": dump(fixture),
    }
    stale = [
        path
        for path, text in outputs.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    ]
    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}")
        return 1 if stale else 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
