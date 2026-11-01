"""P82 (Supabase egress): the polled and per-tick reads stop shipping JSON blobs.

``GET /v1/demo/runs`` read every run's whole ``state`` (~20 KB uncompressed per run, every
5 s per open tab); the reaper loaded every active run's row three times per tick; the
decisions list read every run of every card. Each now reads the columns it decides on --
with the response unchanged, proved here against the pre-P82 response on a fixture whose
runs carry a long ``state``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event

from juli_backend.api.routes.agent_runs import WorkflowRunListItem
from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    Product,
    Shop,
    ToolExecution,
    User,
    WorkflowRun,
    WorkflowRunEvent,
)
from juli_backend.services.agent_runs import list_cache, listing_quality
from juli_backend.services.agent_runs.listing import RunViewer, list_runs
from juli_backend.services.demo_decisions.card_view import load_card_contexts

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 20, 8, 0, 0)
NS = uuid.UUID("8f2c0000-0000-4000-8000-000000000082")


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


SHOP, OWNER, REVIEWER, PRODUCT = _id("shop"), _id("owner"), _id("reviewer"), _id("product")
DAY0 = [
    {"code": "TITLE_LESS_THAN_40_CHARACTERS", "label_vi": "Tiêu đề quá ngắn"},
    {"code": "DESC_NO_NEW_LINE", "label_vi": "Mô tả chưa xuống dòng"},
]


def _long_state(n: int, *, diagnosis: bool = True) -> dict[str, Any]:
    window: list[Any] = [{"role": "system", "content": "s" * 2_000}, "not a message"]
    if diagnosis:
        window.append(
            {"role": "tool", "tool_name": "get_product_diagnoses", "content": {"unavailable": True}}
        )
        window.append(
            {
                "role": "tool",
                "tool_name": "get_product_diagnoses",
                "content": {"codes": DAY0, "count": 2},
            }
        )
    window += [{"role": "assistant", "content": f"{n}: " + "lorem ipsum " * 140}] * 12
    return {"conversation_window": window, "iteration": 12}


#: (name, status, workflow, minutes after T0, approved by the reviewer, ledger tool, outcome,
#: write mode, wait reason)
RUNS: list[tuple[Any, ...]] = [
    ("edit", "completed", "optimize_product_2", 300, True, "update_product_listing",
     {"ok": True, "title": "Tiêu đề mới", "confirmed_at": "2026-10-20T13:00:00Z"}, "live", None),
    ("photo", "waiting_external", "optimize_product_2", 290, False, None, None, "live", "photo"),
    ("resumed", "running", "optimize_product_2", 280, True, None, None, "live", "photo"),
    ("sim", "completed", "optimize_product_2", 270, False, "update_product_price",
     {"ok": True}, "simulated", None),
    ("create", "completed", "create_product", 260, True, "create_product",
     {"ok": True, "tiktok_product_id": "1738157559581542019"}, "live", None),
    ("refused", "failed", "create_promotion", 250, True, "create_product_discount",
     {"ok": False}, "live", None),
    ("old-team", "completed", "optimize_product_2", 10, False, "update_product_listing",
     {"ok": True, "title": "x"}, "live", None),
    ("old-mine", "completed", "optimize_product_2", 5, True, None, None, "live", None),
]  # fmt: skip

#: The sandbox reviewer's window: its own runs, and the shop's runs since this instant.
VIEWER_SINCE = T0 + timedelta(hours=1)


async def _seed(session) -> None:
    session.add_all(
        [
            User(id=OWNER, phone="+15550082101", email="p82-owner@example.com"),
            User(id=REVIEWER, phone="+15550082102", email="p82-rv@example.com"),
        ]
    )
    await session.flush()
    session.add(Shop(id=SHOP, user_id=OWNER, shop_name="P82", tiktok_shop_id="7600000000008201"))
    await session.flush()
    session.add(
        Product(
            id=PRODUCT,
            shop_id=SHOP,
            tiktok_product_id="1730000000000008201",
            name="Áo thun P82",
            title="Áo thun P82",
            status="ACTIVATE",
            update_time=T0,
        )  # fmt: skip
    )
    await session.flush()
    for n, (name, status, workflow, minutes, mine, tool, outcome, mode, reason) in enumerate(RUNS):
        card = ActionCard(
            id=_id(f"card-{name}"), shop_id=SHOP, workflow_key=workflow, subject_type="product",
            subject_id=str(PRODUCT), revision=n + 1, priority=0, severity="medium", title="x",
            description="", recommendation_payload="{}", status="approved",
        )  # fmt: skip
        session.add(card)
        await session.flush()
        if mine:
            session.add(
                ActionCardApproval(
                    action_card_id=card.id,
                    approved_by_user_id=REVIEWER,
                    approved_at=T0,
                    card_snapshot={},
                )  # fmt: skip
            )
        created = T0 + timedelta(minutes=minutes)
        live = status in ("waiting_external", "running")
        session.add(
            WorkflowRun(
                id=_id(f"run-{name}"),
                shop_id=SHOP,
                product_id=PRODUCT,
                action_card_id=card.id,
                workflow_key=workflow,
                subject_type="product",
                subject_ref=f"{PRODUCT}#{n}",
                state=_long_state(n, diagnosis=name != "create"),
                status=status,
                stop_reason=None if live else "final_response",
                prompt_version="v",
                prompt_sha256="a" * 64,
                write_mode=mode,
                external_wait_reason=reason,
                running_seconds_elapsed=n,
                created_at=created,
                completed_at=None if live else created + timedelta(minutes=2),
            )  # fmt: skip
        )
        await session.flush()
        session.add(
            WorkflowRunEvent(
                workflow_run_id=_id(f"run-{name}"),
                sequence_number=1,
                event_type="workflow.status",
                timestamp=created,
                payload={"phase_narration": f"Bước {n}"},
            )  # fmt: skip
        )
        if tool is not None:
            session.add(
                ToolExecution(
                    shop_id=SHOP,
                    approval_id=f"a-{n}",
                    tool_name=tool,
                    payload_json=json.dumps({"description": "mô tả " * 200}),
                    status="succeeded",
                    workflow_run_id=_id(f"run-{name}"),
                    tool_call_id=f"c-{n}",
                    operation=tool,
                    outcome_json=json.dumps(outcome),
                    updated_at=created + timedelta(minutes=1),
                )  # fmt: skip
            )
    await session.commit()


@pytest.fixture
def no_tiktok(monkeypatch):
    async def no_reading(session, shop_id, product_ids):
        return {}

    monkeypatch.setattr("juli_backend.services.agent_runs.listing.current_readings", no_reading)
    listing_quality.reset_cache()


@contextmanager
def _statements(session) -> Iterator[list[str]]:
    seen: list[str] = []
    engine = session.bind.sync_engine

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _wire(items) -> list[dict[str, Any]]:
    return [
        WorkflowRunListItem.model_validate(i, from_attributes=True).model_dump(mode="json")
        for i in items
    ]


def _run(name: str) -> str:
    return str(_id(f"run-{name}"))


def _card(name: str) -> str:
    return str(_id(f"card-{name}"))


def _item(name: str, **over: Any) -> dict[str, Any]:
    """One run as the pre-P82 list answered it for a seller. The expected lists below were
    checked by running the pre-P82 (3a55fd2c) ``list_runs`` on this exact fixture: its
    response equals them field for field; only the ``state`` / ``payload_json`` reads differ."""
    n = next(i for i, r in enumerate(RUNS) if r[0] == name)
    _, status, workflow, minutes, _mine, _tool, _outcome, mode, reason = RUNS[n]
    created = T0 + timedelta(minutes=minutes)
    live = status in ("waiting_external", "running")
    base = {
        "id": _run(name),
        "status": status,
        "stop_reason": None if live else "final_response",
        "product_name": "Áo thun P82",
        "created_at": created.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "completed_at": None
        if live
        else (created + timedelta(minutes=2))
        .replace(tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "running_seconds_elapsed": n,
        "latest_narration": f"Bước {n}",
        "decision_summary": None,
        "awaiting": reason if status == "waiting_external" else None,
        "decision_id": _card(name),
        "simulated": mode == "simulated",
        "run_flow": {"create_product": "create", "create_promotion": "promotion"}.get(workflow),
        "started_by_viewer": None,
        "confirmed_write": None,
        "listing_quality": None,
    }
    return base | over


async def test_seller_runs_list_is_the_pre_p82_response_without_reading_state(session, no_tiktok):
    await _seed(session)
    with _statements(session) as seen:
        items = await list_runs(session, SHOP, limit=100)
    assert _wire(items) == [_item(r[0]) for r in RUNS]
    assert seen, "the list reads Postgres"
    assert not any("workflow_runs.state" in sql for sql in seen), seen
    assert not any("payload_json" in sql for sql in seen), seen


async def test_reviewer_runs_list_is_the_pre_p82_response(session, no_tiktok):
    await _seed(session)
    viewer = RunViewer(user_id=REVIEWER, since=VIEWER_SINCE)
    with _statements(session) as seen:
        items = await list_runs(session, SHOP, limit=100, viewer=viewer)
    day0 = {"count": 2, "issues": ["Tiêu đề quá ngắn", "Mô tả chưa xuống dòng"], "read_at": None}
    expected = [
        _item(
            "edit",
            started_by_viewer=True,
            confirmed_write={
                "kind": "listing_edit",
                "tiktok_id": "1730000000000008201",
                "confirmed_at": "2026-10-20T13:00:00Z",
                "discount_pct": None,
                "fields": ["title"],
            },
            listing_quality={"before": day0, "after": None, "checked": None},
        ),  # fmt: skip
        _item("photo", started_by_viewer=False),
        _item("resumed", started_by_viewer=True),
        _item(
            "sim",
            started_by_viewer=False,
            confirmed_write={
                "kind": "price_edit",
                "tiktok_id": "1730000000000008201",
                "confirmed_at": "2026-10-20T12:31:00Z",
                "discount_pct": None,
                "fields": [],
            },
        ),  # fmt: skip
        _item(
            "create",
            started_by_viewer=True,
            confirmed_write={
                "kind": "create_product",
                "tiktok_id": "1738157559581542019",
                "confirmed_at": "2026-10-20T12:21:00Z",
                "discount_pct": None,
                "fields": [],
            },
        ),  # fmt: skip
        _item("refused", started_by_viewer=True),
        _item("old-mine", started_by_viewer=True),
    ]
    assert _wire(items) == expected
    # The ledger read selects four columns, never the WRITE payload.
    assert not any("payload_json" in sql for sql in seen), seen


async def test_the_reviewer_filter_runs_in_sql_so_the_limit_counts_visible_runs(session, no_tiktok):
    await _seed(session)
    viewer = RunViewer(user_id=REVIEWER, since=VIEWER_SINCE)
    # Seven visible runs: the old code cut the shop's newest seven first and then dropped
    # the team's old run, returning six; the filter now runs before the limit.
    items = await list_runs(session, SHOP, limit=7, viewer=viewer)
    assert [str(i.id) for i in items] == [_run(r[0]) for r in RUNS if r[0] != "old-team"]
    # A reviewer with no `since` sees only the runs it started.
    mine_only = await list_runs(session, SHOP, limit=100, viewer=RunViewer(REVIEWER, None))
    assert [str(i.id) for i in mine_only] == [_run(r[0]) for r in RUNS if r[4]]


async def test_card_contexts_read_only_each_cards_latest_run_columns(session):
    await _seed(session)
    # A second, newer run of the "edit" card: the context keeps only it.
    newer = _id("run-edit-2")
    session.add(
        WorkflowRun(
            id=newer,
            shop_id=SHOP,
            product_id=PRODUCT,
            action_card_id=_id("card-edit"),
            workflow_key="optimize_product_2",
            subject_type="product",
            subject_ref="again",
            state=_long_state(99),
            status="running",
            prompt_version="v",
            prompt_sha256="a" * 64,
            created_at=T0 + timedelta(hours=9),
        )  # fmt: skip
    )
    await session.commit()
    cards = [await session.get(ActionCard, _id(f"card-{r[0]}")) for r in RUNS]
    with _statements(session) as seen:
        contexts = await load_card_contexts(session, SHOP, cards)
    assert contexts[_id("card-edit")].latest_run.id == newer
    assert contexts[_id("card-edit")].latest_run.status == "running"
    assert contexts[_id("card-sim")].latest_run.write_mode == "simulated"
    assert contexts[_id("card-sim")].latest_run.stop_reason == "final_response"
    assert not any("workflow_runs.state" in sql for sql in seen), seen


# -- the runs list's Redis cache ----------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.deleted: list[str] = []

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.hashes.pop(key, None)


@pytest.fixture
def redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setenv(list_cache.TTL_ENV, "4")
    monkeypatch.setattr(list_cache, "_client", lambda: fake)
    return fake


def _field(user: uuid.UUID, viewer: RunViewer | None = None, limit: int = 100) -> str:
    return list_cache.entry_field(SHOP, user, viewer, limit)


async def test_cache_entries_are_per_user_viewer_and_limit_and_expire(redis, monkeypatch):
    body = {"success": True, "data": [{"id": "x"}]}
    await list_cache.write("hdr", _field(OWNER), body)
    assert await list_cache.read("hdr", _field(OWNER)) == body
    # Another user, another viewer window, another limit, another shop header: a miss.
    assert await list_cache.read("hdr", _field(REVIEWER)) is None
    assert await list_cache.read("hdr", _field(OWNER, RunViewer(OWNER, None))) is None
    assert await list_cache.read("hdr", _field(OWNER, limit=5)) is None
    assert await list_cache.read("other", _field(OWNER)) is None
    # Older than the TTL: a miss, whatever the hash's own expiry says.
    now = time.time()
    monkeypatch.setattr(list_cache.time, "time", lambda: now + 4.5)
    assert await list_cache.read("hdr", _field(OWNER)) is None


async def test_cache_disabled_or_broken_is_a_miss(redis, monkeypatch):
    await list_cache.write("hdr", _field(OWNER), {"data": []})
    redis.hashes["juli:agent_runs:list:hdr"][_field(REVIEWER)] = "{not json"
    assert await list_cache.read("hdr", _field(REVIEWER)) is None
    monkeypatch.setenv(list_cache.TTL_ENV, "0")
    assert await list_cache.read("hdr", _field(OWNER)) is None
    await list_cache.forget("hdr")
    assert redis.deleted == [], "a disabled cache does not touch Redis"
    monkeypatch.setenv(list_cache.TTL_ENV, "4")
    await list_cache.forget("hdr")
    assert redis.deleted == ["juli:agent_runs:list:hdr"]
    assert await list_cache.read("hdr", _field(OWNER)) is None


async def test_runs_route_serves_a_warm_list_from_the_cache(session, redis, no_tiktok, monkeypatch):
    from tests.support.api import build_app, client_for

    await _seed(session)
    calls = 0
    real = list_runs

    async def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr("juli_backend.services.agent_runs.list_runs", counting)
    headers = _seller_headers()
    async with client_for(build_app(session)) as client:
        first = await client.get("/v1/demo/runs", headers=headers)
        second = await client.get("/v1/demo/runs", headers=headers)
        assert first.status_code == 200, first.text
        assert second.json() == first.json()
        assert calls == 1, "the second poll within the TTL never reached Postgres"
        # A refused write leaves the cache; a write that went through drops the shop's lists.
        refused = await client.post(f"/v1/demo/runs/{uuid.uuid4()}/cancel", headers=headers)
        assert refused.status_code >= 400
        assert redis.deleted == []
        cancelled = await client.post(f"/v1/demo/runs/{_id('run-photo')}/cancel", headers=headers)
        assert cancelled.status_code < 400, cancelled.text
        assert redis.deleted == [f"juli:agent_runs:list:{SHOP}"]
        third = await client.get("/v1/demo/runs", headers=headers)
    assert third.status_code == 200
    assert calls == 2


async def test_a_degraded_read_is_never_cached(session, redis, monkeypatch):
    from tests.support.api import build_app, client_for

    await _seed(session)

    async def broken(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("juli_backend.services.agent_runs.list_runs", broken)
    async with client_for(build_app(session)) as client:
        response = await client.get("/v1/demo/runs", headers=_seller_headers())
    assert response.json() == {"success": True, "data": []}
    assert redis.hashes == {}


def _seller_headers() -> dict[str, str]:
    from tests.support import reviewer as rv

    token = rv.token(OWNER, platform=None, email="p82-owner@example.com")
    return {"Authorization": f"Bearer {token}", "X-Shop-Id": str(SHOP)}


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    from tests.support import reviewer as rv

    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)


# -- the reaper ---------------------------------------------------------------------------


async def test_a_reaper_tick_reads_decision_columns_not_state(session):
    from juli_backend.workers.tasks import reaper

    await _seed(session)

    class NoSink:
        async def emit(self, event):  # pragma: no cover - nothing is due
            raise AssertionError("nothing is due on this fixture")

    now = datetime.now(UTC)
    for name in ("photo", "resumed"):
        run = await session.get(WorkflowRun, _id(f"run-{name}"))
        run.waiting_external_since = now if name == "photo" else None
        run.started_at = now
        run.created_at = now.replace(tzinfo=None)
    await session.commit()
    session.expunge_all()
    with _statements(session) as seen:
        result = await reaper.reap_workflow_runs(
            session, now=now, sink=NoSink(), has_live_task=lambda _run_id: True
        )
    assert result.stale_runs_reaped == () and result.expired_external_waits_reaped == ()
    run_reads = [sql for sql in seen if "FROM workflow_runs" in sql]
    assert run_reads, seen
    assert not any("workflow_runs.state" in sql for sql in run_reads), run_reads
