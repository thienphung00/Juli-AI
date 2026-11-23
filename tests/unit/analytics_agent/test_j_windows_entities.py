"""Track J (batch-1123-a): one window per phrase, window kept across a choice, no metric picker
when a metric is named, an entity-labelled answer never carries a shop number. Synthetic data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, windows
from juli_backend.services.analytics_agent.routing import decide, entity_kind
from tests.unit.analytics_agent.fakes import AS_OF, FakeData, FakeJev, FakeLLM, shop_rows
from tests.unit.analytics_agent.test_cards import ch, nl
from tests.unit.analytics_agent.test_engine import SHOP, full, go, req
from tests.unit.analytics_agent.test_routing import ans, intent

SAT = date(2026, 11, 21)  # newest complete day in the 22/11 scenario


@pytest.mark.parametrize("phrase", ["tuần trước", "last week", "previous week", "tuần vừa rồi"])
def test_three_phrasings_of_last_week_are_one_window(phrase: str) -> None:
    preset = windows.window_from_phrase(phrase)
    w = windows.build_windows(preset or "", SAT)
    assert preset == "last_full_week_vs_week_before"
    assert w.cur == (date(2026, 11, 9), date(2026, 11, 15))
    assert w.prev == (date(2026, 11, 2), date(2026, 11, 8))


def test_this_week_is_monday_to_yesterday_against_the_same_days_last_week() -> None:
    w = windows.build_windows(windows.window_from_phrase("tuần này") or "", SAT)
    assert w.cur == (date(2026, 11, 16), SAT) and w.prev == (date(2026, 11, 9), date(2026, 11, 14))


def test_last_7_days_are_the_last_seven_complete_days() -> None:
    w = windows.build_windows(windows.window_from_phrase("7 ngày qua") or "", SAT)
    assert w.cur == (date(2026, 11, 15), SAT) and w.prev == (date(2026, 11, 8), date(2026, 11, 14))


def test_sale_days_are_double_days_15th_and_25th() -> None:
    got = windows.campaign_days(date(2026, 11, 9), date(2026, 11, 26))
    assert got == [date(2026, 11, 11), date(2026, 11, 15), date(2026, 11, 25)]
    w = windows.build_windows("last_full_week_vs_week_before", SAT)
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


async def test_entity_question_is_refused_never_a_shop_number() -> None:
    shop = shop_rows(AS_OF - timedelta(days=60), AS_OF, gmv=1000.0, orders=3.0)
    llm = FakeLLM(
        {
            "restated_vi": "Đơn dùng voucher",
            "intents": [intent(question_type="status", entity_phrase="voucher orders")],
        }
    )
    jev = FakeJev(
        lambda s, q: full(mode=ch("lookup"), lookup=ch("metric_total"), metric=ch("orders"))
    )
    sink, res = await go(req(text="q"), llm=llm, jev=jev, data=FakeData(shop))
    assert sink.of("label")[0]["text_vi"] == "Juli chưa có số liệu này"
    assert not sink.of("data_answer") and not sink.of("path") and not sink.of("card")
    assert res.stop_reasons == ["data_missing"]


async def test_window_chosen_is_the_window_run_and_freshness_is_the_newest_complete_day() -> None:
    # shop totals reach 21/11 (a Saturday); today's "as_of" is later, as in the 22/11 session
    shop = shop_rows(SAT - timedelta(days=60), SAT, gmv=1000.0, orders=3.0)
    first_as_of = SAT + timedelta(days=3)
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
            window=ch("last_7d_vs_prev_7d", 0.55, "last_30d_vs_prev_30d"),
        )
    )
    r = AskRequest(shop_id=SHOP, platform="shopee", as_of=first_as_of, text="q")
    sink, _ = await go(r, llm=llm, jev=jev, data=FakeData(shop))
    nc = sink.of("needs_choice")[0]
    assert nc["pending"]["anchor"] == SAT.isoformat()
    shown = nc["options"][0]["label_vi"]
    assert shown == "15/11–21/11 so với 08/11–14/11"
    r2 = AskRequest(
        shop_id=SHOP,
        platform="shopee",
        as_of=first_as_of,
        choice={"item": "window", "value": "last_7d_vs_prev_7d"},
        pending=nc["pending"],
    )
    sink2, _ = await go(
        r2, llm=FakeLLM(None), jev=FakeJev(lambda s, q: full()), data=FakeData(shop)
    )
    da = sink2.of("data_answer")[0]
    assert da["window_vi"] == shown and da["fresh_vi"] == "Số liệu đến hết 21/11"
