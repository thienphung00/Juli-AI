"""P75: the reviewer mask is structural (fail closed) and gives one alias per product.

Observed 29/10 on a masked pin: promotion rows of Phân tích showed real product titles
and a short seller SKU the catalog dictionary did not hold (the report's
``{product_id: title}`` / ``{product_id: seller_sku}`` maps were only masked when the
dictionary knew the value), and one product read different aliases on different pages
(the alias was keyed on the raw title text). Every fixture here is synthetic; the
titles and SKUs are NOT in the mask dictionary, and the serialized masked JSON must not
contain any of them.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from juli_backend.api.routes.demo_analysis import seller_report
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.reviewer.masking import MaskDictionary, mask_payload, title_alias
from juli_backend.services.shop_diagnosis.channels import Counts
from juli_backend.services.shop_diagnosis.heroes import Ranking
from juli_backend.services.shop_diagnosis.rankings import VideoWindowCounts, build_rankings
from juli_backend.services.shop_diagnosis.report import build_report
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, load_snapshot
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.shop_diagnosis import (
    END,
    Block,
    DayRow,
    a34_row,
    seconds,
    window_days,
    write_snapshot,
)

SHOP_NAME = "Cửa hàng Gốm Lam Thử"
P1, P2, P3 = "1729000000000000101", "1729000000000000102", "1729000000000000103"
TITLE_1 = "Bình giữ nhiệt Sao Mai inox 750ml giữ nóng 12 giờ chính hãng"
TITLE_2 = "Cốc sứ Hoa Ban men lam 350ml quà tặng"
TITLE_3 = "Ấm pha trà Tân Lạc gốm 600ml"
SKU_1, SKU_2, SKU_3 = "SM750-T", "HB350-L", "TL600"
VIDEO_TITLE = "Mở hộp bình Sao Mai đi làm"
LIVE_TITLE = "Phiên tối Hoa Ban xả kho"
CREATOR = "co_be_gom_lam_99"
#: None of these may reach a reviewer (none is in the mask dictionary).
SECRETS = (TITLE_1, TITLE_2, TITLE_3, SKU_1, SKU_2, SKU_3, VIDEO_TITLE, LIVE_TITLE, CREATOR)
DAYS = window_days(END)
LAST = DAYS[30:]
PRODUCT_ALIAS = re.compile(r"Sản phẩm \d{3}")


def _empty_dictionary() -> MaskDictionary:
    """A masked pin whose catalog knows none of the fixture's products."""
    shop_id = uuid.uuid4()
    return MaskDictionary(shop_id=shop_id, alias_id=shop_alias_id(shop_id), shop_name=SHOP_NAME)


def _assert_clean(masked: Any) -> str:
    text = json.dumps(masked, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} leaked: {text[:600]}"
    # A title cut short with "…" never survives either.
    assert TITLE_1[:40] not in text
    return text


def _products() -> dict[str, dict]:
    def product(title: str, sku_id: str, seller_sku: str) -> dict:
        price = {"sale_price": "150000"}
        return {"title": title, "skus": [{"id": sku_id, "seller_sku": seller_sku, "price": price}]}

    return {
        P1: product(TITLE_1, P1 + "9", SKU_1),
        P2: product(TITLE_2, P2 + "9", SKU_2),
        P3: product(TITLE_3, P3 + "9", SKU_3),
    }


def _flash(day: date, product: str) -> tuple[dict, dict]:
    activity = {
        "id": f"f-{product}-{day.isoformat()}",
        "activity_type": "FLASHSALE",
        "status": "EXPIRED",
        "title": "Flash",
        "begin_time": seconds(day, 0),
        "end_time": seconds(day, 23),
    }
    sku = {"id": product + "9", "activity_price": {"amount": "120000"}}
    detail = {"products": [{"id": product, "skus": [sku]}]}
    return activity, detail


def _report(tmp_path: Path) -> dict[str, Any]:
    video, live = Block(600, 20, 4, 2, 200_000), Block(400, 30, 6, 3, 250_000)
    daily = {
        d: [
            DayRow(P1, card=Block(900, 50, 10, 5, 700_000), seller_video=video),
            DayRow(P2, card=Block(500, 20, 4, 2, 300_000), seller_live=live),
            DayRow(P3, card=Block(300, 9, 2, 1, 90_000)),
        ]
        for d in DAYS
    }
    activities, details = [], {}
    for product, day in ((P1, LAST[2]), (P2, LAST[4]), (P3, LAST[6])):
        activity, detail = _flash(day, product)
        activities.append(activity)
        details[activity["id"]] = detail
    folder = write_snapshot(
        tmp_path / "snap",
        daily,
        shop_name=SHOP_NAME,
        products=_products(),
        activities=activities,
        details=details,
    )
    return seller_report(build_report(load_snapshot(folder), Ranking.COMBINED_60D).to_dict())


# -- Phân tích: the report and its ranking tables -----------------------------------------


def test_analysis_report_masks_titles_and_skus_the_catalog_does_not_know(tmp_path):
    report = _report(tmp_path)
    raw = json.dumps(report, ensure_ascii=False)
    assert TITLE_1 in raw and SKU_1 in raw  # the fixture really carries them
    assert {row["product_id"] for row in report["promo_products"]} == {P1, P2, P3}

    response = {"as_of": END.isoformat(), "built_at": "x", "ranking": "60d", "report": report}
    masked = mask_payload(response, _empty_dictionary())
    _assert_clean(masked)
    titles = masked["report"]["titles"]
    skus = masked["report"]["seller_skus"]
    for row in masked["report"]["promo_products"]:
        # The promotions table reads each row's name / SKU from these maps by product id.
        assert PRODUCT_ALIAS.fullmatch(titles[row["product_id"]])
        assert re.fullmatch(r"an-sku-[0-9a-f]{8}", skus[row["product_id"]])
    # One alias per product: keyed on the product id, not on its title text.
    assert sorted(titles.values()) == sorted(title_alias("product", p) for p in (P1, P2, P3))
    # Magnitudes stay real.
    assert [r["gmv_in"] for r in masked["report"]["promo_products"]] == [
        r["gmv_in"] for r in report["promo_products"]
    ]


def test_ranking_tables_mask_product_video_and_live_rows_by_key():
    daily = {
        d: [
            a34_row(
                DayRow(
                    P1,
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
            "id": "7300000000000000001",
            "title": LIVE_TITLE,
            "start_time": str(seconds(LAST[5], 20)),
            "interaction_performance": {"product_impressions": 9_000, "product_clicks": 600},
            "sales_performance": {"sku_orders": 90, "gmv": {"amount": "9000000"}},
        }
    ]
    snapshot = Snapshot(
        SHOP_NAME,
        END,
        daily,
        live_sessions=sessions,
        live_products={"7300000000000000001": {"data": {"products": [{"id": P1}]}}},
        videos=[{"id": "7400000000000000001", "products": [{"id": P1}]}],
        video_products={"7400000000000000001": {"products": [{"id": P1}]}},
        products=_products(),
    )
    videos = [
        VideoWindowCounts(
            "7400000000000000001", VIDEO_TITLE, LAST[2], Counts(5_000, 100, None, 20, 2_000_000)
        )
    ]
    tables = build_rankings(snapshot, videos=videos)
    assert tables
    names: list[str] = []
    for table in tables:
        response = {
            "stream": table.stream.value,
            "metric": table.metric.value,
            "ranking": table.payload,
        }
        masked = mask_payload(response, _empty_dictionary())
        _assert_clean(masked)
        for side in ("down", "up"):
            names += [row["name"] for row in masked["ranking"].get(side) or []]
    assert names
    assert all(re.fullmatch(r"(Sản phẩm|Video|LIVE) \d{3}", name) for name in names), names


async def test_reviewer_analysis_route_masks_report_titles_not_in_the_catalog(
    session, monkeypatch, tmp_path
):
    """Through the real middleware: the report holds products the catalog never had."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    rv.reset_caches()
    ref = await rv.seed_reference_shop(session)
    session.add(
        ShopDiagnosisReport(
            shop_id=ref.shop.id,
            end_date=END,
            ranking="60d",
            report=_report(tmp_path),
            built_at=datetime(2026, 10, 10),
        )
    )
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ref.shop.id))
    user_id = await rv.make_reviewer(session)
    headers = {
        "Authorization": f"Bearer {rv.token(user_id)}",
        "X-Shop-Id": str(shop_alias_id(ref.shop.id)),
    }
    try:
        async with client_for(build_app(session)) as client:
            response = await client.get("/v1/demo/analysis", headers=headers)
    finally:
        rv.reset_caches()
    assert response.status_code == 200, response.text
    for secret in SECRETS:
        assert secret not in response.text
    titles = response.json()["report"]["titles"]
    assert titles and all(PRODUCT_ALIAS.fullmatch(t) for t in titles.values())


# -- Quyết định, runs, content analysis, shops -------------------------------------------


def _route_payloads() -> dict[str, Any]:
    short = TITLE_1[:59].rstrip() + "…"
    return {
        "decisions": {
            "data": [
                {
                    "id": str(uuid.uuid4()),
                    "title": f"Kịch bản video mới · {short}",
                    "description": f"CTR video thấp. Sản phẩm {SKU_1} cần kịch bản mới.",
                    "recommendation": {
                        "card": {
                            "seller_sku": SKU_1,
                            "seller_sku_more": 3,
                            "product_title": TITLE_1,
                            "reason_full": f"Video của {TITLE_1} có CTR thấp.",
                            "content": {
                                "will_draft": [f"Kịch bản cho {SKU_1}"],
                                "measure": "",
                                "sources": [
                                    {
                                        "video_id": "7400000000000000002",
                                        "title": VIDEO_TITLE,
                                        "date": "2026-10-02",
                                    }
                                ],
                            },
                        },
                        "diagnosis": {"product_title": TITLE_2, "tiktok_product_id": P2},
                    },
                }
            ]
        },
        "runs": {
            "data": [
                {"id": str(uuid.uuid4()), "product_name": TITLE_3, "latest_narration": "Đang sửa"}
            ]
        },
        "run_detail": {
            "data": {
                "product_name": TITLE_2,
                "content": {
                    "product_label": SKU_2,
                    "product_title": TITLE_2,
                    "script": {"sku": SKU_3, "name": TITLE_3},
                    "basket_skus": [SKU_1, SKU_3],
                    "creator_name": CREATOR,
                },
                "promotion": {"proposal": {"skus": [{"sku_code": SKU_3, "sku_name": TITLE_3}]}},
            }
        },
        "content_analysis": {
            "data": [
                {"tiktok_product_id": P1, "product_title": TITLE_1, "video_title": VIDEO_TITLE}
            ]
        },
        "lives": {"data": [{"live_id": "7300000000000000001", "title": LIVE_TITLE}]},
    }


@pytest.mark.parametrize("route", sorted(_route_payloads()))
def test_every_reviewer_route_shape_masks_identities_by_key(route):
    masked = mask_payload(_route_payloads()[route], _empty_dictionary())
    _assert_clean(masked)


def test_content_card_source_reads_a_video_alias():
    masked = mask_payload(_route_payloads()["decisions"], _empty_dictionary())
    (source,) = masked["data"][0]["recommendation"]["card"]["content"]["sources"]
    assert source["title"] == title_alias("video", "7400000000000000002")
    assert source["date"] == "2026-10-02"


# -- one alias per product -----------------------------------------------------------------


def test_one_alias_per_product_across_pages_and_spellings():
    shop_id = uuid.uuid4()
    juli_id = str(uuid.uuid4())
    catalog = MaskDictionary(
        shop_id=shop_id,
        alias_id=shop_alias_id(shop_id),
        shop_name=SHOP_NAME,
        titles={TITLE_1: "product"},
        ids={P1: "product", SKU_1: "sku"},
        product_refs={TITLE_1: P1, juli_id: P1, SKU_1: P1},
    )
    expected = title_alias("product", P1)
    # Quyết định (catalog title + id), Phân tích (another spelling, by product id),
    # a run (only the Juli id), a card that names only its SKU, free text.
    decision = mask_payload({"product_title": TITLE_1, "tiktok_product_id": P1}, catalog)
    report = mask_payload({"titles": {P1: TITLE_1 + " (mẫu mới)"}}, catalog)
    run = mask_payload({"product_id": juli_id, "product_name": "Tên cũ của bình"}, catalog)
    card = mask_payload({"seller_sku": SKU_1, "product_title": "Bình 750ml"}, catalog)
    text = mask_payload({"reason": f"Video của {TITLE_1} có CTR thấp."}, catalog)
    assert decision["product_title"] == expected
    assert list(report["titles"].values()) == [expected]
    assert run["product_name"] == expected
    assert card["product_title"] == expected
    assert text["reason"] == f"Video của {expected} có CTR thấp."


def test_two_products_sharing_a_title_get_two_aliases():
    rows = [
        {"tiktok_product_id": P1, "product_title": TITLE_2},
        {"tiktok_product_id": P2, "product_title": TITLE_2},
    ]
    masked = mask_payload({"data": rows}, _empty_dictionary())
    first, second = (row["product_title"] for row in masked["data"])
    assert first != second and PRODUCT_ALIAS.fullmatch(first) and PRODUCT_ALIAS.fullmatch(second)


async def test_catalog_maps_each_product_reference_to_its_tiktok_id(session):
    reviewer_catalog.forget_cached()
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    dictionary = await reviewer_catalog.load_dictionary(session, ref.shop)
    refs = dictionary.product_refs
    assert refs[str(ref.product.id)] == rv.TIKTOK_PRODUCT_ID
    assert refs[rv.PRODUCT_TITLE] == rv.TIKTOK_PRODUCT_ID
    assert refs[rv.SELLER_SKU] == rv.TIKTOK_PRODUCT_ID
    assert refs[rv.TIKTOK_SKU_ID] == rv.TIKTOK_PRODUCT_ID
    reviewer_catalog.forget_cached()


def test_reviewer_aliases_stay_neutral():
    masked = mask_payload(_route_payloads(), _empty_dictionary())
    text = json.dumps(masked, ensure_ascii=False)
    assert "demo" not in text.lower()
