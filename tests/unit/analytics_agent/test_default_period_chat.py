"""#112(3): a question that names no period runs on the tabs' default period (the newest 30-day
window with >= 70 % of GMV's costs known, `shopee_analytics.default_period`), its dates shown; a
named period is never moved. Checked on the bank's seeded shop against the tabs' own resolver."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.shopee_analytics import default_period, queries
from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory


@pytest.fixture(scope="module")
def shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("default_period_chat") / "shop.sqlite"
    return path, build_sqlite(path)


async def _tabs_default(factory: Any, shop_id: Any) -> tuple[date, date]:
    async with factory() as s:
        win, _ = await queries.resolve_screen_window(s, shop_id, period=default_period.AUTO)
        await s.rollback()
    assert win is not None
    return win.start, win.end


def _case(question: str, **intent: Any) -> dict[str, Any]:
    return {
        "id": "t",
        "question": question,
        "intents": [{"metric_key": "gmv", "metric_phrase": "revenue", **intent}],
        "jev": {"metric": "gmv", "window": "last_7d_vs_prev_7d"},  # the router's pick is ignored
        "expect": {},
    }


async def _ask(shop: tuple[Path, Any], case: dict[str, Any]) -> tuple[runner.Outcome, Any, Any]:
    path, shop_id = shop
    async with sqlite_factory(path) as factory:
        out = await runner.ask(factory, SqliteServiceData(factory, shop_id), shop_id, case)
        tabs = await _tabs_default(factory, shop_id)
    return out, tabs, shop_id


async def test_no_period_named_is_the_tabs_default_period(shop: tuple[Path, Any]) -> None:
    out, (a, b), _ = await _ask(shop, _case("doanh thu bao nhiêu?"))
    (ans,) = out.of("data_answer")
    assert not out.of("needs_choice")
    assert ans["window_vi"].startswith(f"{a:%d/%m}–{b:%d/%m} so với ")  # its dates shown
    assert (b - a).days + 1 == default_period.DEFAULT_DAYS


async def test_a_named_period_is_never_moved(shop: tuple[Path, Any]) -> None:
    out, _, _ = await _ask(shop, _case("doanh thu tuần trước?", time_phrase="last week"))
    (ans,) = out.of("data_answer")
    assert ans["window_vi"].startswith("28/09–04/10")


async def test_a_template_runs_on_the_default_period(shop: tuple[Path, Any]) -> None:
    case = {"id": "t", "question": "[improve_gmv]", "template": "improve_gmv", "expect": {}}
    out, (a, b), _ = await _ask(shop, case)
    comparing = [e for e in out.events if e.get("key") == "comparing"]
    assert comparing and f"{a:%d/%m}–{b:%d/%m}" in comparing[0]["text_vi"]


async def test_a_month_not_started_states_it_and_no_figure(shop: tuple[Path, Any]) -> None:
    out, _, _ = await _ask(
        shop, _case("doanh thu tháng 11?", time_phrase="November", named_month="2026-11")
    )
    assert not out.of("data_answer")
    assert out.of("label")[0]["text_vi"] == "Tháng 11/2026 chưa bắt đầu (số liệu đến hết 07/10)."
