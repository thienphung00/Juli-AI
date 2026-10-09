"""Fast track P12 (ADR-109 Amendment 2): the additive report and ranking fields.

The Phân tích redesign reads, beyond the ADR-108 report: the shop's GMV per
day (Lịch sale và chiến dịch), each product's seller SKU (the ranking rows'
SKU chip), the products' promotions (Khuyến mãi) and, on LIVE / video rows,
the products they featured ("Xem sản phẩm được gắn ›"). Contract:
``fasttrack/contracts/p12-phan-tich.md``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from juli_backend.services.shop_diagnosis import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.channels import Counts
from juli_backend.services.shop_diagnosis.heroes import Ranking
from juli_backend.services.shop_diagnosis.promotions import (
    PromoKind,
    bands,
    parse_activities,
    promo_products,
)
from juli_backend.services.shop_diagnosis.rankings import (
    VideoWindowCounts,
    build_rankings,
    tagged_products,
)
from juli_backend.services.shop_diagnosis.report import build_report
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows, load_snapshot
from tests.support.shop_diagnosis import (
    END,
    Block,
    DayRow,
    a34_row,
    seconds,
    window_days,
    write_snapshot,
)

CONFIG = ShopDiagnosisConfig()
WINDOWS = Windows.ending(END, CONFIG.window_days)
DAYS = window_days(END)
LAST = DAYS[30:]


def _products() -> dict[str, dict]:
    return {
        "p1": {
            "title": "Son môi số 12",
            "skus": [{"id": "s1", "seller_sku": "SM-012", "price": {"sale_price": "150000"}}],
        },
        "p2": {
            "title": "Mặt nạ đất sét",
            "skus": [{"id": "s2", "seller_sku": " ", "price": {"sale_price": "100000"}}],
        },
    }


def _flash(day: date, product: str, price: str) -> tuple[dict, dict]:
    activity = {
        "id": f"f-{day.isoformat()}",
        "activity_type": "FLASHSALE",
        "status": "EXPIRED",
        "title": "Flash",
        "begin_time": seconds(day, 0),
        "end_time": seconds(day + timedelta(days=1)),
    }
    detail = {
        "products": [{"id": product, "skus": [{"id": "s1", "activity_price": {"amount": price}}]}]
    }
    return activity, detail


def test_snapshot_reads_the_first_non_blank_seller_sku() -> None:
    snapshot = Snapshot("shop", END, {}, products=_products())
    assert snapshot.seller_sku("p1") == "SM-012"
    assert snapshot.seller_sku("p2") is None
    assert snapshot.seller_sku("missing") is None


def test_promo_products_split_gmv_inside_and_outside_promotion_days() -> None:
    flash_days = LAST[:4]
    activities, details = [], {}
    for day in flash_days:
        activity, detail = _flash(day, "p1", "135000")
        activities.append(activity)
        details[activity["id"]] = detail
    promotions = parse_activities(activities, details)
    snapshot = Snapshot("shop", END, {}, products=_products())
    gmv = {"p1": {d: (300_000.0 if d in flash_days else 100_000.0) for d in WINDOWS.all_days()}}

    rows = promo_products(promotions, WINDOWS, snapshot, gmv, CONFIG)

    assert len(rows) == 1
    row = rows[0]
    assert row.product_id == "p1"
    assert row.kind is PromoKind.FLASH
    assert row.days == 4
    assert row.depth == pytest.approx(1 - 135_000 / 150_000)
    assert row.gmv_in == pytest.approx(300_000)
    assert row.gmv_out == pytest.approx(100_000)


def test_bands_carry_the_promotions_product_count() -> None:
    activity, detail = _flash(LAST[3], "p1", "135000")
    promotions = parse_activities([activity], {activity["id"]: detail})
    (band,) = bands(promotions, [], WINDOWS)
    assert band.product_count == 1


def test_report_holds_daily_gmv_skus_and_promotions(tmp_path: Path) -> None:
    daily = {
        d: [
            DayRow("p1", card=Block(400, 40, 8, 4, 600_000)),
            DayRow("p2", card=Block(200, 10, 2, 1, 100_000)),
        ]
        for d in DAYS
    }
    activity, detail = _flash(LAST[2], "p1", "135000")
    folder = write_snapshot(
        tmp_path / "snap",
        daily,
        products=_products(),
        activities=[activity],
        details={activity["id"]: detail},
    )
    report = build_report(load_snapshot(folder), Ranking.COMBINED_60D).to_dict()

    assert len(report["daily_gmv"]) == len(DAYS)
    assert report["daily_gmv"][DAYS[0].isoformat()] == pytest.approx(700_000)
    assert report["seller_skus"] == {"p1": "SM-012"}
    (promo,) = report["promo_products"]
    assert promo["product_id"] == "p1"
    assert promo["kind"] == "Flash sale"
    assert promo["days"] == 1
    assert promo["gmv_in"] == pytest.approx(600_000)


def test_rankings_name_the_sku_and_the_tagged_products() -> None:
    daily = {
        d: [
            a34_row(
                DayRow(
                    "p1",
                    card=Block(1_000, 60, 12, 6 if d in LAST else 9, 600_000),
                    seller_live=Block(500, 25, 5, 2, 200_000),
                    seller_video=Block(800, 40, 6, 3, 300_000),
                )
            )
        ]
        for d in DAYS
    }
    sessions = [
        {
            "id": "live-1",
            "title": "Tối",
            "start_time": str(seconds(LAST[5], 20)),
            "interaction_performance": {"product_impressions": 9_000, "product_clicks": 600},
            "sales_performance": {"sku_orders": 90, "gmv": {"amount": "9000000"}},
        }
    ]
    snapshot = Snapshot(
        "shop",
        END,
        daily,
        live_sessions=sessions,
        live_products={
            "live-1": {"data": {"products": [{"id": "p1"}, {"id": "p2"}, {"id": "p1"}]}}
        },
        videos=[{"id": "v1", "products": [{"id": "p2"}]}],
        video_products={"v1": {"products": [{"id": "p1"}]}},
        products=_products(),
    )
    assert tagged_products(snapshot.live_products, snapshot.videos, snapshot.video_products) == {
        "live-1": ("p1", "p2"),
        "v1": ("p2", "p1"),
    }
    videos = [VideoWindowCounts("v1", "Review", LAST[2], Counts(5_000, 100, None, 20, 2_000_000))]
    tables = {
        (r.stream.value, r.metric.value): r.payload for r in build_rankings(snapshot, videos=videos)
    }

    card_rows = [*tables[("product_card", "ctor")]["down"], *tables[("product_card", "ctor")]["up"]]
    assert card_rows and all(r["seller_sku"] == "SM-012" for r in card_rows)
    live_rows = [*tables[("seller_live", "ctor")]["down"], *tables[("seller_live", "ctor")]["up"]]
    assert [r["product_ids"] for r in live_rows] == [["p1", "p2"]]
    video_rows = [*tables[("seller_video", "ctr")]["down"], *tables[("seller_video", "ctr")]["up"]]
    assert [r["product_ids"] for r in video_rows] == [["p2", "p1"]]
