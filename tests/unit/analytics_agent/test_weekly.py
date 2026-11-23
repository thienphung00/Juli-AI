"""J8: the free question "tuần sau shop nên làm gì?" -> the weekly analysis, section by section.
Golden scenario on synthetic data (the 22/11 shape: a sale week as last week, two idle days)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent import AskRequest, run, weekly
from juli_backend.services.analytics_agent.types import TEMPLATES
from tests.unit.analytics_agent.fakes import (
    FakeCardEngine,
    FakeEntityData,
    FakeJev,
    FakeLLM,
    ListSink,
    engine_card,
    shop_rows,
    source_rows,
)
from tests.unit.analytics_agent.test_cards import ch
from tests.unit.analytics_agent.test_engine import SHOP, L, full
from tests.unit.analytics_agent.test_routing import intent

YDAY = date(2026, 11, 22)  # today Monday 23/11
CUR0, SALE0, NORM0 = date(2026, 11, 16), date(2026, 11, 9), date(2026, 11, 2)


def _gmv(d: date) -> float:
    return 1500.0 if d >= CUR0 else (3000.0 if d >= SALE0 else 1000.0)


def _orders(d: date) -> float:
    if d in (date(2026, 11, 20), date(2026, 11, 21)):
        return 0.0
    return 7.0 if d >= CUR0 else (15.0 if d >= SALE0 else 5.0)


def _data() -> FakeEntityData:
    first = YDAY - timedelta(days=40)
    shop = shop_rows(first, YDAY, gmv=_gmv, orders=_orders, ads_spend=100.0, ads_gmv=400.0)
    srcs = source_rows(
        first, YDAY, "video", gmv=lambda d: 100.0 if d >= CUR0 else 500.0
    ) + source_rows(first, YDAY, "trang_shop", gmv=200.0)
    prods = [
        {"day": d, "item_id": k, "gmv": g, "orders": 1.0, "units": 1.0}
        for d in (first + timedelta(days=i) for i in range(41))
        for k, g in (("p1", 1200.0), ("p2", 300.0))
    ]
    idle = {date(2026, 11, 20), date(2026, 11, 21)}
    budget = [
        {
            "day": d,
            "spend": 50.0 if d in idle else 100.0,
            "budget": 200.0 if d in idle else 100.0,
        }
        for d in (CUR0 + timedelta(days=i) for i in range(7))
    ]
    pp = {}
    for k, m_now, m_old, cov in (("p1", 10.0, 12.0, 100.0), ("p2", 8.0, 8.0, 60.0)):
        pp[(k, CUR0)] = {"profit": 100.0, "margin_pct": m_now, "coverage_pct": cov, "gmv": 1.0}
        pp[(k, NORM0)] = {"profit": 100.0, "margin_pct": m_old, "coverage_pct": cov, "gmv": 1.0}
    return FakeEntityData(
        shop,
        srcs,
        products=prods,
        names={"p1": "Găng tay sale 11.11", "p2": "Túi đay"},
        cards=[
            {
                "kind": "ads_budget",
                "item_id": None,
                "status": "sent",
                "code": "JC-0001",
                "change_after": "Tăng ngân sách QC",  # the very change the engine drafts
            }
        ],
        entity={
            "campaigns": [
                {
                    "key": "c1",
                    "name": "CDN/01",
                    "spend": 400.0,
                    "gmv": 900.0,
                    "roas": 2.25,
                    "break_even": 3.0,
                    "profit_after_ads": -50.0,
                },
                {
                    "key": "c2",
                    "name": "CDN/02",
                    "spend": 300.0,
                    "gmv": 1800.0,
                    "roas": 6.0,
                    "break_even": 3.2,
                    "profit_after_ads": 200.0,
                },
            ],
            "budget_days": budget,
            "product_profit": pp,
        },
    )


async def _run_plan() -> tuple[ListSink, Any]:
    sink = ListSink()
    llm = FakeLLM({"restated_vi": "Tuần sau nên làm gì", "intents": [intent(question_type="plan")]})
    res = await run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="tuần sau shop nên làm gì?"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(window=ch("last_7d_vs_prev_7d"))),
        sink=sink,
        labels=L,
        data=_data(),
        card_engine=FakeCardEngine(
            per_kind={
                "ads_budget": {"ok": True, "card": {**engine_card(), "title": "Tăng ngân sách QC"}}
            }
        ),
    )
    return sink, res


async def test_weekly_analysis_sections_from_a_free_question() -> None:
    sink, res = await _run_plan()
    sections = {e["title_vi"]: e for e in sink.of("data_answer")}
    assert not sink.of("needs_choice") and not sink.of("unsupported")
    assert res.stop_reasons == ["data_answer"]
    assert len(TEMPLATES) == 5  # no new template: the question is free text
    # 1. this week vs last week vs a NORMAL week (the sale week is not the baseline)
    s1 = sections["16–22/11 so với 09–15/11 và tuần thường 02–08/11"]
    assert s1["window_vi"] == "16/11–22/11 so với 02/11–08/11"
    assert s1["sale_vi"].startswith("Ngày sale: 11/11")
    gmv = s1["rows"][0]
    assert gmv["label_vi"] == "GMV" and "(có ngày sale)" in gmv["detail_vi"]
    assert gmv["delta"]["dir"] == "up"  # 10.500 vs the normal week 7.000, not a collapse vs 21.000
    # 2. ads ROAS vs ROAS hoà vốn
    s2 = sections["Quảng cáo: ROAS so với ROAS hoà vốn"]
    assert s2["rows"][0]["label_vi"] == "CDN/01" and s2["rows"][0]["detail_vi"].startswith(
        "Dưới hoà vốn"
    )
    # 3. under-budget days with 0 orders
    s3 = sections["Ngày chi dưới ngân sách và không có đơn"]
    assert [r["label_vi"] for r in s3["rows"]] == ["20/11", "21/11"]
    # 4. the source that fell
    s4 = sections["Kênh lưu lượng giảm"]
    assert len(s4["rows"]) == 1 and s4["rows"][0]["value_vi"].startswith("▼")
    # 5. products: share, margin change, a title naming an ended deal
    s5 = sections["Sản phẩm: tỷ trọng, biên và tên"]
    first = s5["rows"][0]
    assert first["label_vi"] == "Găng tay sale 11.11"
    assert "80% GMV" in first["detail_vi"] and "biên ▼" in first["detail_vi"]
    assert "“11.11” đã hết" in first["detail_vi"]
    # 6. giá vốn gaps: profit not trusted, ask to fill
    s6 = sections["Thiếu giá vốn: lợi nhuận chưa đáng tin"]
    assert [r["label_vi"] for r in s6["rows"]] == ["Túi đay"]
    assert s6["rows"][0]["value_vi"] == "Hãy điền giá vốn"


async def test_weekly_actions_point_to_existing_cards_or_make_drafts_only() -> None:
    sink, res = await _run_plan()
    acts = {e["title_vi"]: e for e in sink.of("data_answer")}["Việc nên làm tuần sau"]["rows"]
    by_label = {r["label_vi"]: r for r in acts}
    dup = by_label[L.kind("ads_budget")]
    assert (
        dup["value_vi"] == "Đã có thẻ JC-0001" and "trùng" in dup["detail_vi"]
    )  # flagged, not redrafted
    assert by_label[L.kind("ads_roas_target")]["value_vi"] == "Thẻ nháp"
    assert by_label[L.kind("title")]["value_vi"] == "Thẻ nháp"
    cards = sink.of("card")
    assert {c["kind"] for c in cards} == {"ads_roas_target", "title"}
    assert all(c["draft_ref"].startswith("d_") for c in cards)  # drafts: never sent, never executed
    assert {c["kind"] for c in res.cards} == {"ads_roas_target", "title"}


def test_ended_deal_titles() -> None:
    today = date(2026, 11, 23)
    assert weekly.ended_deal_in("Găng tay sale 11.11 giá sốc", today) == "11.11"
    assert weekly.ended_deal_in("Combo 12.12", today) is None  # still ahead
    assert weekly.ended_deal_in("Túi 500ml", today) is None
