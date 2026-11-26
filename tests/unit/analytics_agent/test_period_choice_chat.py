"""Owner #113 (replaces #112(3) for Chat): a question that names no period asks the seller to pick
one -- "7 ngày qua", "30 ngày qua", "Tháng này", "Tháng trước", "Khoảng khác" -- and the tap runs
that period with its dates on top (#110); a named period is never asked; a template keeps its
fixed 7 days unless they hold no data. Checked on the bank's seeded shop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.analytics_agent import routing, shopee_labels
from juli_backend.services.analytics_agent.windows import ASK_PERIODS, PERIOD_VI
from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory


@pytest.fixture(scope="module")
def shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("period_choice_chat") / "shop.sqlite"
    return path, build_sqlite(path)


def _case(question: str, **intent: Any) -> dict[str, Any]:
    return {
        "id": "t",
        "question": question,
        "intents": [{"metric_key": "gmv", "metric_phrase": "revenue", **intent}],
        "jev": {"metric": "gmv", "window": "last_7d_vs_prev_7d"},  # the router's guess is unused
        "expect": {},
    }


async def _ask(shop: tuple[Path, Any], case: dict[str, Any]) -> tuple[runner.Outcome, Any, Any]:
    path, shop_id = shop
    async with sqlite_factory(path) as factory:
        out = await runner.ask(factory, SqliteServiceData(factory, shop_id), shop_id, case)
    return out, None, shop_id


async def test_no_period_named_asks_with_the_period_buttons(shop: tuple[Path, Any]) -> None:
    out, _, _ = await _ask(shop, _case("doanh thu bao nhiêu?"))
    assert not out.of("data_answer")
    (nc,) = out.of("needs_choice")
    assert nc["item"] == "window"
    labels = [o["label_vi"] for o in nc["options"]]
    assert labels == ["7 ngày qua", "30 ngày qua", "Tháng này", "Tháng trước", "Khoảng khác"]
    assert [o["value"] for o in nc["options"]] == list(ASK_PERIODS)
    assert labels[:4] == [PERIOD_VI[v] for v in ASK_PERIODS[:4]]  # the "more" buttons' names


async def test_the_tap_runs_that_period_with_its_dates_once_on_top(shop: tuple[Path, Any]) -> None:
    case = {**_case("doanh thu bao nhiêu?"), "then": {"choice": {"value": "last_7d_vs_prev_7d"}}}
    out, _, _ = await _ask(shop, case)
    assert out.followup is not None
    (ans,) = out.followup.of("data_answer")
    (meta,) = out.followup.of("meta")
    assert ans["window_vi"].startswith("01/10–07/10") and meta["window_vi"] == ans["window_vi"]
    assert meta["fresh_vi"] == "Số liệu đến hết 07/10"


async def test_a_named_period_is_never_asked(shop: tuple[Path, Any]) -> None:
    out, _, _ = await _ask(shop, _case("doanh thu tuần trước?", time_phrase="last week"))
    assert not out.of("needs_choice")
    (ans,) = out.of("data_answer")
    assert ans["window_vi"].startswith("28/09–04/10")


def test_khoang_khac_hands_the_period_back_and_never_guesses() -> None:
    lookup = {"choice": "lookup", "probabilities": {"lookup": 0.95}}
    dec = routing.decide(
        {"question_type": "status", "metric_phrase": "GMV", "metric_key": "gmv"},
        {"fits": {"noul": 0.95}, "mode": lookup},
    )
    assert dec["outcome"] == "needs_choice" and dec["remaining"][0][0] == "window"
    ev = routing.needs_choice_event(dec, {}, shopee_labels(), runner.DEFAULT_AS_OF)
    again = routing.resume(ev["pending"], {"item": "window", "value": "other"})
    assert again["outcome"] == "needs_choice" and "window" not in again


async def test_a_template_keeps_its_fixed_seven_days(shop: tuple[Path, Any]) -> None:
    case = {"id": "t", "question": "[improve_gmv]", "template": "improve_gmv", "expect": {}}
    out, _, _ = await _ask(shop, case)
    assert not out.of("needs_choice")
    comparing = [e for e in out.events if e.get("key") == "comparing"][0]["text_vi"]
    assert comparing.startswith("Đang so sánh 01/10–07/10")
    assert out.of("meta")[0]["window_vi"].startswith("01/10–07/10")


async def test_a_template_widens_to_30_days_only_when_its_7_days_hold_no_data() -> None:
    from datetime import timedelta

    from tests.unit.analytics_agent.fakes import AS_OF, FakeData, FakeJev, FakeLLM, shop_rows
    from tests.unit.analytics_agent.test_engine import full, go, req

    # the 7 days before the last week hold no row; the 30-day windows are covered enough
    rows = shop_rows(AS_OF - timedelta(days=60), AS_OF - timedelta(days=14), orders=5.0, gmv=500.0)
    rows += shop_rows(AS_OF - timedelta(days=6), AS_OF, orders=9.0, gmv=900.0)
    sink, res = await go(
        req(template="improve_gmv"), llm=FakeLLM(None), jev=FakeJev(lambda s, q: full()),
        data=FakeData(rows),
    )  # fmt: skip
    comparing = [e for e in sink.events if e.get("key") == "comparing"][0]["text_vi"]
    first = AS_OF - timedelta(days=29)
    assert comparing.startswith(f"Đang so sánh {first:%d/%m}–{AS_OF:%d/%m}")
    assert {"step": "template_window", "kept": "last_30d_vs_prev_30d"} in res.routing


async def test_a_month_not_started_states_it_and_no_figure(shop: tuple[Path, Any]) -> None:
    out, _, _ = await _ask(
        shop, _case("doanh thu tháng 11?", time_phrase="November", named_month="2026-11")
    )
    assert not out.of("data_answer")
    assert out.of("label")[0]["text_vi"] == "Tháng 11/2026 chưa bắt đầu (số liệu đến hết 07/10)."


async def test_a_cost_ratio_lookup_answers_never_raises(shop: tuple[Path, Any]) -> None:
    case = {
        "id": "t",
        "question": "Tổng chi phí chiếm bao nhiêu % doanh thu 7 ngày qua?",
        "intents": [
            {"metric_key": "cost_total_pct", "metric_phrase": "cost share", "time_phrase": "7 days"}
        ],
        "jev": {"metric": "cost_ratio"},
        "expect": {},
    }
    out, _, _ = await _ask(shop, case)
    assert out.error is None and not out.of("error")
    (ans,) = out.of("data_answer")
    assert ans["value"].endswith("%") and ans["window_vi"].startswith("01/10–07/10")
