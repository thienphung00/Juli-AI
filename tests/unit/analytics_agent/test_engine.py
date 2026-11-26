"""End-to-end engine runs with fake ports: events, routing log, templates, resume, platforms."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from juli_backend.services.analytics_agent import AskRequest, run, shopee_labels
from juli_backend.services.analytics_agent.types import TEMPLATES
from tests.unit.analytics_agent.fakes import (
    AS_OF,
    FakeCardEngine,
    FakeData,
    FakeJev,
    FakeLLM,
    ListSink,
    funnel_data,
    shop_rows,
)
from tests.unit.analytics_agent.test_cards import ch, nl
from tests.unit.analytics_agent.test_chains import _costs
from tests.unit.analytics_agent.test_routing import ans, intent

SHOP = uuid.uuid4()
L = shopee_labels()
TEXT = "Đang tìm hiểu: vì sao đơn hàng giảm.\nĐơn giảm vì Video kém; Sản phẩm A nên xem giảm giá."


def full(**over: Any) -> dict[str, dict[str, Any]]:
    base = ans() | {
        "actionable": nl(0.9),
        "kind": ch("product_discount"),
        "product": ch("p1"),
        "overlap": nl(0.1),
        "version": ch("Vừa"),
    }
    return base | over


def data_orders() -> FakeData:
    shop, srcs = funnel_data()
    prods = [
        {
            "day": r["day"],
            "item_id": "p1",
            "gmv": 5000.0 if r["day"] <= AS_OF - timedelta(days=7) else 1000.0,
            "orders": 5.0 if r["day"] <= AS_OF - timedelta(days=7) else 1.0,
            "units": 1.0,
        }
        for r in shop
    ]
    d = FakeData(shop, srcs, products=prods, names={"p1": "Sản phẩm A"})
    d.default_span = (AS_OF - timedelta(days=6), AS_OF)  # this shop's default period (#112(3))
    return d


def req(**kw: Any) -> AskRequest:
    return AskRequest(shop_id=SHOP, platform=kw.pop("platform", "shopee"), as_of=AS_OF, **kw)


async def go(
    r: AskRequest, *, llm: FakeLLM, jev: FakeJev, data: FakeData, eng: FakeCardEngine | None = None
) -> tuple[ListSink, Any]:
    sink = ListSink()
    res = await run(
        r, llm=llm, jev=jev, sink=sink, labels=L, data=data, card_engine=eng or FakeCardEngine()
    )
    return sink, res


async def test_free_text_why_full_flow() -> None:
    llm = FakeLLM({"restated_vi": "Vì sao đơn hàng giảm", "intents": [intent()]}, text=TEXT)
    jev = FakeJev(lambda s, q: full())
    sink, res = await go(req(text="sao đơn tụt"), llm=llm, jev=jev, data=data_orders())
    types = [e["type"] for e in sink.events]
    assert (
        types[0] == "status"
        and sink.events[0]["key"] == "thinking"
        and sink.events[0]["text_vi"] == "Đang tìm hiểu"
    )
    assert sink.of("restated")[0]["text_vi"] == "Đang tìm hiểu: Vì sao đơn hàng giảm"
    assert types.index("restated") < types.index("path") < types.index("card") < types.index("done")
    assert "".join(e["text"] for e in sink.of("text_delta")).startswith("Đang tìm hiểu: ")
    assert (
        sink.of("card")[0]["item_name"] == "Sản phẩm A"
        and res.cards[0]["draft_ref"] == sink.of("card")[0]["draft_ref"]
    )
    assert res.cards[0]["engine_card"]["title"]
    done = sink.of("done")[0]
    assert (
        done["stop_reasons"] == ["explained"]
        and done["cost_usd"] > 0
        and done["routing"][0]["outcome"] == "go"
    )
    assert res.events == sink.events
    # E7: direction data on every value of the path
    steps = sink.of("path")[0]["steps"]
    assert steps[0]["delta"]["dir"] == "down" and steps[0]["link"]["kind"] == "metric"
    assert any(s["link"]["kind"] == "channel" for s in steps)


async def test_one_jev_routing_request_per_intent_in_parallel() -> None:
    its = [intent(metric_phrase="orders"), intent(metric_phrase="gmv")]
    llm = FakeLLM({"restated_vi": "hai câu", "intents": its}, text=TEXT)
    jev = FakeJev(lambda s, q: full())
    sink, _ = await go(req(text="q"), llm=llm, jev=jev, data=data_orders())
    routing_calls = [c for c in jev.calls if "fits" in c[1]]
    assert len(routing_calls) == 2
    assert [e["index"] for e in sink.of("intent_block")] == [1, 2]
    # intent titles are Vietnamese (the parsed intent is English)
    assert all(e["title_vi"].startswith("Câu ") for e in sink.of("intent_block"))


async def test_more_items_beyond_cap() -> None:
    its = [intent(metric_phrase=f"m{i}") for i in range(5)]
    llm = FakeLLM({"restated_vi": "nhiều câu", "intents": its}, text=TEXT)
    sink, _ = await go(
        req(text="q"), llm=llm, jev=FakeJev(lambda s, q: full(fits=nl(0.1))), data=data_orders()
    )
    assert len(sink.of("intent_block")) == 3 and len(sink.of("more")[0]["items"]) == 2


async def test_template_skips_parse_and_routing_and_allows_card_at_any_stop() -> None:
    llm = FakeLLM(None, text="Đang tìm hiểu: Giảm chi phí.\nChi phí quảng cáo tăng; xem giảm giá.")
    shop = shop_rows(
        AS_OF - timedelta(days=40), AS_OF, orders=5.0, views=1000, clicks=100, gmv=500.0
    )
    d = FakeData(
        shop,
        costs=_costs(300.0, 300.0),
        critical={
            "items": [
                {
                    "product_id": "p9",
                    "at_stake_per_day": 5,
                    "change_kinds": ["ads_budget"],
                    "cause": {"stage": "roas"},
                }
            ]
        },
        names={"p9": "Sản phẩm Z"},
    )
    d.default_span = (AS_OF - timedelta(days=6), AS_OF)
    jev = FakeJev(lambda s, q: full(kind=ch("ads_budget")))
    sink, _ = await go(req(template="reduce_cost"), llm=llm, jev=jev, data=d)
    assert llm.parse_calls == 0 and all("fits" not in c[1] for c in jev.calls)
    assert sink.of("restated")[0]["text_vi"] == "Đang tìm hiểu: Giảm chi phí"
    assert sink.of("label")[0]["stop_reason"] == "within_noise"
    assert sink.of("card") and sink.of("card")[0]["kind"] == "ads_budget"
    assert any(
        "Không có thay đổi lớn; cơ hội lớn nhất là" in e["text"] for e in sink.of("text_replace")
    )
    assert [t.key for t in TEMPLATES] == [
        "improve_gmv",
        "improve_margin",
        "improve_conversion",
        "reduce_cost",
        "increase_visibility",
    ]


async def test_needs_choice_then_resume_from_pending_without_a_new_routing_call() -> None:
    llm = FakeLLM({"restated_vi": "Vì sao đơn giảm", "intents": [intent()]}, text=TEXT)
    jev = FakeJev(lambda s, q: full(scope=ch("shop", 0.55, "product")))
    sink, res = await go(req(text="q"), llm=llm, jev=jev, data=data_orders())
    nc = sink.of("needs_choice")[0]
    assert nc["item"] == "scope" and res.stop_reasons == ["needs_choice"] and not sink.of("card")
    n_before = len(jev.calls)
    llm2 = FakeLLM(None, text=TEXT)
    jev2 = FakeJev(lambda s, q: full())
    sink2, _ = await go(
        req(choice={"item": "scope", "value": "shop"}, pending=nc["pending"]),
        llm=llm2,
        jev=jev2,
        data=data_orders(),
    )
    assert (
        llm2.parse_calls == 0
        and all("fits" not in c[1] for c in jev2.calls)
        and n_before == len(jev.calls)
    )
    assert sink2.of("restated")[0]["text_vi"] == "Đang tìm hiểu: Vì sao đơn giảm" and sink2.of(
        "path"
    )


async def test_unsupported_offers_closest_action_with_templates_and_other_platform_switch() -> None:
    it = intent(source_phrase="tiktok shop")
    llm = FakeLLM({"restated_vi": "Doanh thu tiktok", "intents": [it]})
    sink, res = await go(
        req(text="q"), llm=llm, jev=FakeJev(lambda s, q: full(fits=nl(0.1))), data=data_orders()
    )
    u = sink.of("unsupported")[0]
    assert (
        u["text_vi"].startswith("Juli có thể")
        and len(u["templates"]) == 5
        and u["switch_platform"] == "tiktok"
    )
    assert res.stop_reasons == ["unsupported"] and not sink.of("text_delta") and not sink.of("card")


async def test_lookup_renders_data_answer_without_llm_text_or_card() -> None:
    llm = FakeLLM(
        {"restated_vi": "Doanh thu bao nhiêu", "intents": [intent(question_type="status")]}
    )
    jev = FakeJev(
        lambda s, q: full(
            mode=ch("lookup"), lookup=ch("metric_total"), metric=ch("gmv"), chain=ch("gmv_change")
        )
    )
    sink, res = await go(req(text="q"), llm=llm, jev=jev, data=data_orders())
    da = sink.of("data_answer")[0]
    assert (
        da["kind"] == "metric_total"
        and da["fresh_vi"].startswith("Số liệu đến hết")
        and da["delta"]["dir"] in ("up", "down", "flat")
    )
    assert res.stop_reasons == ["data_answer"] and not sink.of("card")
    # #110: the answer's lead sentence carries the figure; the period line is the top `meta`
    assert sink.of("lead")[0]["text_vi"].startswith(f"GMV là {da['value']}")
    assert sink.of("meta")[0]["fresh_vi"] == da["fresh_vi"]
    # rule 8: the next steps are buttons
    assert [i["label_vi"] for i in sink.of("more")[0]["items"]] == ["Theo sản phẩm", "Theo ngày"]


async def test_tiktok_before_w3_says_data_missing_and_no_card() -> None:
    llm = FakeLLM({"restated_vi": "Vì sao đơn giảm", "intents": [intent()]}, text=TEXT)
    sink, res = await go(
        req(text="q", platform="tiktok"),
        llm=llm,
        jev=FakeJev(lambda s, q: full()),
        data=data_orders(),
    )
    # #110 rule 7: no box that only says "Chưa có đề xuất cho TikTok"
    assert sink.of("label")[0]["text_vi"] == "Thiếu dữ liệu" and not sink.of("no_card")
    assert not sink.of("card") and res.stop_reasons == ["data_missing"]


async def test_parse_failure_offers_templates() -> None:
    sink, res = await go(
        req(text="q"), llm=FakeLLM(None), jev=FakeJev(lambda s, q: full()), data=data_orders()
    )
    assert sink.of("unsupported")[0]["templates"] and res.stop_reasons == ["unsupported"]


async def test_timeout_is_busy_error_and_done_still_ends_the_stream() -> None:
    class Slow(FakeData):
        async def shop_daily(self, end: Any, item: Any = None) -> list[dict[str, Any]]:
            raise TimeoutError

    shop, srcs = funnel_data()
    llm = FakeLLM({"restated_vi": "q", "intents": [intent()]}, text=TEXT)
    sink, res = await go(
        req(text="q"), llm=llm, jev=FakeJev(lambda s, q: full()), data=Slow(shop, srcs)
    )
    assert sink.of("error")[0]["code"] == "busy" and sink.events[-1]["type"] == "done"


async def test_service_data_cost_lines_come_from_the_analytics_services(monkeypatch: Any) -> None:
    from contextlib import asynccontextmanager

    from juli_backend.services.analytics_agent.data_service import ServiceData

    @asynccontextmanager
    async def factory() -> Any:
        yield None

    sd = ServiceData(factory, SHOP)
    calls: list[str] = []

    async def fake_svc(name: str, **kw: Any) -> dict[str, Any]:
        calls.append(f"{name}:{kw.get('product_id')}")
        if name == "channel_split":
            return {
                "kpis": {
                    "cost_ads": 10.0,
                    "cost_affiliate": None,
                    "cost_offers": 5.0,
                    "cost_total": 15.0,
                }
            }
        return {"shop_profit": {"net_revenue": 1000.0}}

    monkeypatch.setattr(sd, "_svc", fake_svc)
    shop = await sd.cost_lines(AS_OF, AS_OF)
    assert shop == {
        "net_revenue": 1000.0,
        "cost_ads": 10.0,
        "cost_affiliate": None,
        "cost_offers": 5.0,
    }
    prod = await sd.cost_lines(AS_OF, AS_OF, "p1")
    assert prod["net_revenue"] is None and calls[-1] == "channel_split:p1"


async def test_placeholder_restatement_is_replaced_by_the_sellers_words() -> None:
    for bad in ("Tôi hiểu: placeholder", "Đang tìm hiểu: placeholder", "placeholder"):
        llm = FakeLLM({"restated_vi": bad, "intents": [intent()]}, text=TEXT)
        sink, _ = await go(
            req(text="Vì sao đơn giảm"),
            llm=llm,
            jev=FakeJev(lambda s, q: full()),
            data=data_orders(),
        )
        assert sink.of("restated")[0]["text_vi"] == "Đang tìm hiểu: Vì sao đơn giảm", bad


async def test_untraced_numbers_are_recorded_in_done_routing_and_card_figures_blocked() -> None:
    bad = (
        "Đang tìm hiểu: vì sao đơn hàng giảm.\n"
        "Đơn tăng +194%; Sản phẩm A giảm giá, ΔGMV P50 2.000.000đ."
    )
    llm = FakeLLM(
        {"restated_vi": "Vì sao đơn hàng giảm", "intents": [intent()]}, text=bad, rewrite=TEXT
    )
    sink, _ = await go(req(text="q"), llm=llm, jev=FakeJev(lambda s, q: full()), data=data_orders())
    step = next(r for r in sink.of("done")[0]["routing"] if r.get("step") == "writer")
    assert step["rewrites"] == 1 and not step["template"]
    assert any("194" in n for n in step["numbers_failed"])
    assert any(n.startswith("card") for n in step["numbers_failed"])


class _ExpiringSession:
    """A session double: after rollback() every ORM object it handed out is expired."""

    def __init__(self) -> None:
        self.expired = False

    async def rollback(self) -> None:
        self.expired = True


class _Row:
    """Reads like an ORM row that raises once its session has rolled back."""

    def __init__(self, session: _ExpiringSession, **values: Any) -> None:
        self._s, self._v = session, values

    def __getattr__(self, name: str) -> Any:
        from sqlalchemy.orm.exc import DetachedInstanceError

        if name.startswith("_"):
            raise AttributeError(name)
        if self._s.expired:
            raise DetachedInstanceError(f"{name}: instance is not bound to a Session")
        return self._v[name]


async def test_item_reads_copy_orm_fields_before_the_rollback_expires_them(
    monkeypatch: Any,
) -> None:
    from contextlib import asynccontextmanager

    from juli_backend.repositories import shopee_analytics as repo
    from juli_backend.services.analytics_agent.data_service import ServiceData

    @asynccontextmanager
    async def factory() -> Any:
        yield _ExpiringSession()

    async def all_items(self: Any, shop_id: Any) -> list[_Row]:
        s = self._session
        return [
            _Row(s, item_id="1001", variation_id="", name="Găng tay A", seller_sku="G1"),
            _Row(
                s, item_id="1001", variation_id="v1", name="Găng tay A - size M", seller_sku="G1-M"
            ),
            _Row(s, item_id="1002", variation_id="", name=None, seller_sku=None),
        ]

    monkeypatch.setattr(repo.PlatformItemsRepo, "all_items", all_items)
    d = ServiceData(factory, SHOP)
    assert await d.item_names(["1001", "1002", "9"]) == {
        "1001": "Găng tay A",
        "1002": "1002",
        "9": "9",
    }
    assert [c["item_id"] for c in await d.catalog_search("gang tay")] == ["1001"]
    assert [c["item_id"] for c in await d.catalog_search("G1")] == ["1001"]


class _CountingData:
    """ServiceData with its analytics-service reads replaced by a counter."""

    @staticmethod
    def make(calls: list[str], monkeypatch: Any) -> Any:
        from contextlib import asynccontextmanager

        from juli_backend.services.analytics_agent.data_service import ServiceData

        @asynccontextmanager
        async def factory() -> Any:
            yield None

        sd = ServiceData(factory, SHOP)

        async def fake_svc(name: str, **kw: Any) -> dict[str, Any]:
            calls.append(f"{name}:{kw.get('product_id')}:{kw.get('start')}")
            if name == "channel_split":
                return {
                    "kpis": {"cost_ads": 30.0, "cost_affiliate": 20.0, "cost_offers": 5.0},
                    "kpis_prev": {"cost_ads": 10.0, "cost_affiliate": 20.0, "cost_offers": 4.0},
                }
            return {"shop_profit": {"net_revenue": 1000.0 if kw["start"] == AS_OF else 900.0}}

        monkeypatch.setattr(sd, "_svc", fake_svc)
        return sd


async def test_cost_lines_pair_uses_one_channel_split_for_adjacent_windows(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    sd = _CountingData.make(calls, monkeypatch)
    now, before = await sd.cost_lines_pair(
        AS_OF, AS_OF, AS_OF - timedelta(days=1), AS_OF - timedelta(days=1), "p1"
    )
    assert [c.split(":")[0] for c in calls] == ["channel_split"]  # kpis + kpis_prev
    assert now["cost_ads"] == 30.0 and before["cost_ads"] == 10.0 and now["net_revenue"] is None


async def test_cost_lines_pair_shop_reads_net_revenue_for_both_windows(monkeypatch: Any) -> None:
    calls: list[str] = []
    sd = _CountingData.make(calls, monkeypatch)
    now, before = await sd.cost_lines_pair(
        AS_OF, AS_OF, AS_OF - timedelta(days=1), AS_OF - timedelta(days=1)
    )
    assert sorted(c.split(":")[0] for c in calls) == ["channel_split", "overview", "overview"]
    assert now["net_revenue"] == 1000.0 and before["net_revenue"] == 900.0


async def test_cost_lines_pair_non_adjacent_windows_read_each_window(monkeypatch: Any) -> None:
    calls: list[str] = []
    sd = _CountingData.make(calls, monkeypatch)
    await sd.cost_lines_pair(
        AS_OF, AS_OF, AS_OF - timedelta(days=7), AS_OF - timedelta(days=7), "p1"
    )
    assert [c.split(":")[0] for c in calls] == ["channel_split", "channel_split"]


def test_chain_timeout_is_configurable_default_90_and_stays_under_the_run_timeout(
    monkeypatch: Any,
) -> None:
    from juli_backend.services.analytics_agent import engine

    monkeypatch.delenv("JULI_AGENT_CHAIN_TIMEOUT_S", raising=False)
    assert engine.chain_timeout_s() == 90.0
    monkeypatch.setenv("JULI_AGENT_CHAIN_TIMEOUT_S", "45")
    assert engine.chain_timeout_s() == 45.0
    monkeypatch.setenv("JULI_AGENT_CHAIN_TIMEOUT_S", "600")
    assert engine.chain_timeout_s() < 120.0  # below the run timeout
    for bad in ("", "abc", "-5", "0"):
        monkeypatch.setenv("JULI_AGENT_CHAIN_TIMEOUT_S", bad)
        assert engine.chain_timeout_s() == 90.0
