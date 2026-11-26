"""#110: the eight reading rules of every Chat answer, asserted on several answer types run end to
end on the bank's seeded shop (one figure, a top list, a voucher analysis of three figures, a why
chain, a several-question message), plus the shaping itself (`readable.shape`)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.analytics_agent import fmt, readable
from juli_backend.services.analytics_agent.windows import build_windows, clip_to_freshness
from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory

CASES = {c["id"]: c for c in runner.load_cases()}
#: one per answer type
TYPES = ("gmv-7d-before-matches-screen", "top-products-7d", "voucher-analyse")


@pytest.fixture(scope="module")
def shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("readability") / "shop.sqlite"
    return path, build_sqlite(path)


async def _run(shop: tuple[Path, Any], case: dict[str, Any]) -> runner.Outcome:
    path, shop_id = shop
    async with sqlite_factory(path) as factory:
        return await runner.ask(factory, SqliteServiceData(factory, shop_id), shop_id, case)


@pytest.mark.parametrize("cid", TYPES)
async def test_rules_1_2_lead_first_and_one_period_line(cid: str, shop: tuple[Path, Any]) -> None:
    out = await _run(shop, CASES[cid])
    shown = [e for e in out.events if e["type"] not in ("status", "restated", "done")]
    # 1: the answer's own sentence comes first, with a figure, and the text has no header
    leads = out.of("lead")
    assert leads and any(ch.isdigit() for ch in leads[0]["text_vi"])
    kinds = [e["type"] for e in shown if e["type"] not in ("text_delta", "text_replace")]
    assert kinds[:2] == ["meta", "lead"]
    assert not out.final_text().startswith("Đang tìm hiểu")
    # 2: period, data day (and sale days) once, on top; the text does not repeat the data day
    (meta,) = out.of("meta")
    assert meta["fresh_vi"].startswith("Số liệu đến hết ")
    assert meta["fresh_vi"] not in out.final_text()


@pytest.mark.parametrize("cid", TYPES)
async def test_rule_5_at_most_three_tiles_each_with_one_comparison(
    cid: str, shop: tuple[Path, Any]
) -> None:
    out = await _run(shop, CASES[cid])
    tiles = [a for a in out.of("data_answer") if a["kind"] == "metric_total"]
    assert len(tiles) <= readable.MAX_TILES
    for t in tiles:
        assert t["title_vi"] and t["value"]
        assert "compare_vi" not in t or isinstance(t["compare_vi"], str)


async def test_rule_5_a_voucher_analysis_is_three_tiles(shop: tuple[Path, Any]) -> None:
    out = await _run(shop, CASES["voucher-analyse"])
    tiles = [a for a in out.of("data_answer") if a["kind"] == "metric_total"]
    assert 1 <= len(tiles) <= 3


async def test_rule_8_a_one_figure_answer_offers_next_steps_as_buttons(
    shop: tuple[Path, Any],
) -> None:
    out = await _run(shop, CASES["gmv-7d-before-matches-screen"])
    (more,) = out.of("more")
    assert [i["label_vi"] for i in more["items"]] == ["Theo sản phẩm", "Theo ngày"]
    assert not out.final_text().rstrip().endswith("?")


async def test_rule_2_several_questions_on_one_period_show_one_line(
    shop: tuple[Path, Any],
) -> None:
    out = await _run(shop, CASES["sa06-ads-week-three-asks"])
    assert len(out.of("intent_block")) == 3 and len(out.of("meta")) == 1


def _tile(**kw: Any) -> dict[str, Any]:
    base = {
        "type": "data_answer",
        "kind": "metric_total",
        "title_vi": "GMV",
        "value": "1.000đ",
        "window_vi": "01/10–07/10 so với 24/09–30/09",
        "fresh_vi": "Số liệu đến hết 07/10",
    }
    return base | kw


def test_rule_3_periods_are_equal_length() -> None:
    anchor = date(2026, 11, 24)
    for preset, kw in (
        ("this_week_vs_same_days_last_week", {}),
        ("mtd_vs_same_days_last_month", {}),
        ("last_7d_vs_prev_7d", {}),
        ("named_month_vs_previous", {"named_month": "2026-11"}),
        ("default", {"explicit": (date(2026, 10, 26), anchor)}),
    ):
        w = clip_to_freshness(build_windows(preset, anchor, **kw), date(2026, 11, 22))
        assert w.prev is not None
        assert (w.cur[1] - w.cur[0]).days == (w.prev[1] - w.prev[0]).days, preset


def test_rule_4_no_percent_on_a_thin_base() -> None:
    assert fmt.delta("gmv", 3_638_700, 82_620)["text_vi"] == fmt.THIN_BASE_VI
    assert fmt.delta("orders", 34, 2)["text_vi"] == fmt.THIN_BASE_VI
    assert fmt.delta("gmv", 1200, 1000)["text_vi"] == "▲ 20,0%"
    assert fmt.delta("margin", 0.3, 0.01)["text_vi"].endswith("điểm %")  # points, never thin


def test_rule_5_a_fourth_figure_goes_into_one_table() -> None:
    held = [_tile(title_vi=f"Chỉ số {i}") for i in range(5)]
    out, _ = readable.shape(held, None)
    tiles = [e for e in out if e.get("kind") == "metric_total"]
    (table,) = [e for e in out if e.get("kind") == "metric_list"]
    assert len(tiles) == 3 and [r["label_vi"] for r in table["rows"]] == ["Chỉ số 3", "Chỉ số 4"]


def test_rule_5_the_comparison_line() -> None:
    up = _tile(delta={"dir": "up", "text_vi": "▲ 20,0%"}, before_vi="800đ")
    thin = _tile(delta={"dir": "flat", "text_vi": fmt.THIN_BASE_VI}, before_vi="10đ")
    none = _tile(delta={"dir": "flat", "text_vi": "–"}, before_vi=fmt.NODATA)
    assert readable.compare_vi(up) == "▲ 20,0% so với 800đ"
    assert readable.compare_vi(thin) == fmt.THIN_BASE_VI
    assert readable.compare_vi(none) is None


def test_rule_7_no_box_that_only_says_there_is_nothing() -> None:
    held = [
        _tile(value=fmt.NODATA),
        {"type": "no_card", "reason_vi": "Không có đòn bẩy phù hợp với nguyên nhân này."},
        {"type": "no_card", "reason_vi": "Đã có thẻ.", "existing_card_code": "C-1"},
        {**_tile(kind="top_products", title_vi="Top sản phẩm theo GMV"), "rows": []},
    ]
    out, _ = readable.shape(held, None)
    assert [e for e in out if e["type"] == "no_card"] == [held[2]]
    assert next(e for e in out if e.get("kind") == "metric_total")["value"] == "—"
    assert next(e for e in out if e.get("kind") == "top_products")["empty"] is True
    assert fmt.value("profit", None) == "—"


def test_rule_2_a_block_on_the_same_period_repeats_no_line() -> None:
    first, shown = readable.shape([_tile()], None)
    again, shown2 = readable.shape([_tile(title_vi="Đơn hàng", value="3")], shown)
    other, _ = readable.shape([_tile(window_vi="28/09–04/10 so với 21/09–27/09")], shown2)
    assert [e["type"] for e in first][:2] == ["meta", "lead"]
    assert "meta" not in [e["type"] for e in again]
    assert [e["type"] for e in other][0] == "meta"


async def test_rules_1_2_on_a_why_chain() -> None:
    from tests.unit.analytics_agent.fakes import FakeJev, FakeLLM
    from tests.unit.analytics_agent.test_engine import TEXT, data_orders, full, go, req
    from tests.unit.analytics_agent.test_routing import intent

    llm = FakeLLM({"restated_vi": "Vì sao đơn hàng giảm", "intents": [intent()]}, text=TEXT)
    sink, _ = await go(
        req(text="sao đơn tụt"), llm=llm, jev=FakeJev(lambda s, q: full()), data=data_orders()
    )
    types = [e["type"] for e in sink.events]
    (meta,) = sink.of("meta")
    head = sink.of("path")[0]["steps"][0]
    assert sink.of("lead")[0]["text_vi"].startswith(f"{head['label_vi']} là {head['value_vi']}")
    assert types.index("meta") < types.index("lead") < types.index("path")
    final = sink.of("text_replace")[-1]["text"] if sink.of("text_replace") else ""
    assert not final.startswith("Đang tìm hiểu") and meta["fresh_vi"].startswith("Số liệu đến hết")
