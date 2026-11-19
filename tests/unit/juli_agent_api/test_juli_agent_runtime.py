"""The Juli tab's run machinery without HTTP: flag reading, the sink, the runner's endings, and
the LLM / Jev adapters over fake T2 doors (no network)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.agent_chat import AgentConversation, AgentMessage
from juli_backend.models.models import Shop, User
from juli_backend.services.juli_agent_api import config, execute
from juli_backend.services.juli_agent_api.events import PersistingSink, split_private, to_wire
from juli_backend.services.juli_agent_api.ports import (
    GateJev,
    GateLLM,
    JevUnavailable,
    LLMUnavailable,
    Vendors,
)
from tests.unit.juli_agent_api.fakes import FakeEngine, fake_ports

# -- flag --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "on", "every_shop"),
    [("", False, False), ("false", False, False), ("true", True, True), ("YES", True, True)],
)
def test_the_flag_is_off_unless_switched_on(monkeypatch, raw, on, every_shop):
    monkeypatch.setenv("JULI_AGENT_ENABLED", raw)
    state = config.flag_state()
    assert state.on is on and (state.shops is None) is (every_shop or not on)
    assert state.allows(uuid.uuid4()) is every_shop


def test_a_shop_list_opens_only_those_shops_and_a_bad_list_is_off(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("JULI_AGENT_ENABLED", f"{a}, {b}")
    state = config.flag_state()
    assert state.allows(a) and state.allows(b) and not state.allows(uuid.uuid4())
    monkeypatch.setenv("JULI_AGENT_ENABLED", f"{a},not-a-uuid")
    assert config.flag_state().on is False


def test_limits_default_to_30_an_hour_and_200_a_day(monkeypatch):
    monkeypatch.delenv("JULI_AGENT_LIMIT_PER_HOUR", raising=False)
    monkeypatch.setenv("JULI_AGENT_LIMIT_PER_DAY", "-3")
    assert (config.limit_per_hour(), config.limit_per_day()) == (30, 200)


# -- wire --------------------------------------------------------------------------------------


def test_events_flat_or_nested_become_type_and_payload():
    assert to_wire({"type": "text_delta", "text": "a"}) == {
        "type": "text_delta",
        "payload": {"text": "a"},
    }
    assert to_wire({"type": "status", "payload": {"key": "thinking"}})["payload"] == {
        "key": "thinking"
    }


def test_routing_and_pending_never_reach_the_client():
    public, private = split_private(
        {"type": "done", "payload": {"stop_reasons": [], "routing": [{"x": 1}]}}
    )
    assert public == {"type": "done", "payload": {"stop_reasons": []}}
    assert private == {"routing": [{"x": 1}]}
    public, private = split_private(
        {"type": "needs_choice", "payload": {"item": "metric", "pending": {"s": 1}}}
    )
    assert "pending" not in public["payload"] and private == {"pending": {"s": 1}}


# -- runner ------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def answer(engine, session):
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name="Runner shop", platform="shopee")
    session.add(shop)
    await session.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    conv = AgentConversation(
        id=uuid.uuid4(),
        shop_id=shop.id,
        platform="shopee",
        title="t",
        created_at=now,
        updated_at=now,
    )
    msg = AgentMessage(
        id=uuid.uuid4(),
        shop_id=shop.id,
        conversation_id=conv.id,
        role="assistant",
        events=[],
        status="running",
        created_at=now,
        updated_at=now,
    )
    session.add_all([conv, msg])
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return {"shop_id": shop.id, "message_id": msg.id, "factory": factory, "session": session}


async def _run(answer, fake, **kw) -> AgentMessage:
    await execute(
        message_id=answer["message_id"],
        request={"shop_id": answer["shop_id"], "platform": "shopee", "text": "GMV?"},
        engine=fake,
        ports_factory=fake_ports,
        write_factory=answer["factory"],
        read_factory=answer["factory"],
        **kw,
    )
    session = answer["session"]
    session.expire_all()
    return await session.get(AgentMessage, answer["message_id"])


class _EngineThatFailsLikeT1(FakeEngine):
    """T1 emits ``error`` + ``done`` and re-raises an unexpected exception."""

    async def run(self, request, *, read_session_factory, llm, jev, sink):
        await sink.emit({"type": "status", "payload": {"key": "thinking", "text_vi": "x"}})
        await sink.emit({"type": "error", "payload": {"code": "failed"}})
        await sink.emit({"type": "done", "payload": {"stop_reasons": []}})
        raise self.raises or RuntimeError("boom")


async def test_an_engine_error_is_written_once_and_ends_the_answer(answer):
    row = await _run(answer, _EngineThatFailsLikeT1())
    assert row.status == "failed"
    assert [e["type"] for e in row.events] == ["status", "error"]


async def test_a_router_outage_ends_as_the_template_buttons(answer):
    row = await _run(answer, _EngineThatFailsLikeT1(raises=JevUnavailable("down")))
    assert row.status == "done" and row.stop_reasons == ["router_unavailable"]
    types = [e["type"] for e in row.events]
    assert types == ["status", "needs_choice", "done"]
    choice = row.events[1]["payload"]
    assert choice["item"] == "template" and len(choice["options"]) == 5


async def test_an_overloaded_writer_ends_as_busy(answer):
    row = await _run(answer, FakeEngine(raises=LLMUnavailable("529", busy=True)))
    assert row.status == "failed" and row.events[-1]["payload"] == {"code": "busy"}


async def test_switch_platform_is_kept_only_for_a_platform_the_business_has(answer):
    unsupported = FakeEngine(
        events=[
            {"type": "status", "payload": {"key": "thinking", "text_vi": "x"}},
            {
                "type": "unsupported",
                "payload": {
                    "text_vi": "Juli chưa hỗ trợ câu hỏi này",
                    "templates": [],
                    "switch_platform": "tiktok",
                },
            },
        ],
        drafts=[],
    )
    row = await _run(answer, unsupported)
    assert "switch_platform" not in row.events[1]["payload"]
    row = await _run(answer, unsupported, switch_platforms=frozenset({"tiktok"}))
    assert row.events[1]["payload"]["switch_platform"] == "tiktok"


async def test_the_answer_carries_the_latest_data_day(answer):
    from datetime import date

    row = await _run(answer, FakeEngine(as_of=date(2026, 11, 18)))
    assert row.events[-1]["type"] == "done"
    assert row.events[-1]["payload"]["data_until_vi"] == "18/11"


async def test_the_sink_reports_a_cancel_read_back_from_the_row(answer):
    session = answer["session"]
    row = await session.get(AgentMessage, answer["message_id"])
    row.cancel_requested = True
    await session.commit()
    sink = PersistingSink(answer["factory"], answer["shop_id"], answer["message_id"])
    with pytest.raises(BaseException) as excinfo:
        await sink.emit({"type": "status", "payload": {"key": "thinking"}})
    assert type(excinfo.value).__name__ == "CancelRequested"


# -- ports over fake T2 doors ------------------------------------------------------------------


class _Failed(Exception):
    def __init__(self, status_code=None, reason="http_status", retry_after=None):
        super().__init__(reason)
        self.status_code, self.reason, self.retry_after = status_code, reason, retry_after


class _Refused(Exception):
    pass


def _vendors(**kw: Any) -> tuple[Vendors, list[Any]]:
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    base = {
        "messages": None,
        "stream": None,
        "system_one": None,
        "call_failed": _Failed,
        "refused": _Refused,
        "sleep": sleep,
    }
    base.update(kw)
    return Vendors(**base), sleeps


async def test_parse_forces_the_tool_and_returns_its_input():
    seen: list[dict] = []

    async def messages(gate, *, purpose, body, timeout):
        seen.append({"purpose": purpose, **body})
        content = [{"type": "tool_use", "name": "intent", "input": {"metric": "gmv"}}]
        return {"content": content}, "usage"

    v, _ = _vendors(messages=messages)
    out, usage = await GateLLM(object(), v).parse("sys", {"name": "intent"}, "GMV?")
    assert out == {"metric": "gmv"} and usage == "usage"
    assert seen[0]["tool_choice"] == {"type": "tool", "name": "intent"}
    assert seen[0]["purpose"] == "agent_chat_parse" and "temperature" not in seen[0]


async def test_a_429_is_retried_twice_then_reported_busy():
    attempts: list[int] = []

    async def messages(gate, *, purpose, body, timeout):
        attempts.append(1)
        raise _Failed(429, retry_after="1")

    v, sleeps = _vendors(messages=messages)
    with pytest.raises(LLMUnavailable) as excinfo:
        await GateLLM(object(), v).text("sys", "hi")
    assert len(attempts) == 3 and sleeps == [1.0, 1.0] and excinfo.value.busy


async def test_a_400_is_not_retried():
    attempts: list[int] = []

    async def messages(gate, *, purpose, body, timeout):
        attempts.append(1)
        raise _Failed(400)

    v, _ = _vendors(messages=messages)
    with pytest.raises(LLMUnavailable) as excinfo:
        await GateLLM(object(), v).text("sys", "hi")
    assert len(attempts) == 1 and not excinfo.value.busy


async def test_a_stream_is_retried_only_before_its_first_text():
    attempts: list[int] = []

    @asynccontextmanager
    async def stream(gate, *, purpose, body, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise _Failed(529)

        class _S:
            async def __aiter__(self):
                yield "Xin "
                yield "chào"

        yield _S()

    v, _ = _vendors(stream=stream)
    out = [t async for t in GateLLM(object(), v).stream_text("sys", "hi")]
    assert out == ["Xin ", "chào"] and len(attempts) == 2


async def test_jev_failures_become_jev_unavailable_after_retries():
    attempts: list[int] = []

    async def system_one(gate, *, purpose, model, state, questions, timeout):
        attempts.append(1)
        raise _Failed(None, reason="transport")

    v, _ = _vendors(system_one=system_one)
    with pytest.raises(JevUnavailable) as excinfo:
        await GateJev(object(), v).ask({}, {"q": {"type": "noul", "instructions": "?"}})
    assert len(attempts) == 3 and "transport" in str(excinfo.value)


async def test_a_gate_refusal_is_not_retried():
    async def system_one(gate, **kw):
        raise _Refused("consent_llm_processing")

    v, sleeps = _vendors(system_one=system_one)
    with pytest.raises(JevUnavailable) as excinfo:
        await GateJev(object(), v).ask({}, {})
    assert sleeps == [] and "consent" in str(excinfo.value)
