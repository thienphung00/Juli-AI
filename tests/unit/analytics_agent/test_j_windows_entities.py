"""Track J (batch-1123-a): one window per phrase, window kept across a choice, no metric picker
when a metric is named, an entity-labelled answer never carries a shop number. Synthetic data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, windows
from juli_backend.services.analytics_agent.routing import decide, entity_kind
from tests.unit.analytics_agent.fakes import (
    FakeData,
    FakeEntityData,
    FakeJev,
    FakeLLM,
    shop_rows,
)
from tests.unit.analytics_agent.test_cards import ch, nl
from tests.unit.analytics_agent.test_engine import SHOP, full, go
from tests.unit.analytics_agent.test_routing import ans, intent

SAT = date(2026, 11, 21)  # newest complete DATA day in the 22/11 scenario
YDAY = date(2026, 11, 22)  # as_of when today is Monday 23/11 (VN)


@pytest.mark.parametrize("phrase", ["tuần trước", "last week", "previous week", "tuần vừa rồi"])
def test_three_phrasings_of_last_week_are_one_window(phrase: str) -> None:
    preset = windows.window_from_phrase(phrase)
    w = windows.build_windows(preset or "", windows.anchor_for(preset or "", YDAY, SAT))
    assert preset == "last_full_week_vs_week_before"
    assert w.cur == (date(2026, 11, 16), YDAY)  # calendar, although the data ends 21/11
    assert w.prev == (date(2026, 11, 9), date(2026, 11, 15))


def test_this_week_is_monday_to_yesterday_against_the_same_days_last_week() -> None:
    wed = date(2026, 11, 25)  # today Thursday 26/11
    w = windows.build_windows(windows.window_from_phrase("tuần này") or "", wed)
    assert w.cur == (date(2026, 11, 23), wed)
    assert w.prev == (date(2026, 11, 16), date(2026, 11, 18))
    assert windows.this_week_empty(YDAY) and not windows.this_week_empty(wed)


def test_last_7_days_are_the_last_seven_complete_calendar_days() -> None:
    p = windows.window_from_phrase("7 ngày qua") or ""
    w = windows.build_windows(p, windows.anchor_for(p, YDAY, SAT))
    assert w.cur == (date(2026, 11, 16), YDAY) and w.prev == (date(2026, 11, 9), date(2026, 11, 15))


def test_sale_days_are_double_days_15th_and_25th() -> None:
    got = windows.campaign_days(date(2026, 11, 9), date(2026, 11, 26))
    assert got == [date(2026, 11, 11), date(2026, 11, 15), date(2026, 11, 25)]
    w = windows.build_windows("last_full_week_vs_week_before", date(2026, 11, 22))
    assert any(f.startswith("contains_campaign_day:11/11,15/11") for f in w.flags)


def test_named_metric_and_window_phrase_skip_the_pickers() -> None:
    it = intent(metric_phrase="advertising spend", time_phrase="last week")
    a = ans(
        chain=ch("orders_change", 0.4, "gmv_change"),
        window=ch("last_7d_vs_prev_7d", 0.5, "last_30d_vs_prev_30d"),
        metric_named=nl(0.1),
    )
    dec = decide(it, a)
    assert dec["outcome"] == "go"
    assert dec["chain"] == "ads_change" and dec["metric"] == "ads_spend"
    assert dec["window"] == "last_full_week_vs_week_before"


@pytest.mark.parametrize(
    ("kw", "kind"),
    [
        ({"entity_phrase": "đơn dùng voucher"}, "voucher"),
        ({"source_phrase": "Tiếp thị liên kết"}, "affiliate"),
        ({"entity_phrase": "chiến dịch A"}, "campaign"),
        ({"metric_phrase": "revenue"}, None),
    ],
)
def test_entity_kind(kw: dict[str, Any], kind: str | None) -> None:
    assert entity_kind(intent(**kw)) == kind


def _week_rows(ordr: float, gmv: float, cost: float, **kw: Any) -> list[dict[str, Any]]:
    """One entity row per day of 16-22/11 (this week) and 9-15/11 (the week before)."""
    return [
        {"day": d, "orders": ordr, "gmv": gmv, "cost": cost, **kw}
        for d in (YDAY - timedelta(days=k) for k in range(14))
    ]


def _lookup_jev(metric: str = "orders") -> FakeJev:
    return FakeJev(
        lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"), metric=ch(metric))
    )


async def _ask(
    data: FakeEntityData, it: dict[str, Any], jev: FakeJev | None = None
) -> tuple[Any, Any]:
    llm = FakeLLM({"restated_vi": "câu hỏi", "intents": [it]})
    r = AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q")
    return await go(r, llm=llm, jev=jev or _lookup_jev(), data=data)


def _shop() -> list[dict[str, Any]]:
    return shop_rows(YDAY - timedelta(days=60), YDAY, gmv=1000.0, orders=30.0)


async def test_voucher_orders_are_the_voucher_orders_not_the_shop_orders() -> None:
    data = FakeEntityData(
        _shop(),
        entity={
            "voucher": _week_rows(2.0, 400.0, 20.0),
            "voucher_codes": [
                {"code": "VC-A", "orders": 9, "gmv": 900.0, "cost": 90.0},
                {"code": "VC-B", "orders": 5, "gmv": 300.0, "cost": 15.0},
            ],
        },
    )
    sink, res = await _ask(
        data,
        intent(
            question_type="status",
            metric_phrase="orders",
            entity_phrase="voucher",
            time_phrase="last week",
        ),
    )
    tot, rows = sink.of("data_answer")
    assert tot["title_vi"].startswith("Đơn dùng voucher") and tot["value"] == "14"  # 2 x 7, not 210
    assert tot["window_vi"].startswith("16/11–22/11")
    assert [r["label_vi"] for r in rows["rows"]] == ["VC-A", "VC-B"]
    assert res.stop_reasons == ["data_answer"] and not sink.of("path")


async def test_voucher_cost_is_a_cost_line_from_the_voucher_rows() -> None:
    data = FakeEntityData(_shop(), entity={"voucher": _week_rows(2.0, 400.0, 20.0)})
    sink, _ = await _ask(
        data,
        intent(
            question_type="status",
            metric_phrase="voucher cost",
            entity_phrase="voucher",
            time_phrase="last week",
        ),
    )
    tot = sink.of("data_answer")[0]
    assert tot["title_vi"].startswith("Chi phí voucher (Ưu đãi)") and tot["value"] == "140đ"


async def test_affiliate_orders_come_from_affiliate_rows() -> None:
    data = FakeEntityData(_shop(), entity={"affiliate": _week_rows(1.0, 100.0, 5.0)})
    sink, _ = await _ask(
        data,
        intent(
            question_type="status",
            metric_phrase="orders",
            source_phrase="Tiếp thị liên kết",
            time_phrase="last week",
        ),
    )
    tot = sink.of("data_answer")[0]
    assert tot["title_vi"].startswith("Đơn từ Tiếp thị liên kết") and tot["value"] == "7"


CAMPS = [
    {
        "key": "c1",
        "name": "CDN/01",
        "spend": 100.0,
        "gmv": 250.0,
        "roas": 2.5,
        "break_even": 3.0,
        "profit_after_ads": -20.0,
    },
    {
        "key": "c2",
        "name": "CDN/02",
        "spend": 100.0,
        "gmv": 600.0,
        "roas": 6.0,
        "break_even": 3.2,
        "profit_after_ads": 90.0,
    },
]


async def test_campaign_rows_show_roas_against_break_even_and_loss_filter() -> None:
    data = FakeEntityData(_shop(), entity={"campaigns": CAMPS})
    sink, _ = await _ask(
        data,
        intent(question_type="status", entity_phrase="campaign", metric_phrase="roas"),
        _lookup_jev("roas"),
    )
    rows = sink.of("data_answer")[0]["rows"]
    assert [r["label_vi"] for r in rows] == ["CDN/01", "CDN/02"]
    assert rows[0]["value_vi"] == "ROAS 2,50 · hoà vốn 3,00"
    sink2, _ = await _ask(
        data,
        intent(
            question_type="status",
            entity_phrase="campaign",
            metric_phrase="which campaigns lose money",
        ),
        _lookup_jev("roas"),
    )
    loss = sink2.of("data_answer")[0]
    assert loss["title_vi"] == "Chiến dịch dưới ROAS hoà vốn"
    assert [r["label_vi"] for r in loss["rows"]] == ["CDN/01"]


async def test_entity_without_data_is_refused_never_the_shop_total() -> None:
    data = FakeEntityData(_shop(), entity={})  # no campaign rows
    sink, res = await _ask(
        data,
        intent(question_type="status", entity_phrase="campaign", metric_phrase="roas"),
        _lookup_jev("roas"),
    )
    assert sink.of("label")[0]["text_vi"] == "Juli chưa có số liệu này"
    assert not sink.of("data_answer") and res.stop_reasons == ["data_missing"]


async def test_entity_answer_never_carries_the_shop_total() -> None:
    """Guard: shop orders are 30/day (210 a week); an entity answer must never show them."""
    data = FakeEntityData(
        _shop(),
        entity={"voucher": _week_rows(2.0, 400.0, 20.0), "affiliate": _week_rows(1.0, 1, 1)},
    )
    for it in (
        intent(question_type="status", metric_phrase="orders", entity_phrase="voucher"),
        intent(question_type="status", metric_phrase="orders", source_phrase="affiliate"),
    ):
        sink, _ = await _ask(data, it)
        assert all(a.get("value") not in ("210", "30") for a in sink.of("data_answer"))


async def test_product_profit_is_that_products_profit_or_refused() -> None:
    wk = YDAY - timedelta(days=6)
    pp = {
        ("p1", wk): {"profit": 5000.0, "margin_pct": 12.5, "coverage_pct": 100.0, "gmv": 40000.0},
        ("p1", wk - timedelta(days=7)): {
            "profit": 4000.0,
            "margin_pct": 10.0,
            "coverage_pct": 100.0,
            "gmv": 40000.0,
        },
    }
    data = FakeEntityData(_shop(), names={"p1": "Sản phẩm A"}, entity={"product_profit": pp})
    it = intent(question_type="status", metric_phrase="profit", product_phrase="Sản phẩm A")
    jev = FakeJev(
        lambda s, q: full(
            mode=ch("lookup"),
            lookup=ch("metric_total"),
            metric=ch("profit"),
            scope=ch("product"),
            product_named=nl(0.9),
            product=ch("p1"),
            window=ch("last_7d_vs_prev_7d"),
        )
    )
    sink, _ = await _ask(
        FakeEntityData(
            _shop(),
            names={"p1": "Sản phẩm A"},
            entity={"product_profit": pp},
            catalog=[{"item_id": "p1", "name": "Sản phẩm A"}],
        ),
        it,
        jev,
    )
    tot = sink.of("data_answer")[0]
    assert tot["title_vi"] == "Lợi nhuận · Sản phẩm A" and tot["value"] == "5.000đ"
    sink2, _ = await _ask(
        FakeEntityData(
            _shop(),
            names={"p1": "Sản phẩm A"},
            entity={},
            catalog=[{"item_id": "p1", "name": "Sản phẩm A"}],
        ),
        it,
        jev,
    )
    assert sink2.of("label")[0]["text_vi"] == "Juli chưa có số liệu này" and not sink2.of(
        "data_answer"
    )
    assert data is not None


async def test_window_chosen_is_the_window_run_and_freshness_is_the_newest_complete_day() -> None:
    # today is Monday 23/11; the data ends 21/11: the window stays 16-22, the freshness says 21/11
    shop = shop_rows(SAT - timedelta(days=60), SAT, gmv=1000.0, orders=3.0)
    llm = FakeLLM(
        {
            "restated_vi": "Doanh thu bao nhiêu",
            "intents": [intent(question_type="status", metric_phrase="revenue")],
        }
    )
    jev = FakeJev(
        lambda s, q: full(
            mode=ch("lookup"),
            lookup=ch("metric_total"),
            metric=ch("gmv"),
            window=ch("last_full_week_vs_week_before", 0.55, "last_7d_vs_prev_7d"),
        )
    )
    r = AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q")
    sink, _ = await go(r, llm=llm, jev=jev, data=FakeData(shop))
    nc = sink.of("needs_choice")[0]
    assert nc["pending"]["anchor"] == YDAY.isoformat()
    shown = nc["options"][0]["label_vi"]
    assert shown == "16/11–22/11 so với 09/11–15/11"
    r2 = AskRequest(
        shop_id=SHOP,
        platform="shopee",
        as_of=YDAY + timedelta(days=1),  # the clock moved on; the pinned anchor wins
        choice={"item": "window", "value": "last_full_week_vs_week_before"},
        pending=nc["pending"],
    )
    sink2, _ = await go(
        r2, llm=FakeLLM(None), jev=FakeJev(lambda s, q: full()), data=FakeData(shop)
    )
    da = sink2.of("data_answer")[0]
    assert da["window_vi"] == shown and da["fresh_vi"] == "Số liệu đến hết 21/11"


async def test_this_week_on_a_monday_offers_last_week_not_a_one_day_window() -> None:
    shop = shop_rows(SAT - timedelta(days=60), YDAY, gmv=1000.0, orders=3.0)
    llm = FakeLLM(
        {
            "restated_vi": "Doanh thu tuần này",
            "intents": [
                intent(question_type="status", metric_phrase="revenue", time_phrase="this week")
            ],
        }
    )
    jev = FakeJev(lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"), metric=ch("gmv")))
    sink, res = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q"),
        llm=llm,
        jev=jev,
        data=FakeData(shop),
    )
    nc = sink.of("needs_choice")[0]
    assert nc["question_vi"] == "Tuần này chưa có ngày nào đủ số liệu. Xem tuần trước?"
    assert [o["value"] for o in nc["options"]] == ["last_full_week_vs_week_before"]
    assert not sink.of("data_answer") and res.stop_reasons == ["needs_choice"]


async def test_vietnamese_named_metric_and_week_answer_directly() -> None:
    """J3: "chi phí quảng cáo tuần trước" — the fake parser output the Vietnamese prompt gives."""
    shop = shop_rows(
        YDAY - timedelta(days=40), YDAY, gmv=1000.0, orders=3.0, ads_spend=100.0, ads_gmv=500.0
    )
    llm = FakeLLM(
        {
            "restated_vi": "Chi phí quảng cáo tuần trước",
            "intents": [
                intent(
                    question_type="status",
                    metric_phrase="advertising spend",
                    time_phrase="last week",
                )
            ],
        }
    )
    jev = FakeJev(
        lambda s, q: full(
            mode=ch("lookup"),
            lookup=ch("metric_total"),
            metric=ch("ads_spend", 0.4, "gmv"),
            chain=ch("ads_change", 0.4, "gmv_change"),
            metric_named=nl(0.1),
            window=ch("last_7d_vs_prev_7d", 0.5, "last_30d_vs_prev_30d"),
        )
    )
    sink, res = await go(
        AskRequest(
            shop_id=SHOP, platform="shopee", as_of=YDAY, text="chi phí quảng cáo tuần trước"
        ),
        llm=llm,
        jev=jev,
        data=FakeData(shop),
    )
    assert not sink.of("needs_choice") and res.stop_reasons == ["data_answer"]
    da = sink.of("data_answer")[0]
    assert da["window_vi"].startswith("16/11–22/11")
