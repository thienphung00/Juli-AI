"""A1: the real port classes hand the engine `analytics_agent.types.Usage` (with `cost_usd`),
never the gate's token-only `llm_gate.vendors.Usage`. The fake gate returns the REAL gate type, so
the mismatch that failed every template on prod cannot hide behind a fake again."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest

from juli_backend.services.analytics_agent import AskRequest, run, shopee_labels
from juli_backend.services.analytics_agent import cards as cardstage
from juli_backend.services.analytics_agent.chains import run_chain
from juli_backend.services.analytics_agent.types import Usage
from juli_backend.services.juli_agent_api import config
from juli_backend.services.juli_agent_api.ports import GateJev, GateLLM, Vendors
from juli_backend.services.llm_gate.vendors import Usage as GateUsage
from tests.unit.analytics_agent.fakes import (
    AS_OF,
    FakeCardEngine,
    FakeData,
    ListSink,
    funnel_data,
)

L = shopee_labels()
TEXT = "Đang tìm hiểu: vì sao đơn hàng giảm.\nĐơn giảm vì Video kém; Sản phẩm A nên xem giảm giá."


class Refused(Exception):
    pass


class Failed(Exception):
    pass


def ch(pick: str, p: float = 0.95) -> dict[str, Any]:
    return {"type": "choice", "choice": pick, "probabilities": {pick: p, "z": round(1 - p, 4)}}


def vendors(in_tok: int = 1_000_000, out_tok: int = 0) -> Vendors:
    async def messages(gate: Any, *, purpose: str, body: dict[str, Any], timeout: float) -> Any:
        block = {"type": "text", "text": TEXT}
        if body.get("tools"):
            block = {"type": "tool_use", "name": body["tools"][0]["name"], "input": {"intents": []}}
        return {"content": [block]}, GateUsage(in_tok, out_tok)

    async def system_one(
        gate: Any,
        *,
        purpose: str,
        model: str,
        state: Any,
        questions: dict[str, Any],
        timeout: float,
    ) -> Any:
        answers: dict[str, dict[str, Any]] = {}
        for k, q in questions.items():
            if q["type"] == "noul":
                answers[k] = {"type": "noul", "noul": 0.1}
            else:
                first = next(iter(q["criteria"]))
                answers[k] = ch(first)
        return answers, GateUsage(in_tok, 0)

    @asynccontextmanager
    async def stream(gate: Any, **kw: Any) -> AsyncIterator[Any]:
        async def deltas() -> AsyncIterator[str]:
            yield TEXT

        yield deltas()

    async def sleep(_: float) -> None:
        return None

    return Vendors(
        messages=messages,
        stream=stream,
        system_one=system_one,
        call_failed=Failed,
        refused=Refused,
        sleep=sleep,
    )


async def test_jev_port_returns_engine_usage_with_cost_from_tokens() -> None:
    jev = GateJev(object(), vendors(in_tok=1_000_000))
    _, usage = await jev.ask({}, {"x": {"type": "noul", "instructions": "?"}})
    assert isinstance(usage, Usage) and not isinstance(usage, GateUsage)
    assert usage.input_tokens == 1_000_000
    assert usage.cost_usd == pytest.approx(
        config.JEV_INPUT_USD_PER_MTOK
    )  # $0.042 / MTok, output free


async def test_llm_port_returns_engine_usage_priced_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JULI_AGENT_WRITE_MODEL", raising=False)
    llm = GateLLM(object(), vendors(in_tok=1_000_000, out_tok=1_000_000))
    _, usage = await llm.text("s", "u")
    assert isinstance(usage, Usage)
    assert usage.cost_usd == pytest.approx(0.10 + 0.50)  # Haiku 5.5 per MTok in + out
    _, parse_usage = await llm.parse("s", {"name": "emit_intent"}, "u")
    assert isinstance(parse_usage, Usage) and parse_usage.cost_usd == pytest.approx(0.60)


def test_unknown_model_is_priced_like_the_default_never_free() -> None:
    assert config.llm_cost_usd("some-new-model", 1_000_000, 0) == pytest.approx(0.10)
    assert config.llm_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)


def _data() -> FakeData:
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
    return FakeData(shop, srcs, products=prods, names={"p1": "Sản phẩm A"})


async def test_card_stage_runs_over_the_real_jev_port_and_gate_usage() -> None:
    d = _data()
    chain = await run_chain(d, "orders_change", "orders", "last_7d_vs_prev_7d", AS_OF)
    out = await cardstage.card_stage(
        chains=[chain],
        data=d,
        engine=FakeCardEngine(),
        jev=GateJev(object(), vendors()),
        labels=L,
        as_of=AS_OF,
    )
    assert out.cost_usd > 0 and out.events  # no AttributeError
    assert isinstance(out.cost_usd, float)


async def test_run_end_to_end_with_real_ports_template_and_free_text() -> None:
    gate_v = vendors()
    sink = ListSink()
    res = await run(
        AskRequest(shop_id=uuid.uuid4(), platform="shopee", template="improve_gmv", as_of=AS_OF),
        llm=GateLLM(object(), gate_v),
        jev=GateJev(object(), gate_v),
        sink=sink,
        labels=L,
        data=_data(),
        card_engine=FakeCardEngine(),
    )
    assert not sink.of("error") and sink.of("done")[0]["cost_usd"] > 0 and res.cost_usd > 0
    # free text: the parse call returns usage too (no intents -> template buttons, no crash)
    sink2 = ListSink()
    await run(
        AskRequest(shop_id=uuid.uuid4(), platform="shopee", text="sao đơn giảm", as_of=AS_OF),
        llm=GateLLM(object(), gate_v),
        jev=GateJev(object(), gate_v),
        sink=sink2,
        labels=L,
        data=_data(),
        card_engine=FakeCardEngine(),
    )
    assert not sink2.of("error")
