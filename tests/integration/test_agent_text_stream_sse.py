"""`assistant.text.delta` over the real SSE route on real Postgres (P61-C, D71.3).

The real `WorkflowRunner` (`stream_text=True`) drives a streaming fake model,
its events go through the real `PersistingEventSink` into real
`workflow_run_events` rows, and a real HTTP client reads the real
`GET /v1/demo/runs/{id}/events` route (a live uvicorn server where a genuine
mid-stream disconnect is needed). Proves:

- deltas reach the client while the turn is still in flight -- before its
  `assistant.text` exists anywhere;
- a reconnect with `Last-Event-ID` resumes after the last delta seen: no
  duplicate ids, and the streamed text plus the replayed tail rebuild each
  turn's text exactly once;
- two runs for two shops (one a fresh non-reference tenant each) stream at the
  same time without crossing, and a shop cannot open the other's stream.

Imports the Postgres fixtures and SSE helpers of
`test_agent_events_streaming_matrix.py` (see its docstring); skipped without a
reachable Postgres `DATABASE_URL`.
"""

# ruff: noqa: F811 -- imported pytest fixtures, see test_agent_events_lifecycle.py.

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from juli_backend.core.config.runtime import async_database_url
from juli_backend.models.models import Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.llm import FinalResponse, TextBlock, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.prompts.composer import (
    production_version,
    prompt_sha256,
    prompt_version,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason
from tests.integration.test_agent_events_streaming_matrix import (
    FakeRedisBus,
    RealCursorClient,
    _disposable_postgres_url,
    _postgres_schema_ready,
    authenticated_client,
    build_app,
    is_terminal_record,
    live_client_factory,
    parse_sse_block,
    pg_engine,
    pg_session_factory,
    seed_shop,
    set_auth_overrides,
)
from tests.support.builders import make_workflow_run
from tests.support.postgres import requires_postgres
from tests.unit.test_agent_runner_core import (
    _full_registry,
    _minimal_playbook,
    _SpyToolExecutor,
    _step,
    _turn,
)

pytestmark = requires_postgres

# The imported fixtures are used by name only (pytest resolves them from this
# module's globals); listing them keeps the imports from reading as unused.
__all__ = [
    "_disposable_postgres_url",
    "_postgres_schema_ready",
    "live_client_factory",
    "pg_engine",
    "pg_session_factory",
]

_CHUNK_CHARS = 5


def _texts(shop_label: str) -> tuple[str, str]:
    narration = (
        f"[{shop_label}] Mình đọc thông tin sản phẩm và các từ khoá người mua tìm nhiều "
        "nhất, rồi xem tiêu đề, mô tả và ảnh chính có khớp với nhu cầu đó không nhé."
    )
    final = (
        f"[{shop_label}] Tiêu đề và mô tả đã khớp từ khoá chính, ảnh rõ ràng, nên lượt "
        "này mình không đề xuất thay đổi. Mình sẽ theo dõi lượt xem và tỉ lệ bấm tuần sau."
    )
    return narration, final


def _script(narration: str, final: str) -> list[Any]:
    return [
        _turn(
            TextBlock(text=narration),
            ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={}),
        ),
        _turn(FinalResponse(content=final)),
    ]


class _GatedStreamingLLM(FakeLLMService):
    """Streams each turn's text, then holds the FIRST turn open on `gate`.

    While held, the turn's deltas are committed and published but its
    `assistant.text` has not been emitted -- the in-flight state a live client
    must already see text in.
    """

    def __init__(self, script: list[Any], gate: asyncio.Event) -> None:
        super().__init__(script=script, stream_chunk_chars=_CHUNK_CHARS)
        self._gate = gate
        self.held = asyncio.Event()
        self._calls = 0

    async def complete(self, **kwargs: Any):
        turn = await super().complete(**kwargs)
        self._calls += 1
        if self._calls == 1:
            self.held.set()
            await self._gate.wait()
        return turn


async def _seed_run(session_factory, shop: Shop) -> WorkflowRunRow:
    key = _minimal_playbook((_step("get_product_information"),)).workflow_key
    version = production_version(key)
    async with session_factory() as session:
        run = await make_workflow_run(
            session,
            shop,
            status="running",
            state=RunState().to_dict(),
            prompt_version=prompt_version(key, version),
            prompt_sha256=prompt_sha256(key, version),
        )
        await session.commit()
        await session.refresh(run)
        return run


async def _drive(session_factory, bus, shop: Shop, run_id: uuid.UUID, llm) -> StopReason:
    async with session_factory() as session:
        runner = WorkflowRunner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=PersistingEventSink(session_factory, bus, shop_id=shop.id),
            conversation_store=JsonbConversationStore(session),
            registry=_full_registry(),
            playbook=_minimal_playbook((_step("get_product_information"),)),
            stream_text=True,
        )
        result = await runner.run(run_id, product_ref="prod-stream")
        await session.commit()
        return result.stop_reason


def _rebuild(records: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    """(committed assistant.text list, streamed text per block) from SSE records."""
    import json

    committed: list[str] = []
    streamed: dict[str, str] = {}
    for record in records:
        data = json.loads(record["data"])
        if record["event"] == "assistant.text":
            committed.append(data["payload"]["text"])
        elif record["event"] == "assistant.text.delta":
            block = data["payload"]["block_id"]
            streamed[block] = streamed.get(block, "") + data["payload"]["text"]
    return committed, streamed


async def test_deltas_arrive_live_before_the_final_text_and_reconnect_has_no_duplicates(
    pg_session_factory, live_client_factory, _disposable_postgres_url
):
    user, shop = await seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop)
    narration, final = _texts("A")
    bus = FakeRedisBus()
    gate = asyncio.Event()
    llm = _GatedStreamingLLM(_script(narration, final), gate)

    # The API side gets a NullPool engine -- what production's stream sessions
    # use (`ensure_worker_session_factory`) -- so the client's deliberate
    # mid-stream disconnect, which cancels the route mid-query, can never hand
    # a closed pooled asyncpg connection to the reconnect.
    api_engine = create_async_engine(
        async_database_url(_disposable_postgres_url), poolclass=NullPool
    )
    app = build_app(
        async_sessionmaker(api_engine, expire_on_commit=False),
        subscriber=bus,
        poll_interval_s=0.02,
    )
    set_auth_overrides(app, user, shop)
    client = await live_client_factory(app)
    reader = RealCursorClient(client, f"/v1/demo/runs/{run.id}/events")

    # The worker and the API never share a connection pool in production; the
    # runner gets its own engine, like the Celery worker.
    worker_engine = create_async_engine(
        async_database_url(_disposable_postgres_url), poolclass=NullPool
    )
    worker_sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    runner_task = asyncio.create_task(_drive(worker_sessions, bus, shop, run.id, llm))
    try:
        await asyncio.wait_for(llm.held.wait(), timeout=10)
        # Live: the stream delivers a delta while the turn is still held open.
        await reader.read_until(lambda r: r.get("event") == "assistant.text.delta", timeout=10)
        assert reader.received[-1]["event"] == "assistant.text.delta"
        async with pg_session_factory() as session:
            persisted = (
                (
                    await session.execute(
                        select(WorkflowRunEventRow.event_type).where(
                            WorkflowRunEventRow.workflow_run_id == run.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "assistant.text.delta" in persisted
        assert "assistant.text" not in persisted, "the final text must not exist yet"

        # The client walked away after a delta; release the turn and reconnect
        # with its own Last-Event-ID cursor.
        gate.set()
        assert await asyncio.wait_for(runner_task, timeout=20) is StopReason.FINAL_RESPONSE
        await reader.read_until(is_terminal_record, timeout=10)
    finally:
        gate.set()
        if not runner_task.done():
            runner_task.cancel()
        await worker_engine.dispose()
        await api_engine.dispose()

    ids = [int(r["id"]) for r in reader.received]
    assert ids == sorted(ids) and len(set(ids)) == len(ids), "no duplicates across the reconnect"
    events = [r["event"] for r in reader.received]
    first_final = events.index("assistant.text")
    assert events.index("assistant.text.delta") < first_final

    committed, streamed = _rebuild(reader.received)
    assert committed == [narration, final], "each turn's text arrives exactly once"
    assert len(streamed) == 2
    for preview, text in zip(streamed.values(), committed, strict=True):
        assert preview and text.startswith(preview)


async def test_two_shops_stream_concurrently_without_crossing(pg_session_factory):
    shops: list[tuple[User, Shop]] = [
        await seed_shop(pg_session_factory),
        await seed_shop(pg_session_factory),
    ]
    runs = [await _seed_run(pg_session_factory, shop) for _, shop in shops]
    texts = [_texts("A"), _texts("B")]
    bus = FakeRedisBus()

    results = await asyncio.gather(
        *(
            _drive(
                pg_session_factory,
                bus,
                shop,
                run.id,
                FakeLLMService(script=_script(*text), stream_chunk_chars=_CHUNK_CHARS),
            )
            for (_, shop), run, text in zip(shops, runs, texts, strict=True)
        )
    )
    assert results == [StopReason.FINAL_RESPONSE, StopReason.FINAL_RESPONSE]

    app = build_app(pg_session_factory, subscriber=None)
    for (user, shop), run, (narration, final), other_run in zip(
        shops, runs, texts, reversed(runs), strict=True
    ):
        async with authenticated_client(app, user, shop) as client:
            own = await client.get(f"/v1/demo/runs/{run.id}/events")
            foreign = await client.get(f"/v1/demo/runs/{other_run.id}/events")
        assert own.status_code == 200
        assert foreign.status_code == 404, "a shop must not open another shop's stream"

        records = [
            record
            for record in (parse_sse_block(b) for b in own.text.strip("\n").split("\n\n"))
            if record is not None
        ]
        committed, streamed = _rebuild(records)
        assert committed == [narration, final]
        label = narration[:3]
        other_label = "[B]" if label == "[A]" else "[A]"
        assert all(preview.startswith(label) for preview in streamed.values())
        assert other_label not in own.text

        # Full replay after the fact == what a live client got; no duplicates.
        ids = [int(r["id"]) for r in records]
        assert ids == sorted(set(ids))
