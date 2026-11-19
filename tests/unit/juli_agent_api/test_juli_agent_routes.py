"""The Juli tab's routes over SQLite with a fake engine (T1) and fake ports (T2).

Covers acceptance A2: flag off -> 404; capability gate (TikTok admitted, the engine answers);
POST ask (text / template / choice, one running answer per conversation -> 409, limits -> 429
with ``retry_at``); SSE replay with ``Last-Event-ID``; cancel; conversations shared per shop;
card send (403 read-only, idempotent) and dismiss; templates + ``shop_state``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import juli_agent
from juli_backend.core.security import get_current_user
from juli_backend.database import get_session
from juli_backend.models.agent_chat import (
    AgentCardDraft,
    AgentConversation,
    AgentMessage,
    AgentRoutingDecision,
)
from juli_backend.models.models import Shop, User
from juli_backend.services.agent.abuse_limits import (
    InMemoryAbuseLimitGate,
    set_agent_abuse_limit_gate,
)
from juli_backend.services.juli_agent_api import runner
from tests.unit.juli_agent_api.fakes import FakeEngine, fake_ports

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("JULI_AGENT_ENABLED", "true")
    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate())
    yield
    set_agent_abuse_limit_gate(None)


@pytest_asyncio.fixture
async def world(engine, session):
    owner = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    member = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    stranger = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add_all([owner, member, stranger])
    await session.flush()
    shop = Shop(user_id=owner.id, shop_name="Juli tab shop", platform="shopee")
    other = Shop(user_id=stranger.id, shop_name="Other shop", platform="shopee")
    session.add_all([shop, other])
    await session.commit()
    # detached: a route's rollback on the shared test session must not expire the request's
    # user / shop (each request has its own session in production)
    for obj in (owner, member, stranger, shop, other):
        session.expunge(obj)
    return {"owner": owner, "member": member, "stranger": stranger, "shop": shop, "other": other}


@pytest.fixture(scope="module")
def shared_app():
    """One app for the module: building it is the slow part; each test re-points its overrides."""
    return create_app()


@pytest_asyncio.fixture
async def app_for(engine, session, shared_app):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = shared_app

    async def _session():
        yield session

    async def _factory():
        return factory

    def make(user: User, shop: Shop, fake: FakeEngine, creator: Any = None):
        o = application.dependency_overrides
        o.clear()
        o[get_session] = _session
        o[get_current_user] = lambda: user
        o[get_active_shop] = lambda: shop
        o[juli_agent.get_engine] = lambda: fake
        o[juli_agent.get_ports_factory] = lambda: fake_ports
        o[juli_agent.get_run_session_factory] = _factory
        o[juli_agent.get_poll_interval_s] = lambda: 0.01
        if creator is not None:
            o[juli_agent.get_card_creator] = lambda: creator
        return application

    yield make
    application.dependency_overrides.clear()


def _client(app):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_runs() -> None:
    for task in list(runner._TASKS.values()):
        await asyncio.wait_for(task, timeout=5)


def _frames(body: str) -> list[dict[str, str]]:
    out = []
    for raw in body.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in raw.split("\n") if line and not line.startswith(":")
        )
        if fields:
            out.append(fields)
    return out


async def _ask(client, **body) -> Any:
    return await client.post("/v1/demo/juli/ask", json=body, headers={"X-Shop-Id": "x"})


# -- flag and gates ----------------------------------------------------------------------------


async def test_flag_off_answers_404_on_every_route(app_for, world, monkeypatch):
    monkeypatch.delenv("JULI_AGENT_ENABLED", raising=False)
    app = app_for(world["owner"], world["shop"], FakeEngine())
    async with _client(app) as c:
        responses = [
            await c.get("/v1/demo/juli/templates"),
            await _ask(c, text="Vì sao GMV giảm?"),
            await c.get("/v1/demo/juli/conversations"),
            await c.post("/v1/demo/juli/cards/d_000000000001/send", json={}),
        ]
    assert [r.status_code for r in responses] == [404, 404, 404, 404]


async def test_a_shop_list_flag_opens_only_the_listed_shop(app_for, world, monkeypatch):
    monkeypatch.setenv("JULI_AGENT_ENABLED", str(world["shop"].id))
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        listed = await c.get("/v1/demo/juli/templates")
    async with _client(app_for(world["stranger"], world["other"], FakeEngine())) as c:
        unlisted = await c.get("/v1/demo/juli/templates")
    assert (listed.status_code, unlisted.status_code) == (200, 404)


async def test_a_tiktok_shop_is_admitted_so_the_engine_answers(app_for, world, session):
    world["shop"].platform = "tiktok"
    stored = await session.get(Shop, world["shop"].id)
    stored.platform = "tiktok"
    await session.commit()
    fake = FakeEngine()
    async with _client(app_for(world["owner"], world["shop"], fake)) as c:
        r = await _ask(c, template="improve_gmv")
        await _wait_runs()
    assert r.status_code == 202, r.text
    assert fake.requests[0]["platform"] == "tiktok"


async def test_templates_carry_the_shop_state(app_for, world):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await c.get("/v1/demo/juli/templates")
    body = r.json()
    assert [t["key"] for t in body["templates"]][:2] == ["improve_gmv", "improve_margin"]
    assert body["shop_state"] == {"read_only": False}


# -- ask, run, stream -------------------------------------------------------------------------


async def test_an_ask_runs_the_engine_and_stores_the_answer(app_for, world, session):
    fake = FakeEngine()
    async with _client(app_for(world["owner"], world["shop"], fake)) as c:
        r = await _ask(c, text="  Vì sao GMV giảm?  ")
        await _wait_runs()
    assert r.status_code == 202, r.text
    out = r.json()
    assert fake.requests[0]["text"] == "Vì sao GMV giảm?"
    assert fake.requests[0]["shop_id"] == world["shop"].id
    session.expire_all()
    answer = await session.get(AgentMessage, uuid.UUID(out["message_id"]))
    assert answer.status == "done" and answer.stop_reasons == ["explained"]
    assert answer.ms is not None and float(answer.cost_usd) == pytest.approx(0.0012)
    types = [e["type"] for e in answer.events]
    assert types == ["status", "restated", "text_delta", "text_delta", "card", "done"]
    assert [e["seq"] for e in answer.events] == [1, 2, 3, 4, 5, 6]
    assert "routing" not in answer.events[-1]["payload"]
    routing = (await session.scalars(select(AgentRoutingDecision))).all()
    assert [(x.intent, x.answers) for x in routing] == [
        ("why_changed", {"chain": {"choice": "gmv"}})
    ]
    drafts = (await session.scalars(select(AgentCardDraft))).all()
    assert [d.status for d in drafts] == ["drafted"]
    assert drafts[0].draft_ref.startswith("d_") and drafts[0].card["engine_card"]["versions"]
    conv = await session.get(AgentConversation, uuid.UUID(out["conversation_id"]))
    assert conv.title == "Vì sao GMV giảm?" and conv.platform == "shopee"


async def test_the_event_stream_replays_after_last_event_id(app_for, world):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, template="improve_gmv")
        await _wait_runs()
        mid = r.json()["message_id"]
        full = await c.get(f"/v1/demo/juli/messages/{mid}/events", headers={"X-Shop-Id": "x"})
        tail = await c.get(
            f"/v1/demo/juli/messages/{mid}/events",
            headers={"X-Shop-Id": "x", "Last-Event-ID": "4"},
        )
    assert full.status_code == 200 and full.headers["content-type"].startswith("text/event-stream")
    frames = _frames(full.text)
    assert [f["id"] for f in frames] == ["1", "2", "3", "4", "5", "6"]
    assert [f["event"] for f in frames][-1] == "done"
    assert frames[2]["data"] == '{"text":"GMV giảm "}'  # data = the payload JSON
    assert [f["id"] for f in _frames(tail.text)] == ["5", "6"]


async def test_the_stream_follows_a_running_answer_to_its_end(app_for, world):
    gate = asyncio.Event()
    fake = FakeEngine(gate=gate)
    async with _client(app_for(world["owner"], world["shop"], fake)) as c:
        r = await _ask(c, text="GMV?")
        mid = r.json()["message_id"]
        await asyncio.sleep(0.05)
        reader = asyncio.create_task(
            c.get(f"/v1/demo/juli/messages/{mid}/events", headers={"X-Shop-Id": "x"})
        )
        await asyncio.sleep(0.05)
        gate.set()
        await _wait_runs()
        body = (await asyncio.wait_for(reader, timeout=5)).text
    assert [f["event"] for f in _frames(body)][0] == "status"
    assert [f["event"] for f in _frames(body)][-1] == "done"


async def test_one_running_answer_per_conversation_else_409(app_for, world):
    gate = asyncio.Event()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(gate=gate))) as c:
        first = await _ask(c, text="GMV?")
        conv = first.json()["conversation_id"]
        second = await _ask(c, conversation_id=conv, text="Còn AOV?")
        gate.set()
        await _wait_runs()
        third = await _ask(c, conversation_id=conv, text="Còn AOV?")
        await _wait_runs()
    assert second.status_code == 409 and second.json()["detail"]["code"] == "juli_busy"
    assert third.status_code == 202


@pytest.mark.parametrize(
    "body",
    [{}, {"text": "a", "template": "improve_gmv"}, {"template": "nope"}, {"text": "   "}],
)
async def test_an_ask_needs_exactly_one_valid_question(app_for, world, body):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, **body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] in {"juli_ask_invalid", "juli_unknown_template"}


async def test_a_choice_answers_the_pending_question_with_its_saved_state(app_for, world):
    pending_state = {"chain": "gmv", "step": 2}
    asking = FakeEngine(
        events=[
            {"type": "status", "payload": {"key": "thinking", "text_vi": "Đang tìm hiểu"}},
            {
                "type": "needs_choice",
                "payload": {
                    "item": "window",
                    "question_vi": "So với khi nào?",
                    "options": [{"label_vi": "7 ngày", "value": "last_7d"}],
                    "pending": pending_state,
                },
            },
            {"type": "done", "payload": {"stop_reasons": ["needs_choice"]}},
        ],
        drafts=[],
    )
    async with _client(app_for(world["owner"], world["shop"], asking)) as c:
        r = await _ask(c, text="GMV giảm?")
        await _wait_runs()
        conv = r.json()["conversation_id"]
        history = (await c.get(f"/v1/demo/juli/conversations/{conv}")).json()
    choice_payload = history["messages"][1]["events"][1]["payload"]
    assert "pending" not in choice_payload  # the routing state never reaches the client
    answering = FakeEngine(drafts=[])
    async with _client(app_for(world["owner"], world["shop"], answering)) as c:
        r2 = await _ask(c, conversation_id=conv, choice={"item": "window", "value": "last_7d"})
        await _wait_runs()
    assert r2.status_code == 202, r2.text
    assert answering.requests[0]["pending"] == pending_state
    assert answering.requests[0]["choice"] == {"item": "window", "value": "last_7d"}


async def test_a_choice_with_nothing_pending_is_422(app_for, world):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, text="GMV?")
        await _wait_runs()
        again = await _ask(
            c, conversation_id=r.json()["conversation_id"], choice={"item": "metric", "value": "x"}
        )
    assert again.status_code == 422 and again.json()["detail"]["code"] == "juli_no_pending_choice"


async def test_the_hourly_limit_answers_429_with_the_retry_time(
    app_for, world, session, monkeypatch
):
    monkeypatch.setenv("JULI_AGENT_LIMIT_PER_HOUR", "2")
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        for _ in range(2):
            assert (await _ask(c, text="GMV?")).status_code == 202
            await _wait_runs()
        limited = await _ask(c, text="GMV?")
    assert limited.status_code == 429
    detail = limited.json()["detail"]
    assert detail["code"] == "juli_limited" and detail["retry_at"].endswith("Z")
    retry_at = datetime.fromisoformat(detail["retry_at"].removesuffix("Z"))
    assert _now() + timedelta(minutes=50) < retry_at <= _now() + timedelta(hours=1, seconds=5)
    assert int(limited.headers["Retry-After"]) > 0


async def test_limits_are_per_shop(app_for, world, monkeypatch):
    monkeypatch.setenv("JULI_AGENT_LIMIT_PER_HOUR", "1")
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        assert (await _ask(c, text="GMV?")).status_code == 202
        await _wait_runs()
    async with _client(app_for(world["stranger"], world["other"], FakeEngine())) as c:
        other = await _ask(c, text="GMV?")
        await _wait_runs()
    assert other.status_code == 202


async def test_a_failing_engine_ends_the_answer_with_an_error_event(app_for, world, session):
    async with _client(
        app_for(world["owner"], world["shop"], FakeEngine(raises=RuntimeError("x")))
    ) as c:
        r = await _ask(c, text="GMV?")
        await _wait_runs()
    session.expire_all()
    answer = await session.get(AgentMessage, uuid.UUID(r.json()["message_id"]))
    assert answer.status == "failed"
    assert answer.events[-1]["type"] == "error"
    assert answer.events[-1]["payload"] == {"code": "failed"}


async def test_cancel_stops_a_running_answer(app_for, world, session):
    gate = asyncio.Event()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(gate=gate))) as c:
        r = await _ask(c, text="GMV?")
        mid = r.json()["message_id"]
        await asyncio.sleep(0.05)
        cancelled = await c.post(f"/v1/demo/juli/messages/{mid}/cancel")
        await _wait_runs()
        again = await c.post(f"/v1/demo/juli/messages/{mid}/cancel")
    assert cancelled.status_code == 202 and again.json() == {"status": "cancelled"}
    session.expire_all()
    answer = await session.get(AgentMessage, uuid.UUID(mid))
    assert answer.status == "cancelled" and answer.stop_reasons == ["cancelled"]
    assert answer.events[-1]["type"] == "done" and answer.events[-1]["payload"]["cancelled"]


# -- history (shared per shop) ------------------------------------------------------------------


async def test_conversations_are_shared_by_the_shops_members(app_for, world):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, text="GMV?")
        await _wait_runs()
    conv = r.json()["conversation_id"]
    async with _client(app_for(world["member"], world["shop"], FakeEngine())) as c:
        listed = (await c.get("/v1/demo/juli/conversations")).json()["conversations"]
        thread = (await c.get(f"/v1/demo/juli/conversations/{conv}")).json()
    assert [x["id"] for x in listed] == [conv] and {"title", "updated_at"} <= set(listed[0])
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    answer = thread["messages"][1]
    [card] = answer["cards"]
    assert {k: card[k] for k in ("status", "sent_card_code", "version_label")} == {
        "status": "drafted",
        "sent_card_code": None,
        "version_label": None,
    }
    assert answer["events"][-1]["type"] == "done" and "data_until_vi" in answer


async def test_another_shops_conversation_and_message_are_missing(app_for, world):
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, text="GMV?")
        await _wait_runs()
    out = r.json()
    async with _client(app_for(world["stranger"], world["other"], FakeEngine())) as c:
        listed = (await c.get("/v1/demo/juli/conversations")).json()["conversations"]
        thread = await c.get(f"/v1/demo/juli/conversations/{out['conversation_id']}")
        events = await c.get(f"/v1/demo/juli/messages/{out['message_id']}/events")
        cancel = await c.post(f"/v1/demo/juli/messages/{out['message_id']}/cancel")
        send = await c.post("/v1/demo/juli/cards/d_000000000001/send", json={})
    assert listed == []
    assert [thread.status_code, events.status_code, cancel.status_code, send.status_code] == [
        404,
        404,
        404,
        404,
    ]


# -- cards -------------------------------------------------------------------------------------


class _Creator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, session, shop_id, variants, chosen, user_id, **kw):
        self.calls.append({"variants": variants, "chosen": chosen, "user_id": user_id, **kw})
        return {"id": str(uuid.uuid4()), "code": "JC-2611-0001", "status": "sent"}


async def _with_draft(app_for, world) -> str:
    async with _client(app_for(world["owner"], world["shop"], FakeEngine())) as c:
        r = await _ask(c, text="GMV?")
        await _wait_runs()
        thread = (await c.get(f"/v1/demo/juli/conversations/{r.json()['conversation_id']}")).json()
    return thread["messages"][1]["cards"][0]["draft_ref"]


async def test_send_creates_the_card_through_the_tu_tao_path(app_for, world, session):
    ref = await _with_draft(app_for, world)
    creator = _Creator()
    async with _client(app_for(world["member"], world["shop"], FakeEngine(), creator)) as c:
        sent = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={"version_label": "Giảm 5%"})
        again = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={"version_label": "Giảm 5%"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["card_code"] == "JC-2611-0001" and sent.json()["already_sent"] is False
    assert again.json()["already_sent"] is True and again.json()["card_code"] == "JC-2611-0001"
    [call] = creator.calls
    assert call["chosen"] == 1 and call["user_id"] == world["member"].id
    assert call["variants"][1] == {
        "label": "Giảm 5%",
        "change_kind": "product_discount",
        "items": ["1001"],
        "inputs": {"discount_pct": 5},
    }
    assert call["cards"] is None and call["draft_ref"] == ref
    session.expire_all()
    draft = (await session.scalars(select(AgentCardDraft))).one()
    assert (draft.status, draft.card_code, draft.version_label) == (
        "sent",
        "JC-2611-0001",
        "Giảm 5%",
    )


async def test_send_without_a_label_takes_the_recommended_version(app_for, world):
    ref = await _with_draft(app_for, world)
    creator = _Creator()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(), creator)) as c:
        r = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={})
    assert r.status_code == 200 and creator.calls[0]["chosen"] == 0


async def test_send_refuses_an_unknown_version(app_for, world):
    ref = await _with_draft(app_for, world)
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(), _Creator())) as c:
        r = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={"version_label": "Giảm 90%"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "juli_unknown_version"


async def test_send_on_a_read_only_shop_is_403_and_creates_nothing(app_for, world, monkeypatch):
    ref = await _with_draft(app_for, world)

    async def _read_only(session, shop_id):
        return True

    monkeypatch.setattr("juli_backend.services.subscriptions.is_read_only", _read_only)
    creator = _Creator()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(), creator)) as c:
        r = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={})
        state = (await c.get("/v1/demo/juli/templates")).json()["shop_state"]
    assert r.status_code == 403 and creator.calls == []
    assert state == {"read_only": True}


async def test_send_with_a_pending_deletion_is_403(app_for, world, monkeypatch):
    ref = await _with_draft(app_for, world)
    monkeypatch.setattr("juli_backend.services.privacy.deletion_pending", lambda user: True)
    creator = _Creator()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(), creator)) as c:
        r = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={})
    assert r.status_code == 403 and creator.calls == []


async def test_dismiss_logs_only_and_blocks_a_later_send(app_for, world, session):
    ref = await _with_draft(app_for, world)
    creator = _Creator()
    async with _client(app_for(world["owner"], world["shop"], FakeEngine(), creator)) as c:
        dismissed = await c.post(f"/v1/demo/juli/cards/{ref}/dismiss")
        send = await c.post(f"/v1/demo/juli/cards/{ref}/send", json={})
    assert dismissed.json() == {"status": "dismissed"}
    assert send.status_code == 409 and creator.calls == []
    session.expire_all()
    draft = (await session.scalars(select(AgentCardDraft))).one()
    assert draft.status == "dismissed" and draft.card["draft_ref"] == ref
