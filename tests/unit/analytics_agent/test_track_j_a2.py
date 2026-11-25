"""Track J (batch-1123-a2): campaign rows, weekly ROAS, J9 draft gate, J5 Ưu đãi, window clip,
TikTok profit gate. Synthetic data only; the parser and Jev are stubbed (no paid call)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from juli_backend.services.analytics_agent import (
    AskRequest,
    engine,
    run,
    windows,
)
from juli_backend.services.analytics_agent import (
    cards as cardstage,
)
from juli_backend.services.analytics_agent.entities import campaign_row, campaign_verdict
from juli_backend.services.analytics_agent.registry_reads import roas
from tests.unit.analytics_agent.fakes import (
    FakeCardEngine,
    FakeData,
    FakeEntityData,
    FakeJev,
    FakeLLM,
    ListSink,
    ScriptedQuery,
    camp,
    engine_card,
    shop_rows,
    version,
)
from tests.unit.analytics_agent.test_engine import SHOP, L, full
from tests.unit.analytics_agent.test_j_windows_entities import _ask, _lookup_jev, _shop
from tests.unit.analytics_agent.test_routing import intent

YDAY = date(2026, 11, 22)


def _campaign_script(rows: list[dict[str, Any]], shop_be: float | None = None) -> Any:
    def script(ids: list[str], a: Any, b: Any, **kw: Any) -> dict[str, Any]:
        if kw.get("group_by") == "campaign":
            return {"values": {"roas_break_even": shop_be}, "rows": rows}
        return {"values": {}, "rows": []}

    return script


async def test_campaign_rows_delegate_to_query_by_campaign_and_skip_no_spend() -> None:
    rows = [
        {"campaign": "k1", "campaign_name": "CDN/02", "cost_ads": 200.0, "ads_gmv_direct": 600.0,
         "roas_direct": 3.0, "roas_break_even": 2.0, "contribution": 300.0, "items": ["p1"]},
        {"campaign": "k3", "campaign_name": "CDN/03", "cost_ads": 0.0, "ads_gmv_direct": 0.0,
         "roas_direct": None, "roas_break_even": None, "contribution": 0.0},
    ]  # fmt: skip
    svc = ScriptedQuery(_campaign_script(rows))
    out = await svc.campaign_rows(date(2026, 11, 16), date(2026, 11, 22))
    assert svc.asked[0]["group_by"] == "campaign" and "roas_break_even" in svc.asked[0]["ids"]
    (first,) = out  # no spend: no row
    assert first["name"] == "CDN/02" and first["roas"] == 3.0 and first["break_even"] == 2.0
    assert first["profit_after_ads"] == 100.0 and first["items"] == ["p1"]  # query's values
    assert campaign_verdict(first) == "Lãi"


async def test_campaign_without_giá_vốn_is_unknown_not_a_loss() -> None:
    rows = [
        {"campaign": "k1", "campaign_name": "CDN/05", "cost_ads": 100.0, "ads_gmv_direct": 300.0,
         "roas_direct": 3.0, "roas_break_even": None, "contribution": None},
    ]  # fmt: skip
    (row,) = await ScriptedQuery(_campaign_script(rows)).campaign_rows(
        date(2026, 11, 16), date(2026, 11, 22)
    )
    assert row["break_even"] is None and row["profit_after_ads"] is None
    assert campaign_verdict(row) == "Chưa rõ"
    assert "hoà vốn chưa có" in campaign_row(row)["value_vi"]


async def test_campaign_loss_question_lists_loss_rows_with_all_figures() -> None:
    camps = [
        camp("k1", "CDN/01", 400, 900, 3.0),  # ROAS 2,25 < 3,00
        camp("k2", "CDN/02", 300, 1800, 3.2),  # ROAS 6,00 > 3,20
    ]
    data = FakeEntityData(_shop(), entity={"campaigns": camps})
    sink, _ = await _ask(
        data,
        intent(question_type="status", entity_phrase="ad campaign", metric_phrase="losing"),
        _lookup_jev("roas"),
    )
    ans = sink.of("data_answer")[0]
    assert [r["label_vi"] for r in ans["rows"]] == ["CDN/01"]
    row = ans["rows"][0]
    assert row["value_vi"].startswith("Lỗ") and "hoà vốn 3,00" in row["value_vi"]
    assert "chi 400đ" in row["detail_vi"] and "GMV 900đ" in row["detail_vi"]


def test_shop_roas_comes_from_the_registry_with_a_derived_cost() -> None:
    assert roas(Decimal("2760000"), Decimal("441350")) == pytest.approx(6.2535, rel=1e-3)
    assert roas(None, 100) is None


async def test_weekly_shop_roas_is_filled_from_ads_gmv_and_spend() -> None:
    from tests.unit.analytics_agent.test_weekly import _data, _run_plan

    sink, _ = await _run_plan()
    s1 = next(e for e in sink.of("data_answer") if e["title_vi"].startswith("16–22/11 so với"))
    roas_row = next(r for r in s1["rows"] if r["label_vi"] == "ROAS")
    assert roas_row["value_vi"] != "—" and roas_row["value_vi"].startswith("4,00")  # 400 / 100
    assert _data() is not None


# ---- J-A5: a draft shows the builder's numbers, or there is no draft


def test_estimable_gate() -> None:
    all_no = {"versions": [version("A", None, None, estimable=False)]}
    assert not cardstage.estimable(all_no, "variation_set")
    assert cardstage.estimable(engine_card(), "variation_set")
    assert cardstage.estimable(all_no, "title")  # a text change carries no number by nature
    assert cardstage.estimable({"versions": []}, "variation_set")


async def test_weekly_action_without_estimate_makes_no_draft() -> None:
    from juli_backend.services.analytics_agent import weekly
    from tests.unit.analytics_agent.test_weekly import _data

    dead = {"title": "Tăng ngân sách QC", "versions": [version("A", None, None, estimable=False)]}
    eng = FakeCardEngine(per_kind={"ads_budget": {"ok": True, "card": dead}})
    data = _data()
    data.cards = []  # nothing open: the action has no card to point to
    events, out = await weekly.run_weekly(data, eng, FakeJev(lambda s, q: full()), L, YDAY)
    acts = next(e for e in events if e.get("title_vi") == "Việc nên làm tuần sau")["rows"]
    by = {r["label_vi"]: r for r in acts}
    assert by[L.kind("ads_budget")]["value_vi"] == "Chưa có phương án"
    assert "ads_budget" not in {a["kind"] for a in out.accepted}


# ---- J-A7: window stops at the freshness day; J5 Ưu đãi cost + per-voucher fallback


def test_window_is_clipped_to_the_newest_complete_day() -> None:
    w = windows.build_windows("last_full_week_vs_week_before", YDAY, sale_aware=True)
    w = windows.clip_to_freshness(w, date(2026, 11, 20))
    assert w.cur == (date(2026, 11, 16), date(2026, 11, 20))
    assert w.prev == (date(2026, 11, 2), date(2026, 11, 6))  # day for day
    assert "clipped_to_freshness" in w.flags
    same = windows.clip_to_freshness(w, date(2026, 11, 22))
    assert same is w


async def test_sums_ignore_incomplete_days() -> None:
    rows = shop_rows(YDAY - timedelta(days=30), YDAY, gmv=100.0, orders=1.0)
    for r in rows[-2:]:
        r["complete"] = False  # 21-22/11 still being read
    sink, _ = await _ask(
        FakeData(rows),
        intent(question_type="status", metric_phrase="orders", time_phrase="last week"),
        _lookup_jev("orders"),
    )
    da = sink.of("data_answer")[0]
    assert da["fresh_vi"] == "Số liệu đến hết 20/11"
    assert da["window_vi"].startswith("16/11–20/11") and da["value"] == "5"


def _voucher_intent() -> dict[str, Any]:
    return intent(
        question_type="status",
        metric_phrase="orders",
        entity_phrase="voucher",
        time_phrase="last week",
    )


def _income(first: date, last: date) -> list[dict[str, Any]]:
    """One synthetic income row per order day: 2 voucher orders, 400đ GMV, 20đ seller voucher."""
    return [
        {"day": first + timedelta(days=k), "orders": 2.0, "gmv": 400.0, "cost": 20.0}
        for k in range((last - first).days + 1)
    ]


async def test_voucher_answer_is_the_uu_dai_voucher_cost_from_income_rows() -> None:
    data = FakeEntityData(_shop(), entity={"voucher": _income(YDAY - timedelta(days=13), YDAY)})
    sink, _ = await _ask(
        data,
        intent(
            question_type="status",
            metric_phrase="voucher cost",
            entity_phrase="voucher",
            time_phrase="last week",
        ),
    )
    answers = sink.of("data_answer")
    cost = answers[0]
    assert cost["title_vi"].startswith("Chi phí voucher (Ưu đãi)") and cost["value"] == "140đ"
    assert cost["fresh_vi"] == "Số liệu đến hết 22/11"
    assert answers[1]["value"] == "Juli chưa có số liệu này"  # per voucher code: no source


async def test_income_ends_before_the_window_is_said_and_not_counted_as_zero() -> None:
    first, last = date(2026, 11, 9), date(2026, 11, 19)  # the income export stops 19/11
    data = FakeEntityData(_shop(), entity={"voucher": _income(first, last)})
    sink, _ = await _ask(data, _voucher_intent())
    tot = sink.of("data_answer")[0]
    assert tot["value"] == "8"  # 4 days (16-19/11) x 2 orders; 20-22/11 are not 0, just absent
    assert tot["fresh_vi"] == "Số liệu thu nhập đến hết 19/11"


async def test_voucher_without_income_rows_is_no_data_not_zero() -> None:
    data = FakeEntityData(_shop(), entity={"voucher": []})
    sink, res = await _ask(data, _voucher_intent())
    assert sink.of("label")[0]["text_vi"] == "Juli chưa có số liệu này"
    assert res.stop_reasons == ["data_missing"]


def test_writer_input_names_the_product_scope() -> None:
    from juli_backend.services.analytics_agent import facts

    cj: dict[str, Any] = {
        "metric": "gmv",
        "stop_reason": "explained",
        "window": {"label_vi": "a", "cur": None},
        "findings": [],
        "product": {"item_id": "p1", "name": "Túi đay"},
    }
    inp, _ = facts.writer_input(cj, L)
    assert inp["phạm_vi"] == "sản phẩm Túi đay"
    inp2, _ = facts.writer_input({**cj, "product": None}, L)
    assert inp2["phạm_vi"] == "cả shop"


# ---- TikTok profit gate (W3-Q5 = a)


async def test_tiktok_profit_is_dash_until_ads_spend_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "_platform_has_analytics", lambda p: True)
    rows = shop_rows(YDAY - timedelta(days=30), YDAY, gmv=100.0, orders=1.0)  # ads_spend None
    llm = FakeLLM(
        {
            "restated_vi": "Lợi nhuận",
            "intents": [intent(question_type="status", metric_phrase="profit")],
        }
    )
    sink = ListSink()
    await run(
        AskRequest(shop_id=SHOP, platform="tiktok", as_of=YDAY, text="lợi nhuận tuần trước"),
        llm=llm,
        jev=_lookup_jev("profit"),
        sink=sink,
        labels=L,
        data=FakeData(rows),
        card_engine=FakeCardEngine(),
    )
    da = sink.of("data_answer")[0]
    assert da["value"] == "—" and da["reason_code"] == "ads_scope_missing"
    known = shop_rows(YDAY - timedelta(days=30), YDAY, gmv=100.0, orders=1.0, ads_spend=5.0)
    assert not await engine._tiktok_profit_gated("tiktok", "profit", FakeData(known), YDAY)
    assert not await engine._tiktok_profit_gated("shopee", "profit", FakeData(rows), YDAY)
    assert not await engine._tiktok_profit_gated("tiktok", "gmv", FakeData(rows), YDAY)
