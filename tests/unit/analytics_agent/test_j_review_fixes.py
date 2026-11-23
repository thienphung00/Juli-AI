"""Verifier findings D1-D6 (batch-1123-a, Track J)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, fmt, windows
from juli_backend.services.analytics_agent.chains import run_chain
from juli_backend.services.analytics_agent.routing import entity_kind
from tests.unit.analytics_agent.fakes import FakeData, FakeEntityData, FakeJev, FakeLLM, shop_rows
from tests.unit.analytics_agent.test_cards import ch
from tests.unit.analytics_agent.test_engine import SHOP, full, go
from tests.unit.analytics_agent.test_routing import intent

YDAY = date(2026, 11, 22)  # today Monday 23/11 (VN)
CUR0, SALE0 = date(2026, 11, 16), date(2026, 11, 9)


# ------------------------------------------------------------------ D1 entity words
@pytest.mark.parametrize(
    ("kw", "kind"),
    [
        ({"raw_text": "phí hoa hồng tuần trước là bao nhiêu"}, None),  # a Shopee fee
        ({"raw_text": "phí cố định tháng này"}, None),
        ({"metric_phrase": "commission fee"}, None),
        ({"raw_text": "hoa hồng TTLK tuần trước"}, "affiliate"),
        ({"raw_text": "đơn từ KOC"}, "affiliate"),
        ({"raw_text": "hoa hồng tiếp thị liên kết"}, "affiliate"),
        ({"raw_text": "chiến dịch quảng cáo nào lỗ"}, "campaign"),
        ({"raw_text": "chiến dịch DVHT nào lỗ"}, "campaign"),
        ({"raw_text": "chiến dịch nào hiệu quả"}, None),  # a campaign alone is not an ad campaign
        ({"raw_text": "khuyến mãi tuần này thế nào"}, None),  # not a voucher
        ({"raw_text": "doanh thu Flash Sale Của Shop"}, "program"),
        ({"raw_text": "đơn Combo Khuyến Mãi"}, "program"),
        ({"raw_text": "đơn dùng mã giảm giá"}, "voucher"),
        ({"raw_text": "đơn dùng voucher"}, "voucher"),
    ],
)
def test_entity_words_scan_the_raw_question(kw: dict[str, Any], kind: str | None) -> None:
    assert entity_kind(intent(**kw)) == kind


async def test_a_named_programme_with_no_reader_is_refused() -> None:
    data = FakeEntityData(shop_rows(YDAY - timedelta(days=60), YDAY, gmv=1000.0, orders=30.0))
    llm = FakeLLM(
        {"restated_vi": "x", "intents": [intent(question_type="status", metric_phrase="orders")]}
    )
    sink, res = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="đơn Flash Sale Của Shop"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"))),
        data=data,
    )
    assert sink.of("label")[0]["text_vi"] == "Juli chưa có số liệu này"
    assert not sink.of("data_answer") and res.stop_reasons == ["data_missing"]


async def test_a_fee_question_is_not_answered_as_affiliate() -> None:
    data = FakeEntityData(
        shop_rows(YDAY - timedelta(days=60), YDAY, gmv=1000.0, orders=30.0),
        entity={"affiliate": [{"day": YDAY, "orders": 1, "gmv": 5.0, "cost": 1.0}]},
    )
    llm = FakeLLM(
        {
            "restated_vi": "phí hoa hồng",
            "intents": [intent(question_type="status", metric_phrase="orders")],
        }
    )
    sink, _ = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="phí hoa hồng tuần trước"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"))),
        data=data,
    )
    assert all("Tiếp thị liên kết" not in a["title_vi"] for a in sink.of("data_answer"))


# ------------------------------------------------------------------ D2 chains are sale-aware
def _gmv(d: date) -> float:
    return 3000.0 if SALE0 <= d < CUR0 else 1000.0  # 11.11 week high; last week = a normal week


async def test_why_question_on_the_monday_after_11_11_is_not_a_collapse() -> None:
    shop = shop_rows(YDAY - timedelta(days=60), YDAY, gmv=_gmv, orders=lambda d: _gmv(d) / 200)
    d = FakeData(shop)
    r = await run_chain(d, "gmv_change", "gmv", "last_full_week_vs_week_before", YDAY)
    assert r.windows.cur == (CUR0, YDAY)
    assert r.windows.prev == (date(2026, 11, 2), date(2026, 11, 8))  # not the 11.11 week
    assert r.stop_reason == "within_noise"  # flat against a normal week
    llm = FakeLLM(
        {
            "restated_vi": "Vì sao GMV giảm tuần trước",
            "intents": [
                intent(
                    question_type="why_changed",
                    metric_phrase="revenue",
                    time_phrase="last week",
                )
            ],
        },
        text="x",
    )
    sink, _ = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="vì sao GMV giảm tuần trước"),
        llm=llm,
        jev=FakeJev(lambda s, q: full(mode=ch("why"), chain=ch("gmv_change"), metric=ch("gmv"))),
        data=d,
    )
    assert sink.of("label")[0]["text_vi"] == "Không phát hiện gì bất thường"
    assert any("02/11–08/11" in e.get("text_vi", "") for e in sink.of("status"))


def test_window_options_are_sale_aware_for_every_mode() -> None:
    from juli_backend.services.analytics_agent import routing, shopee_labels

    ev = routing.needs_choice_event(
        {"remaining": [("window", ["last_full_week_vs_week_before"])], "mode": "why"},
        intent(),
        shopee_labels(),
        YDAY,
    )
    assert ev["options"][0]["label_vi"] == "16/11–22/11 so với 02/11–08/11"


# ------------------------------------------------------------------ D4 / D5 entity metrics
def _entity_data() -> FakeEntityData:
    # shop: 30 orders and 1.000đ a day -> 210 orders, 7.000đ, AOV 33; entities differ
    shop = shop_rows(YDAY - timedelta(days=60), YDAY, gmv=1000.0, orders=30.0)

    def rows(o: float, g: float, c: float) -> list[dict[str, Any]]:
        return [
            {"day": YDAY - timedelta(days=k), "orders": o, "gmv": g, "cost": c} for k in range(14)
        ]

    return FakeEntityData(
        shop,
        entity={
            "voucher": rows(2.0, 400.0, 20.0),
            "affiliate": rows(1.0, 150.0, 9.0),
            "voucher_codes": [{"code": "VC-A", "orders": 9, "gmv": 900.0, "cost": 90.0}],
            "campaigns": [
                {
                    "key": "c1",
                    "name": "CDN/01",
                    "spend": 100.0,
                    "gmv": 250.0,
                    "roas": 2.5,
                    "break_even": 3.0,
                    "profit_after_ads": -20.0,
                }
            ],
            "product_profit": {
                ("p1", YDAY - timedelta(days=6)): {
                    "profit": 5000.0,
                    "margin_pct": 12.5,
                    "coverage_pct": 100.0,
                    "gmv": 40000.0,
                },
                ("p1", YDAY - timedelta(days=13)): {
                    "profit": 4000.0,
                    "margin_pct": 10.0,
                    "coverage_pct": 100.0,
                    "gmv": 40000.0,
                },
            },
        },
        names={"p1": "Sản phẩm A"},
        catalog=[{"item_id": "p1", "name": "Sản phẩm A"}],
    )


def _jev(metric: str, **over: Any) -> FakeJev:
    return FakeJev(
        lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"), metric=ch(metric), **over)
    )


async def _ask(it: dict[str, Any], metric: str, **over: Any) -> Any:
    llm = FakeLLM({"restated_vi": "câu hỏi", "intents": [it]})
    sink, _ = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q"),
        llm=llm,
        jev=_jev(metric, **over),
        data=_entity_data(),
    )
    return sink


@pytest.mark.parametrize("kind", ["voucher", "affiliate"])
@pytest.mark.parametrize(
    ("metric", "phrase", "expected", "title_start"),
    [
        ("orders", "orders", "14", "Đơn"),
        ("gmv", "revenue", None, "GMV đơn"),
        ("aov", "average order value", None, "AOV đơn"),
        ("orders", "cost", None, None),  # cost: the voucher cost / the commission
    ],
)
async def test_entity_answers_the_asked_metric_under_its_own_label(
    kind: str, metric: str, phrase: str, expected: str | None, title_start: str | None
) -> None:
    ent = "voucher" if kind == "voucher" else "affiliate"
    sink = await _ask(
        intent(
            question_type="status",
            metric_phrase=phrase,
            entity_phrase=ent,
            time_phrase="last week",
        ),
        metric,
    )
    tot = sink.of("data_answer")[0]
    if title_start:
        assert tot["title_vi"].startswith(title_start)
    if phrase == "revenue":
        assert tot["value"] == fmt.value("gmv", 2800.0 if kind == "voucher" else 1050.0)
    if phrase == "average order value":
        assert tot["value"] == fmt.value("aov", 200.0 if kind == "voucher" else 150.0)
    if phrase == "cost":
        assert "Chi phí voucher" in tot["title_vi"] or "Hoa hồng" in tot["title_vi"]
    if expected and kind == "voucher":
        assert tot["value"] == expected


@pytest.mark.parametrize("kind", ["voucher", "affiliate"])
async def test_a_metric_the_entity_does_not_have_is_refused(kind: str) -> None:
    sink = await _ask(
        intent(
            question_type="status",
            metric_phrase="click-through rate",
            entity_phrase=kind,
            time_phrase="last week",
        ),
        "ctr",
    )
    assert sink.of("label")[0]["text_vi"] == "Juli chưa có số liệu này"
    assert not sink.of("data_answer")


def _texts(sink: Any) -> list[str]:
    out: list[str] = []
    for a in sink.of("data_answer"):
        out += [str(a.get("value", "")), str(a.get("value_raw", ""))]
        for r in a.get("rows") or []:
            out += [str(r.get("value_vi", "")), str(r.get("detail_vi", ""))]
    return out


SHOP_TOTALS = {
    "orders": 210.0,
    "gmv": 7000.0,
    "aov": 7000.0 / 210.0,
}


def _forbidden() -> set[str]:
    bad: set[str] = set()
    for m, v in SHOP_TOTALS.items():
        bad |= {str(v), str(int(v)), fmt.value(m, v), f"{v:.1f}"}
    bad.add(fmt.value("margin", 0.0))
    return bad


@pytest.mark.parametrize("kind", ["voucher", "affiliate"])
@pytest.mark.parametrize(
    ("metric", "phrase"),
    [
        ("orders", "orders"),
        ("gmv", "revenue"),
        ("aov", "average order value"),
        ("orders", "cost"),
        ("profit", "profit"),
        ("ctr", "click-through rate"),
    ],
)
async def test_no_entity_answer_ever_equals_the_shop_total(
    kind: str, metric: str, phrase: str
) -> None:
    sink = await _ask(
        intent(
            question_type="status",
            metric_phrase=phrase,
            entity_phrase=kind,
            time_phrase="last week",
        ),
        metric,
    )
    bad = _forbidden()
    assert not (set(_texts(sink)) & bad), (kind, metric, _texts(sink))


async def test_campaign_and_product_answers_never_equal_the_shop_total() -> None:
    sink = await _ask(
        intent(question_type="status", entity_phrase="ad campaign", metric_phrase="roas"), "roas"
    )
    assert not (set(_texts(sink)) & _forbidden())
    sink2 = await _ask(
        intent(
            question_type="status",
            metric_phrase="profit",
            product_phrase="Sản phẩm A",
            time_phrase="7 days",
        ),
        "profit",
        scope=ch("product"),
        product_named={"type": "noul", "noul": 0.9},
        product=ch("p1"),
    )
    assert not (set(_texts(sink2)) & _forbidden())
    assert sink2.of("data_answer")[0]["title_vi"] == "Lợi nhuận · Sản phẩm A"


# ------------------------------------------------------------------ D6 calendar windows
def test_calendar_phrases_follow_today_not_the_data() -> None:
    latest = date(2026, 11, 18)  # data is short; windows still follow today (as_of 22/11)

    def win(phrase: str) -> Any:
        p = windows.window_from_phrase(phrase) or ""
        return windows.build_windows(p, windows.anchor_for(p, YDAY, latest))

    assert win("hôm qua").cur == (YDAY, YDAY)
    assert win("30 ngày qua").cur == (date(2026, 10, 24), YDAY)
    assert win("tháng này").cur == (date(2026, 11, 1), YDAY)
    assert win("tháng trước").cur == (date(2026, 10, 1), date(2026, 10, 31))
    assert win("tháng trước").prev == (date(2026, 9, 1), date(2026, 9, 30))
    # the 1st of the month: "tháng này" has no complete day yet
    assert windows.this_period_empty("mtd_vs_same_days_last_month", date(2026, 11, 30))
    assert not windows.this_period_empty("mtd_vs_same_days_last_month", YDAY)


async def test_decline_ranking_follows_the_decline_word_whatever_the_product_phrase() -> None:
    first = YDAY - timedelta(days=30)
    shop = shop_rows(first, YDAY, gmv=1000.0, orders=3.0)
    prods = [
        {
            "day": first + timedelta(days=i),
            "item_id": k,
            "gmv": (now if (first + timedelta(days=i)) > YDAY - timedelta(days=7) else before),
            "orders": 1.0,
            "units": 1.0,
        }
        for i in range(31)
        for k, now, before in (("p1", 100.0, 900.0), ("p2", 5000.0, 10.0))
    ]
    data = FakeData(shop, products=prods, names={"p1": "A", "p2": "B"})
    llm = FakeLLM(
        {
            "restated_vi": "x",
            "intents": [
                intent(question_type="status", metric_phrase="revenue", time_phrase="7 days")
            ],
        }
    )
    sink, _ = await go(
        AskRequest(
            shop_id=SHOP, platform="shopee", as_of=YDAY, text="mã nào tụt mạnh nhất tuần này"
        ),
        llm=llm,
        jev=FakeJev(
            lambda s, q: full(mode=ch("lookup"), lookup=ch("top_products"), metric=ch("gmv"))
        ),
        data=data,
    )
    rows = sink.of("data_answer")[0]["rows"]
    assert rows[0]["label_vi"] == "A" and rows[0]["value_vi"].startswith("▼")


async def test_why_after_a_decline_ranking_explains_the_top_decliner() -> None:
    first = YDAY - timedelta(days=40)
    shop = shop_rows(first, YDAY, gmv=1000.0, orders=3.0)
    prods = [
        {
            "day": first + timedelta(days=i),
            "item_id": k,
            "gmv": now if (first + timedelta(days=i)) >= date(2026, 11, 16) else before,
            "orders": 1.0,
            "units": 1.0,
        }
        for i in range(41)
        for k, now, before in (("p1", 100.0, 900.0), ("p2", 800.0, 800.0))
    ]
    data = FakeData(shop, products=prods, names={"p1": "A", "p2": "B"})
    llm = FakeLLM(
        {
            "restated_vi": "x",
            "intents": [
                intent(
                    question_type="status",
                    metric_phrase=None,
                    ranking="decline",
                    time_phrase="last week",
                ),
                intent(
                    question_type="why_changed", metric_phrase="revenue", time_phrase="last week"
                ),
            ],
        },
        text="x",
    )

    def jev(state: Any, q: Any) -> Any:
        if state["intent"]["question_type"] == "status":
            return full(
                fits={"type": "noul", "noul": 0.5}, mode=ch("lookup"), lookup=ch("top_products")
            )
        return full(mode=ch("why"), chain=ch("gmv_change"), metric=ch("gmv"))

    sink, _ = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q"),
        llm=llm,
        jev=FakeJev(jev),
        data=data,
    )
    assert not sink.of("needs_choice")
    assert sink.of("data_answer")[0]["rows"][0]["label_vi"] == "A"
    assert "shop_daily:p1" in data.calls  # the why chain ran on the top decliner


async def test_one_intent_with_asks_why_adds_the_why_on_the_top_item() -> None:
    first = YDAY - timedelta(days=40)
    shop = shop_rows(first, YDAY, gmv=1000.0, orders=3.0)
    prods = [
        {
            "day": first + timedelta(days=i),
            "item_id": k,
            "gmv": now if (first + timedelta(days=i)) >= date(2026, 11, 16) else before,
            "orders": 1.0,
            "units": 1.0,
        }
        for i in range(41)
        for k, now, before in (("p1", 100.0, 900.0), ("p2", 800.0, 800.0))
    ]
    data = FakeData(shop, products=prods, names={"p1": "A", "p2": "B"})
    llm = FakeLLM(
        {
            "restated_vi": "x",
            "intents": [
                intent(
                    question_type="status",
                    metric_phrase=None,
                    time_phrase="last week",
                    ranking="decline",
                    asks_why=True,
                )
            ],
        },
        text="x",
    )
    sink, _ = await go(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q"),
        llm=llm,
        jev=FakeJev(
            lambda s, q: full(
                fits={"type": "noul", "noul": 0.5}, mode=ch("lookup"), lookup=ch("top_products")
            )
        ),
        data=data,
    )
    assert not sink.of("needs_choice")
    assert sink.of("data_answer")[0]["rows"][0]["label_vi"] == "A"
    assert "shop_daily:p1" in data.calls  # the why chain ran on the top decliner
