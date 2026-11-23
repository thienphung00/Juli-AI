"""batch-1120 -- a partner reviewer on the Juli tab, through the real gate (signed tokens, SQLite).

``api/reviewer.py`` ``JULI_PIN_ENDPOINTS`` are on the allowlist for every pin; the route's
``admit_juli_pin`` admits them only on:

- the ``sample`` pin: ask / cancel / dismiss change ONLY the Juli chat tables of the sample shop,
  each with one ``reviewer_sample_write`` audit row (route + shop, never the question); "Gửi" is
  refused 403 (no cards on the sample shop) and creates nothing;
- Juli's writable sandbox pin: "Gửi" changes exactly the rows ``manual.create_manual`` changes for
  Tự tạo "Chọn" (plus the draft's own status), audited ``reviewer_sandbox_approve``;
- any other pin (a masked real shop): 403 ``read_only`` on every Juli route, nothing written.

No network, no LLM: the engine and the ports are fakes; the TikTok / Celery / HTTP tripwires of
the no-write proof are armed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.api.routes import juli_agent
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.agent_chat import AgentCardDraft, AgentConversation, AgentMessage
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.juli_agent_api import runner
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.shopee_recommendations import manual
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import utc_now_naive
from tests.support.fakes import FakeAsyncRedis
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.juli_agent_api.fakes import FakeEngine, draft_card, fake_ports
from tests.unit.test_reviewer_no_write import Tripwire, _snapshot
from tests.unit.test_reviewer_sample_shopee import _audits, _foreign_changes, _rows

J = "/v1/demo/juli"
JULI_TABLES = {
    "agent_conversations",
    "agent_messages",
    "agent_routing_decisions",
    "agent_card_drafts",
}


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("JULI_AGENT_ENABLED", "true")
    for name in ("REVIEWER_SHOP_ID", "REVIEWER_SHOP_IDS", "REVIEWER_SAMPLE_SHOP_IDS"):
        monkeypatch.delenv(name, raising=False)
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()
    yield
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()


class CountingRedis(FakeAsyncRedis):
    """The repo's ``FakeAsyncRedis`` plus the fixed-window verbs (INCR / EXPIRE / TTL)."""

    def __init__(self) -> None:
        super().__init__()
        self.ttls: dict[str, int] = {}
        self.incr_raises: Exception | None = None

    async def incr(self, key: str) -> int:
        if self.incr_raises is not None:
            raise self.incr_raises
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


@pytest.fixture(autouse=True)
def reviewer_redis():
    from juli_backend.services.juli_agent_api import reviewer_limits

    fake = CountingRedis()
    reviewer_limits.set_client(fake)
    yield fake
    reviewer_limits.set_client(None)


@pytest.fixture
def tripwire(monkeypatch) -> Tripwire:
    import httpx
    import requests
    from celery import Celery
    from celery.app.task import Task

    from juli_backend.integrations.tiktok import client as tiktok_client

    wire = Tripwire()
    monkeypatch.setattr(tiktok_client.TikTokClient, "__init__", wire.trip("TikTokClient()"))
    monkeypatch.setattr(Task, "apply_async", wire.trip("Celery Task.apply_async"))
    monkeypatch.setattr(Celery, "send_task", wire.trip("Celery.send_task"))
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", wire.trip("httpx network request")
    )
    monkeypatch.setattr(requests.Session, "send", wire.trip("requests network request"))
    return wire


async def _seed_draft(session, shop_id) -> str:
    now = utc_now_naive()
    conv = AgentConversation(
        id=uuid.uuid4(), shop_id=shop_id, platform="shopee", title="t", created_at=now,
        updated_at=now,
    )  # fmt: skip
    msg = AgentMessage(
        id=uuid.uuid4(), shop_id=shop_id, conversation_id=conv.id, role="assistant", events=[],
        status="done", created_at=now, updated_at=now,
    )  # fmt: skip
    session.add_all([conv, msg])
    await session.flush()
    ref = f"d_{uuid.uuid4().hex[:12]}"
    session.add(
        AgentCardDraft(
            id=uuid.uuid4(), shop_id=shop_id, message_id=msg.id, draft_ref=ref,
            card=draft_card(ref), status="drafted", created_at=now,
        )
    )  # fmt: skip
    await session.commit()
    return ref


@pytest.fixture
async def world(session, monkeypatch):
    """A masked seller shop, the Shopee sample shop and a Shopee shop as Juli's sandbox."""
    seller = await rv.seed_reference_shop(session)
    sample = await seed_reco_shop(session)
    sample.shop.shop_name = "Dữ liệu mẫu"
    sample.shop.tiktok_shop_id = None
    sandbox = await seed_reco_shop(session)
    await session.commit()
    for owned, capability, merchant in (
        (sandbox.shop, TikTokCapability.SANDBOX_WRITE, "sandbox-merchant"),
        (seller.shop, TikTokCapability.PRODUCTION_READ, "prod-merchant"),
    ):
        await TikTokCredentialRepo(session).create(
            owned.id,
            f"{merchant}-token",
            f"{merchant}-refresh",
            utc_now_naive() + timedelta(days=30),
            merchant_authorization_id=merchant,
            capability=capability.value,
            shop_cipher=f"cipher-{merchant}",
            scopes="seller.product.basic",
        )
    await session.commit()
    sandbox_ref = await _seed_draft(session, sandbox.shop_id)
    monkeypatch.setenv(
        "REVIEWER_SHOP_IDS",
        ",".join(str(s) for s in (seller.shop.id, sample.shop_id, sandbox.shop_id)),
    )
    monkeypatch.setenv("REVIEWER_SAMPLE_SHOP_IDS", str(sample.shop_id))
    rv.reset_caches()
    reviewer_id = await rv.make_reviewer(session)
    return {
        "seller": seller,
        "sample": sample,
        "sandbox": sandbox,
        "sandbox_ref": sandbox_ref,
        "reviewer_id": reviewer_id,
    }


def _app(session, engine):
    app = build_app(session)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _factory():
        return factory

    app.dependency_overrides[juli_agent.get_engine] = lambda: FakeEngine()
    app.dependency_overrides[juli_agent.get_ports_factory] = lambda: fake_ports
    app.dependency_overrides[juli_agent.get_run_session_factory] = _factory
    app.dependency_overrides[juli_agent.get_poll_interval_s] = lambda: 0.01
    return app


def _headers(reviewer_id, shop_header) -> dict[str, str]:
    return {"Authorization": f"Bearer {rv.token(reviewer_id)}", "X-Shop-Id": str(shop_header)}


async def _wait_runs() -> None:
    for task in list(runner._TASKS.values()):
        await asyncio.wait_for(task, timeout=10)


def _changed_tables(before, after) -> set[str]:
    return {name for name in before if set(before[name]) != set(after[name])}


# -- the list ---------------------------------------------------------------------------------


def test_the_juli_routes_are_allowlisted_and_named_apart():
    assert reviewer_gate.JULI_PIN_ENDPOINTS <= reviewer_gate.ALLOWED_ENDPOINTS
    assert {e.rsplit(":", 1)[1] for _, e in reviewer_gate.JULI_PIN_ENDPOINTS} == {
        "list_templates", "ask", "stream_message_events", "cancel_message",
        "list_conversations", "get_conversation", "send_card", "dismiss_card", "juli_enabled",
    }  # fmt: skip
    assert reviewer_gate.JULI_STATUS_ENDPOINT in reviewer_gate.JULI_PIN_ENDPOINTS
    assert reviewer_gate.JULI_PIN_WRITE_ENDPOINTS == {
        k for k in reviewer_gate.JULI_PIN_ENDPOINTS if k[0] == "POST"
    }
    assert not reviewer_gate.JULI_PIN_ENDPOINTS & set(reviewer_gate.SAMPLE_SHOP_ROUTES)
    assert not reviewer_gate.JULI_PIN_ENDPOINTS & reviewer_gate.SANDBOX_ONLY_ENDPOINTS


# -- the sample pin ----------------------------------------------------------------------------


async def test_on_the_sample_pin_juli_writes_touch_only_its_chat_tables(
    session, engine, world, tripwire
):
    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    app = _app(session, engine)
    h = _headers(reviewer_id, sid)
    async with client_for(app) as client:
        before = await _rows(session, reviewer_id=reviewer_id)
        asked = await client.post(f"{J}/ask", json={"template": "improve_gmv"}, headers=h)
        assert asked.status_code == 202, asked.text
        await _wait_runs()
        out = asked.json()
        thread = await client.get(f"{J}/conversations/{out['conversation_id']}", headers=h)
        assert thread.status_code == 200
        ref = thread.json()["messages"][1]["cards"][0]["draft_ref"]
        cancel = await client.post(f"{J}/messages/{out['message_id']}/cancel", headers=h)
        dismiss = await client.post(f"{J}/cards/{ref}/dismiss", headers=h)
        reads = [
            await client.get(f"{J}/templates", headers=h),
            await client.get(f"{J}/conversations", headers=h),
            await client.get(f"{J}/messages/{out['message_id']}/events", headers=h),
        ]
        after = await _rows(session, reviewer_id=reviewer_id)
    assert (cancel.status_code, dismiss.status_code) == (202, 200)
    assert [r.status_code for r in reads] == [200, 200, 200]
    assert _foreign_changes(before, after, sid) == []
    assert _changed_tables(before, after) <= JULI_TABLES
    audits = await _audits(session, "reviewer_sample_write")
    assert sorted(a.after["endpoint"].rsplit(":", 1)[1] for a in audits) == [
        "ask",
        "cancel_message",
        "dismiss_card",
    ]
    assert {a.shop_id for a in audits} == {sid}
    assert all("text" not in a.after and "template" not in a.after for a in audits)
    assert not tripwire.hits


async def test_send_on_the_sample_pin_is_refused_and_creates_no_card(
    session, engine, world, tripwire
):
    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    ref = await _seed_draft(session, sid)
    cards_before = await session.scalar(select(func.count()).select_from(ShopProposal))
    async with client_for(_app(session, engine)) as client:
        r = await client.post(f"{J}/cards/{ref}/send", json={}, headers=_headers(reviewer_id, sid))
    assert r.status_code == 403 and r.headers["x-juli-reviewer-denied"] == "read_only"
    assert await session.scalar(select(func.count()).select_from(ShopProposal)) == cards_before
    draft = await session.scalar(select(AgentCardDraft).where(AgentCardDraft.draft_ref == ref))
    assert draft.status == "drafted"
    assert len(await _audits(session, "reviewer_write_refused")) == 1


# -- the sandbox pin ---------------------------------------------------------------------------


async def test_send_on_the_sandbox_pin_is_the_tu_tao_card_path(session, engine, world, tripwire):
    sandbox, reviewer_id, ref = world["sandbox"], world["reviewer_id"], world["sandbox_ref"]
    before = await _rows(session, reviewer_id=reviewer_id)
    async with client_for(_app(session, engine)) as client:
        r = await client.post(
            f"{J}/cards/{ref}/send",
            json={"version_label": "Giảm 10%", "acknowledge_breaches": True},
            headers=_headers(reviewer_id, sandbox.shop_id),
        )
    assert r.status_code == 200, r.text
    assert r.json()["card_code"].startswith("JC-")
    sent = await _rows(session, reviewer_id=reviewer_id)
    # the same kind of send, done directly as Tự tạo "Chọn" does it (11 %: the same 10 % change as
    # the card just sent would be refused as a duplicate, S4)
    await manual.create_manual(
        session,
        sandbox.shop_id,
        [{"change_kind": "product_discount", "items": ["1001"], "inputs": {"discount_pct": 11}}],
        0,
        False,
        manual.Actor("seller", reviewer_id),
        now=datetime.now(UTC).replace(tzinfo=None),
        acknowledge_breaches=True,
    )
    await session.commit()
    direct = await _rows(session, reviewer_id=reviewer_id)
    assert _foreign_changes(before, sent, sandbox.shop_id) == []
    assert _changed_tables(before, sent) - {"agent_card_drafts"} == _changed_tables(sent, direct)
    [audit_row] = await _audits(session, "reviewer_sandbox_approve")
    assert audit_row.after["endpoint"] == "juli_agent:send_card"
    assert audit_row.after["card_code"] == r.json()["card_code"]
    assert not tripwire.hits


# -- any other pin -----------------------------------------------------------------------------


async def test_a_masked_pin_refuses_every_juli_route_and_writes_nothing(
    session, engine, world, tripwire
):
    reviewer_id = world["reviewer_id"]
    alias = shop_alias_id(world["seller"].shop.id)
    h = _headers(reviewer_id, alias)
    some = uuid.uuid4()
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(_app(session, engine)) as client:
        responses = [
            await client.get(f"{J}/templates", headers=h),
            await client.post(f"{J}/ask", json={"text": "GMV?"}, headers=h),
            await client.get(f"{J}/messages/{some}/events", headers=h),
            await client.post(f"{J}/messages/{some}/cancel", headers=h),
            await client.get(f"{J}/conversations", headers=h),
            await client.get(f"{J}/conversations/{some}", headers=h),
            await client.post(f"{J}/cards/{world['sandbox_ref']}/send", json={}, headers=h),
            await client.post(f"{J}/cards/{world['sandbox_ref']}/dismiss", headers=h),
        ]
    assert [r.status_code for r in responses] == [403] * 8
    assert {r.headers["x-juli-reviewer-denied"] for r in responses} == {"read_only"}
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert runner._TASKS == {}
    assert len(await _audits(session, "reviewer_write_refused")) == 4
    assert not tripwire.hits


# -- a reviewer's limits and the LLM cost guard (held for the owner's OK) ----------------------


async def _answer(session, shop_id, *, user_id, cost=None) -> None:
    now = utc_now_naive()
    conv = AgentConversation(
        id=uuid.uuid4(), shop_id=shop_id, platform="shopee", title="t", created_at=now,
        updated_at=now,
    )  # fmt: skip
    session.add(conv)
    await session.flush()
    session.add(
        AgentMessage(
            id=uuid.uuid4(), shop_id=shop_id, conversation_id=conv.id, role="assistant",
            events=[], status="done", created_by_user_id=user_id, cost_usd=cost,
            created_at=now, updated_at=now,
        )
    )  # fmt: skip
    await session.commit()


async def test_a_reviewers_limit_is_its_own_not_the_shops(session, engine, world, monkeypatch):
    monkeypatch.setenv("JULI_AGENT_LIMIT_PER_HOUR", "1")
    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    await _answer(session, sid, user_id=world["sample"].user.id)  # another user's ask this hour
    h = _headers(reviewer_id, sid)
    async with client_for(_app(session, engine)) as client:
        first = await client.post(f"{J}/ask", json={"template": "improve_gmv"}, headers=h)
        await _wait_runs()
        second = await client.post(f"{J}/ask", json={"template": "improve_gmv"}, headers=h)
    assert first.status_code == 202, first.text
    assert second.status_code == 429 and second.json()["detail"]["code"] == "juli_limited"


async def test_a_reviewers_limit_counts_across_pins(
    session, engine, world, monkeypatch, reviewer_redis
):
    monkeypatch.setenv("JULI_AGENT_LIMIT_PER_HOUR", "1")
    reviewer_id = world["reviewer_id"]
    async with client_for(_app(session, engine)) as client:
        on_sample = await client.post(
            f"{J}/ask",
            json={"template": "improve_gmv"},
            headers=_headers(reviewer_id, world["sample"].shop_id),
        )
        await _wait_runs()
        on_sandbox = await client.post(
            f"{J}/ask",
            json={"template": "improve_gmv"},
            headers=_headers(reviewer_id, world["sandbox"].shop_id),
        )
    assert on_sample.status_code == 202, on_sample.text
    assert on_sandbox.status_code == 429 and on_sandbox.json()["detail"]["code"] == "juli_limited"
    assert f"juli:agent:reviewer:{reviewer_id}:hour" in reviewer_redis.store
    assert reviewer_redis.ttls[f"juli:agent:reviewer:{reviewer_id}:day"] == 86_400


@pytest.mark.parametrize("outage", ["no_redis", "redis_error"])
async def test_a_reviewers_ask_fails_closed_without_redis(
    session, engine, world, monkeypatch, reviewer_redis, outage
):
    from redis.exceptions import ConnectionError as RedisConnectionError

    from juli_backend.services.juli_agent_api import reviewer_limits

    if outage == "no_redis":
        reviewer_limits.set_client(None)
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        reviewer_redis.incr_raises = RedisConnectionError("down")
    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    async with client_for(_app(session, engine)) as client:
        r = await client.post(
            f"{J}/ask", json={"template": "improve_gmv"}, headers=_headers(reviewer_id, sid)
        )
    assert r.status_code == 429 and r.json()["detail"]["code"] == "juli_limited"
    assert runner._TASKS == {}


async def test_the_cost_guard_counts_the_juli_tabs_own_spend(session, engine, world):
    from decimal import Decimal

    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    from juli_backend.services.shop_rules.openai_cap import default_cap_usd

    over = default_cap_usd() + Decimal("1")  # the configured cap, not a hard-coded $5
    await _answer(session, sid, user_id=world["sample"].user.id, cost=over)
    async with client_for(_app(session, engine)) as client:
        r = await client.post(
            f"{J}/ask", json={"template": "improve_gmv"}, headers=_headers(reviewer_id, sid)
        )
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "juli_cost_cap" and r.json()["detail"]["scope"] == "shop"
    assert runner._TASKS == {}


async def test_the_system_cap_stops_a_reviewers_ask(session, engine, world, monkeypatch):
    async def reached(session, *, now=None):
        return True

    monkeypatch.setattr("juli_backend.services.ops.system_cap.system_cap_reached", reached)
    sid, reviewer_id = world["sample"].shop_id, world["reviewer_id"]
    async with client_for(_app(session, engine)) as client:
        r = await client.post(
            f"{J}/ask", json={"template": "improve_gmv"}, headers=_headers(reviewer_id, sid)
        )
    assert r.status_code == 429 and r.json()["detail"]["scope"] == "system"


@pytest.mark.parametrize(
    ("which", "enabled"), [("sample", True), ("sandbox", True), ("masked", False)]
)
async def test_enabled_tells_a_reviewer_whether_the_pin_has_the_tab(
    session, engine, world, which, enabled
):
    shop = {
        "sample": world["sample"].shop_id,
        "sandbox": world["sandbox"].shop_id,
        "masked": shop_alias_id(world["seller"].shop.id),
    }[which]
    before = await _snapshot(session, reviewer_id=world["reviewer_id"])
    async with client_for(_app(session, engine)) as client:
        r = await client.get(f"{J}/enabled", headers=_headers(world["reviewer_id"], shop))
    assert (r.status_code, r.json()) == (200, {"enabled": enabled})
    after = await _snapshot(session, reviewer_id=world["reviewer_id"])
    assert [n for n in before if before[n] != after[n]] == []
    assert await _audits(session, "reviewer_read_refused") == []  # a status read, not refused


async def test_a_lost_expire_never_locks_a_reviewer_out(monkeypatch, reviewer_redis):
    """INCR returned 1 but EXPIRE failed (or the process died between them): the next ask
    sees the key without a TTL and sets one, so the window still ends."""
    from juli_backend.services.juli_agent_api import reviewer_limits

    user = uuid.uuid4()
    real_expire = reviewer_redis.expire
    failures = {"left": 1}

    async def flaky_expire(key: str, seconds: int) -> bool:
        if failures["left"]:
            failures["left"] -= 1
            raise ConnectionError("lost between INCR and EXPIRE")
        return await real_expire(key, seconds)

    monkeypatch.setattr(reviewer_redis, "expire", flaky_expire)
    first = await reviewer_limits.try_acquire(user)
    assert first.allowed is False  # fail-closed on the store error
    hour = reviewer_limits.key(user, "hour")
    assert hour in reviewer_redis.store and hour not in reviewer_redis.ttls  # the orphan
    second = await reviewer_limits.try_acquire(user)
    assert second.allowed is True
    assert reviewer_redis.ttls[hour] == reviewer_limits.HOUR_S  # healed: the window ends
    assert reviewer_redis.ttls[reviewer_limits.key(user, "day")] == reviewer_limits.DAY_S
