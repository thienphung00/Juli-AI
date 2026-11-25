"""J-H1 (a written summary on every answer) and J-H2 (ROAS hoà vốn at shop / product / campaign
level from the shared profit service). Synthetic numbers; the writer LLM is a stub."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, entities, lookup, routing, summary
from juli_backend.services.analytics_agent.data_service import SHOP_SCOPE_VI
from juli_backend.services.analytics_agent.entities import campaign_row, campaign_verdict
from tests.unit.analytics_agent.fakes import (
    FakeData,
    FakeEntityData,
    FakeLLM,
    ScriptedQuery,
    shop_rows,
)
from tests.unit.analytics_agent.test_engine import SHOP, go
from tests.unit.analytics_agent.test_j_windows_entities import (
    CAMPS,
    YDAY,
    _ask,
    _lookup_jev,
    _shop,
    _week_rows,
)
from tests.unit.analytics_agent.test_routing import intent
from tests.unit.analytics_agent.test_weekly import _run_plan

PRESET = "last_7d_vs_prev_7d"
_REQ = AskRequest(shop_id=SHOP, platform="shopee", as_of=YDAY, text="q")


def _body(sink: Any) -> str:
    """The text the seller reads: deltas, replaced by the last replace."""
    text = "".join(e["text"] for e in sink.of("text_delta"))
    for e in sink.of("text_replace"):
        text = e["text"]
    return text


def _named(da: dict[str, Any], sentence: str) -> str:
    """A stub writer text that names the window and the freshness day, as the prompt asks."""
    main = da["window_vi"].split(" so với ")[0]
    return f"Kỳ {main}. {da['fresh_vi']}. {sentence}"


# ------------------------------------------------------------------ J-H1: one summary per answer


async def test_lookup_answer_gets_a_summary_from_its_result() -> None:
    first = await _ask(FakeEntityData(_shop()), intent(metric_phrase="gmv"), _lookup_jev("gmv"))
    da = first[0].of("data_answer")[0]
    llm = FakeLLM(
        {"restated_vi": "câu hỏi", "intents": [intent(metric_phrase="gmv")]},
        text=_named(da, f"GMV là {da['value']}."),
    )
    sink, res = await go(_REQ, llm=llm, jev=_lookup_jev("gmv"), data=FakeEntityData(_shop()))
    text = _body(sink)
    assert da["value"] in text and da["fresh_vi"] in text
    assert len(llm.stream_calls) == 1  # one writer call for the answer
    assert [r for r in res.routing if r.get("step") == "summary"][0]["template"] is False


async def test_campaign_list_gets_a_summary() -> None:
    data = FakeEntityData(_shop(), entity={"campaigns": CAMPS})
    it = intent(question_type="status", entity_phrase="ad campaign", metric_phrase="roas")
    first, _ = await _ask(data, it, _lookup_jev("roas"))
    da = first.of("data_answer")[0]
    llm = FakeLLM(
        {"restated_vi": "câu hỏi", "intents": [it]},
        text=_named(da, "Chiến dịch CDN/01 đang dưới ROAS hoà vốn."),
    )
    sink, res = await go(_REQ, llm=llm, jev=_lookup_jev("roas"), data=data)
    assert "CDN/01" in _body(sink) and len(llm.stream_calls) == 1
    assert res.routing[-1]["step"] == "summary" and res.routing[-1]["template"] is False


async def test_voucher_list_gets_a_summary_via_the_template_when_the_llm_is_silent() -> None:
    data = FakeEntityData(
        _shop(),
        entity={
            "voucher": _week_rows(2.0, 400.0, 20.0),
            "voucher_codes": [{"code": "VC-A", "orders": 9, "gmv": 900.0, "cost": 90.0}],
        },
    )
    sink, res = await _ask(
        data,
        intent(question_type="status", entity_phrase="voucher", metric_phrase="orders"),
        _lookup_jev("orders"),
    )
    da = sink.of("data_answer")[0]
    text = _body(sink)
    assert da["fresh_vi"] in text and da["window_vi"].split(" so với ")[0] in text
    assert res.routing[-1]["template"] is True  # the stub wrote nothing: code text, still shown


async def test_weekly_plan_gets_a_summary_naming_window_freshness_and_the_card() -> None:
    sink, res = await _run_plan()
    text = _body(sink)
    assert "Số liệu đến hết 22/11" in text and "16/11–22/11" in text
    assert [r for r in res.routing if r.get("step") == "summary"]
    assert len([e for e in sink.of("text_replace")]) <= 1  # one writer pass, one fallback


async def test_card_answer_summary_names_the_card_and_never_its_values() -> None:
    events = [
        {
            "type": "card",
            "draft_ref": "d_1",
            "kind": "ads_budget",
            "kind_vi": "Ngân sách quảng cáo",
            "item_id": None,
            "item_name": None,
            "versions": [{"label_vi": "Phương án 1", "value_vi": "+1.234.567đ"}],
        }
    ]
    sent: list[str] = []

    async def delta(t: str) -> None:
        sent.append(t)

    async def replace(t: str) -> None:
        sent[:] = [t]

    llm = FakeLLM(None, text="Mình đã tạo thẻ ngân sách quảng cáo cho bạn. Số liệu đến hết 22/11.")
    meta = await summary.write_summary(
        llm, delta, replace, events, fresh_vi="Số liệu đến hết 22/11"
    )
    assert meta is not None and meta["template"] is False
    assert "1.234.567" not in "".join(sent)


async def test_guard_removes_a_number_that_is_not_in_the_result() -> None:
    data = FakeEntityData(_shop())
    first, _ = await _ask(data, intent(metric_phrase="gmv"), _lookup_jev("gmv"))
    da = first.of("data_answer")[0]
    bad = _named(da, "GMV là 99.999.999đ, tăng 77%.")
    llm = FakeLLM({"restated_vi": "q", "intents": [intent(metric_phrase="gmv")]}, text=bad)
    sink, res = await go(_REQ, llm=llm, jev=_lookup_jev("gmv"), data=data)
    final = _body(sink)
    assert "99.999.999" not in final and "77%" not in final and da["value"] in final
    step = res.routing[-1]
    assert step["template"] is True and any(i.startswith("number:") for i in step["issues"])


async def test_unavailable_llm_falls_back_to_the_template() -> None:
    class Down(FakeLLM):
        async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
            raise RuntimeError("down")
            yield ""  # pragma: no cover

    events = [
        {
            "type": "data_answer",
            "title_vi": "GMV",
            "window_vi": "16/11–22/11",
            "fresh_vi": "Số liệu đến hết 22/11",
            "value": "14.000.000đ",
        }
    ]
    out: list[str] = []

    async def noop(t: str) -> None:
        out.append(t)

    meta = await summary.write_summary(Down(None), noop, noop, events)
    assert meta is not None and meta["template"] is True
    assert "14.000.000đ" in out[-1] and "Số liệu đến hết 22/11" in out[-1]


async def test_summary_is_skipped_when_the_chain_already_wrote_text() -> None:
    from tests.unit.analytics_agent.fakes import FakeJev
    from tests.unit.analytics_agent.test_engine import TEXT, data_orders, full

    llm = FakeLLM({"restated_vi": "Vì sao đơn hàng giảm", "intents": [intent()]}, text=TEXT)
    _, res = await go(_REQ, llm=llm, jev=FakeJev(lambda s, q: full()), data=data_orders())
    assert not [r for r in res.routing if r.get("step") == "summary"]


# ------------------------------------------------------------------ J-H2 (A): campaigns


def _camp_script(rows: list[dict[str, Any]], shop_be: float | None) -> Any:
    def script(ids: list[str], a: Any, b: Any, **kw: Any) -> dict[str, Any]:
        return {"values": {"roas_break_even": shop_be}, "rows": rows}

    return script


def _crow(key: str, name: str, spend: float, gmv: float, be: float | None) -> dict[str, Any]:
    return {"campaign": key, "campaign_name": name, "cost_ads": spend, "ads_gmv_direct": gmv,
            "roas_direct": gmv / spend, "roas_break_even": be,
            "contribution": None if be is None else gmv / be}  # fmt: skip


async def test_unknown_campaign_takes_the_shop_value_labelled_ca_shop() -> None:
    rows = [_crow("k1", "CDN/05", 100, 300, None), _crow("k2", "CDN/06", 100, 300, 2.0)]
    unknown, own = await ScriptedQuery(_camp_script(rows, 3.09)).campaign_rows(YDAY, YDAY)
    assert unknown["break_even"] == 3.09 and unknown["break_even_scope"] == SHOP_SCOPE_VI
    assert own["break_even_scope"] is None and own["break_even"] == pytest.approx(2.0)
    assert "hoà vốn 3,09 (cả shop)" in campaign_row(unknown)["value_vi"]
    assert "(cả shop)" not in campaign_row(own)["value_vi"]
    (none_known,) = await ScriptedQuery(_camp_script(rows[:1], None)).campaign_rows(YDAY, YDAY)
    assert none_known["break_even"] is None


async def test_client_shaped_fixture_roas_above_break_even_is_lai() -> None:
    rows = [_crow("a", "CDN/A", 200, 1000, 2.5), _crow("c", "CDN/B", 100, 0.0, None)]
    camps = await ScriptedQuery(_camp_script(rows, 3.09)).campaign_rows(YDAY, YDAY)
    by = {c["name"]: c for c in camps}
    assert by["CDN/A"]["roas"] == pytest.approx(5.0) and by["CDN/A"]["break_even"] == 2.5
    assert campaign_verdict(by["CDN/A"]) == "Lãi"
    assert (
        by["CDN/B"]["break_even_scope"] == SHOP_SCOPE_VI and campaign_verdict(by["CDN/B"]) == "Lỗ"
    )


# ------------------------------------------------------------------ J-H2 (B): shop level


async def test_lookup_reads_the_overview_profit_block() -> None:
    def ov(a: Any, b: Any) -> dict[str, Any]:
        # `shop_profit` has no contribution_before_ads; the figure lives in `profit`
        return {"shop_profit": {"net_revenue": 1000}, "profit": {"break_even_roas": 3.09}}

    shop = shop_rows(YDAY.replace(month=9), YDAY, gmv=1000.0, orders=3.0)
    out = await lookup.run_lookup(
        FakeData(shop, overview=ov), entities_labels(), "metric_total", "roas_break_even",
        PRESET, YDAY,
    )  # fmt: skip
    assert out["value"] == "3,09" and out["value_raw"] == pytest.approx(3.09)


def entities_labels() -> Any:
    from tests.unit.analytics_agent.test_engine import L

    return L


# ------------------------------------------------------------------ J-H2: product level


async def test_product_value_is_the_query_rows_contribution_and_break_even() -> None:
    def script(ids: list[str], a: Any, b: Any, **kw: Any) -> dict[str, Any]:
        return {"values": {"contribution": 250.0, "roas_break_even": 4.0, "profit": 100.0}}

    svc = ScriptedQuery(script)
    got = await svc.product_profit("p1", YDAY, YDAY)
    assert svc.asked[0]["scope"] == "products" and svc.asked[0]["items"] == ["p1"]
    assert got is not None
    assert got["contribution_before_ads"] == 250.0 and got["break_even_roas"] == 4.0
    empty = await ScriptedQuery(lambda *a, **k: {"values": {"profit": None}}).product_profit(
        "p1", YDAY, YDAY
    )
    assert empty is None  # nothing known: no product row, never zeros


class _ProductData(FakeEntityData):
    async def product_profit(self, item: str, a: Any, b: Any) -> dict[str, Any] | None:
        return {"profit": 100.0, "margin_pct": 10.0, "break_even_roas": 3.5,
                "contribution_before_ads": 300.0}  # fmt: skip


async def test_product_question_answers_from_the_products_own_value() -> None:
    (ans,) = await entities.run_entity(
        None, _ProductData(_shop()), intent(), "roas_break_even", PRESET, YDAY,
        item_id="p1", item_name="Sản phẩm A",
    )  # fmt: skip
    assert ans["title_vi"] == "ROAS hoà vốn · Sản phẩm A" and ans["value"] == "3,50"
    assert ans["contribution_vi"] == "Đóng góp trước quảng cáo 300đ"


async def test_which_products_lose_after_ads_lists_the_losing_ones_with_their_figures() -> None:
    rows = [
        {"item_id": "p1", "name": "Sản phẩm A", "profit": -500.0, "ad_spend": 900.0,
         "contribution_before_ads": 400.0, "break_even_roas": 4.5},
        {"item_id": "p2", "name": "Sản phẩm B", "profit": 800.0, "ad_spend": 100.0,
         "contribution_before_ads": 900.0, "break_even_roas": 2.0},
    ]  # fmt: skip
    it = intent(raw_text="sản phẩm nào lỗ sau quảng cáo", metric_phrase="lỗ sau quảng cáo")
    assert routing.entity_kind(it) == "product_loss"
    (ans,) = await entities.run_entity(
        "product_loss", FakeEntityData(_shop(), entity={"product_rows": rows}), it,
        "profit", PRESET, YDAY,
    )  # fmt: skip
    assert ans["title_vi"] == "Sản phẩm đang lỗ sau quảng cáo"
    (row,) = ans["rows"]
    assert row["label_vi"] == "Sản phẩm A" and row["value_vi"] == "Lỗ 500đ"
    assert (
        "đóng góp trước quảng cáo 400đ" in row["detail_vi"] and "hoà vốn 4,50" in row["detail_vi"]
    )
    none_lose = await entities.run_entity(
        "product_loss", FakeEntityData(_shop(), entity={"product_rows": rows[1:]}), it,
        "profit", PRESET, YDAY,
    )  # fmt: skip
    assert none_lose[0]["title_vi"] == "Chưa có sản phẩm nào lỗ sau quảng cáo"
