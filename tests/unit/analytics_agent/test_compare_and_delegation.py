"""C6 (build-and-compare), C2 (DataPort delegates to `query()`), C1 (no calculation in the agent)
and L1/L4 (levels and labels). Synthetic rows; OPP and QUERY are scripted, no paid call."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from juli_backend.services.analytics_agent import AskRequest, compare, levers, routing, run
from tests.unit.analytics_agent.fakes import (
    FakeCardEngine,
    FakeEntityData,
    FakeJev,
    FakeLLM,
    ListSink,
    ScriptedQuery,
    opp,
)
from tests.unit.analytics_agent.test_engine import SHOP, L, full
from tests.unit.analytics_agent.test_routing import intent
from tests.unit.analytics_agent.test_weekly import YDAY, _data

AGENT = Path(__file__).resolve().parents[3] / "backend/src/juli_backend/services/analytics_agent"


def option(n: int, profit: float | None, **kw: Any) -> dict[str, Any]:
    """An OPP `compare` option (synthetic): one version of a voucher card."""
    return {
        "option": f"Mức {n}",
        "lever": "min_spend_voucher",
        "version": f"v{n}",
        "inputs": {"giảm": n * 5},
        "delta_gmv": 1000.0 * n,
        "delta_profit": profit,
        "cost": 100.0 * n,
        **kw,
    }


async def _ask(text: str, parsed: dict[str, Any], data: Any) -> tuple[ListSink, Any, FakeLLM]:
    llm = FakeLLM({"restated_vi": text, "intents": [parsed]})
    sink = ListSink()
    res = await run(
        AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text=text),
        llm=llm,
        jev=FakeJev(lambda s, q: full()),
        sink=sink,
        labels=L,
        data=data,
        card_engine=FakeCardEngine(per_kind={}),
    )
    return sink, res, llm


def _block(sink: ListSink) -> dict[str, Any]:
    (blk,) = [e for e in sink.events if e.get("kind") == "compare"]
    return blk


# ------------------------------------------------------------------ parser


def test_compare_options_is_its_own_question_type_with_slots_from_the_kinds_table() -> None:
    props = routing.INTENT_TOOL["input_schema"]["properties"]["intents"]["items"]["properties"]
    assert "compare_options" in props["question_type"]["enum"]
    assert "compare" in props["question_type"]["enum"]  # a period comparison keeps its type
    assert props["compare_kinds"]["items"]["enum"] == levers.card_kinds()
    dec = routing.decide(
        intent(question_type="compare_options", compare_kinds=["min_spend_voucher", "bogus"]), {}
    )
    assert dec["outcome"] == "go" and dec["mode"] == "compare"
    assert dec["kinds"] == ["min_spend_voucher"]  # only kinds in the table
    assert (await_none := routing.decide(intent(question_type="compare_options"), {}))[
        "kinds"
    ] == []
    assert await_none["mode"] == "compare"


# ------------------------------------------------------------------ the block


async def test_four_options_of_one_kind_one_pick_and_the_lead_names_the_figure() -> None:
    data = FakeEntityData(
        [],
        entity={
            "compare": {
                "min_spend_voucher": [
                    option(1, 100.0),
                    option(2, 900.0),
                    option(3, 300.0),
                    option(4, 500.0),
                ]
            }  # fmt: skip
        },
    )
    sink, res, llm = await _ask(
        "Tạo 4 phương án voucher rồi so sánh",
        intent(question_type="compare_options", compare_kinds=["min_spend_voucher"]),
        data,
    )
    blk = _block(sink)
    rows = blk["rows"]
    assert len(rows) == 4 and [r["recommended"] for r in rows].count(True) == 1
    best = next(r for r in rows if r["recommended"])
    assert best["option"] == "Mức 2" and best["profit_delta_vi"] == "900đ"  # OPP's figure
    assert all(r["gmv_delta_vi"] and r["profit_delta_vi"] and r["cost_vi"] for r in rows)
    assert all(r["version"] and r["lever"] == "min_spend_voucher" for r in rows)
    assert len({str(r["inputs"]) for r in rows}) == 4  # the inputs differ
    lead = "".join(e["text"] for e in sink.of("text_delta"))
    assert "Mức 2" in lead and "900đ" in lead  # the lead names the figure it was picked on
    assert res.stop_reasons == ["data_answer"] and not llm.agent_calls  # code, not the model
    assert "compare:min_spend_voucher" in data.calls


async def test_a_missing_option_states_the_reason_and_is_never_the_pick() -> None:
    opts = [option(1, 100.0), option(2, None, reason="chưa đủ dữ liệu", version=None),
            option(3, 300.0), option(4, 200.0)]  # fmt: skip
    data = FakeEntityData([], entity={"compare": {"min_spend_voucher": opts}})
    block, lead = await compare.run_compare(data, None, L, YDAY, ["min_spend_voucher"])
    miss = block["rows"][1]
    assert miss["reason"] == "chưa đủ dữ liệu" and not miss["card_ref"] and not miss["version"]
    assert [r["recommended"] for r in block["rows"]] == [False, False, True, False]
    assert "300đ" in lead


async def test_options_of_different_levers_come_from_the_stored_opportunities() -> None:
    opps = [
        opp("a", "ads_roas_target", profit=100.0),
        opp("b", "title", profit=700.0),
        opp("c", "min_spend_voucher", profit=300.0, card_code="JC-0007"),
        opp("d", "flash_sale", profit=200.0),
        opp("e", "cover_image", profit=None, outcome="below_band", reason="x"),  # not published
    ]
    data = FakeEntityData([], entity={"opportunities": opps})
    block, _ = await compare.run_compare(data, None, L, YDAY, [])
    levers_ = [r["lever"] for r in block["rows"]]
    assert len(levers_) == 4 and len(set(levers_)) == 4 and "cover_image" not in levers_
    best = next(r for r in block["rows"] if r["recommended"])
    assert best["lever"] == "title" and best["profit_delta_vi"] == "700đ"
    carded = next(r for r in block["rows"] if r["lever"] == "min_spend_voucher")
    assert carded["card_ref"] == "open:JC-0007"
    # a lever asked for with no published opportunity is an option that says why
    block, _ = await compare.run_compare(
        data, None, L, YDAY, ["title", "flash_sale", "cover_image"]
    )
    miss = next(r for r in block["rows"] if r["lever"] == "cover_image")
    assert miss["reason"] == "chưa có cơ hội" and len(block["rows"]) == 4


async def test_no_opportunities_at_all_still_gives_four_rows_and_no_pick() -> None:
    data = FakeEntityData([], entity={"opportunities": []})
    block, lead = await compare.run_compare(data, None, L, YDAY, [])
    assert len(block["rows"]) == 4 and not any(r["recommended"] for r in block["rows"])
    assert all(r["reason"] for r in block["rows"]) and "chưa có đủ số liệu" in lead


async def test_the_product_comes_from_the_phrase_or_the_biggest_gmv_row_from_query() -> None:
    data = _data()
    data.catalog = [{"item_id": "p2", "name": "Túi đay"}]
    assert await compare._item(data, None, [], "túi đay", YDAY) == "p2"

    class Needs(FakeCardEngine):
        def needs_item(self, kind: str) -> bool:
            return True

    big = await compare._item(_data(), Needs(per_kind={}), ["product_discount"], "", YDAY)
    assert big == "p1"  # the largest gmv among the returned rows (ties: the first)


# ------------------------------------------------------------------ C2: delegation


async def test_dataport_series_delegate_to_query_and_keep_missing_as_none() -> None:
    def script(ids: list[str], a: Any, b: Any, **kw: Any) -> dict[str, Any]:
        if kw.get("group_by") == "day":
            return {"rows": [
                {"day": date(2026, 11, 21), "gmv": 100.0, "orders": 2, "units": 3, "views": None,
                 "clicks": None, "cost_ads": 10.0, "ads_gmv_platform": 50.0},
                {"day": date(2026, 11, 22), "gmv": None, "orders": None},
            ]}  # fmt: skip
        return {"rows": [{"item": "p1", "gmv": 100.0, "orders": 1, "units": 2}]}

    svc = ScriptedQuery(script)
    rows = await svc.shop_daily(YDAY)
    assert svc.asked[0]["group_by"] == "day" and svc.asked[0]["scope"] == "shop"
    assert rows[0]["complete"] and rows[0]["views"] is None and rows[0]["ads_spend"] == 10.0
    assert not rows[1]["complete"] and rows[1]["gmv"] is None  # missing is None, never 0
    await svc.shop_daily(YDAY, "p1")
    assert svc.asked[1]["scope"] == "products" and svc.asked[1]["items"] == ["p1"]
    prod = await svc.product_daily(date(2026, 11, 16), YDAY)
    assert svc.asked[2]["group_by"] == "item" and prod[0]["item_id"] == "p1"
    pp_rows = await svc.product_profit_rows(date(2026, 11, 16), YDAY)
    assert svc.asked[3]["group_by"] == "item" and pp_rows[0]["name"] == "Sản phẩm p1"
    # L1 / L4: the product level asks for Đóng góp (before ads and AFF) and Ròng by registry id
    assert {"contribution", "profit", "margin", "roas_break_even"} <= set(svc.asked[3]["ids"])


def test_data_service_has_no_own_sql_for_metrics_and_no_reco_env() -> None:
    src = (AGENT / "data_service.py").read_text()
    assert "_reco_env" not in src and "merge_campaigns" not in src
    for table in ("shop_metrics_daily", "product_metrics_daily"):
        assert table not in src


def test_the_advisor_tools_do_no_arithmetic_on_metric_values() -> None:
    """C1: a tool reads, orders and formats what `query()` returned; it sums nothing."""
    for name in ("advisor_tools.py", "compare.py"):
        src = (AGENT / name).read_text()
        assert not re.search(r"\bsum\(", src), name
        assert not re.search(r"float\([^)]*\)\s*[-+*/]\s*float\(", src), name
    assert "ctx.data.metrics(" in (AGENT / "advisor_tools.py").read_text()


def test_the_chat_labels_use_one_id_per_label_and_never_the_after_aff_figure() -> None:
    """L4: 'Đóng góp' is before ads and AFF; the registry ids are `contribution` /
    `margin_contribution`, and Ròng is `profit` / `margin`."""
    from juli_backend.services.analytics_agent import advisor_tools
    from juli_backend.services.metrics.registry import METRICS

    ids = advisor_tools.metric_ids()
    assert {"contribution", "margin_contribution", "profit", "margin"} <= set(ids)
    labels = [METRICS[i].label_vi for i in ids]
    assert len(labels) == len(set(labels))  # one label <-> one metric id
    assert "đóng góp" in METRICS["contribution"].label_vi
