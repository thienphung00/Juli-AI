"""A streamed run, captured by the tool from the real runner (P61-C, D71.3).

Same mechanism and rules as `test_golden_scenario_capture_from_real_runner.py`
(#1311 AC8, #1677): the events come from the real `WorkflowRunner` with
`stream_text=True`, driven by `FakeLLMService(stream_chunk_chars=...)` (which
plays each turn's text through `on_text_delta` exactly as the adapter does),
persisted by `PersistingEventSink` into real `workflow_run_events` rows and
read back by `capture_run_as_scenario`. Nothing in the fixture is typed by
hand; the run surface's reducer tests (`reduce-run-view.test.ts`) read it.

A normal run only compares; regenerate with

    JULI_REGENERATE_GOLDEN_SCENARIOS=1 python -m pytest \\
        tests/unit/test_golden_scenario_streamed_capture.py::test_the_committed_streamed_scenario_is_what_the_tool_produces
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
from freezegun import freeze_time
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.golden_scenarios import GoldenScenario
from juli_backend.services.agent.llm import FinalResponse, TextBlock, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.status import StopReason
from tests.unit.test_agent_runner_core import _minimal_playbook, _step
from tests.unit.test_agent_runner_pause_resume import (
    _full_registry,
    _SpyToolExecutor,
    _SteppingClock,
    _turn,
)
from tests.unit.test_golden_scenario_capture_from_real_runner import (
    _FROZEN_SYSTEM_CLOCK,
    _REGENERATE_ENV_VAR,
    FIXTURE_DIR,
    _capture,
    _NullPublisher,
    _seed_run,
)

FIXTURE_PATH = FIXTURE_DIR / "optimize_product_streamed.json"
_RUN_ID = uuid.UUID("00000000-0000-0000-0000-0000000057e4")
_CHUNK_CHARS = 6

NARRATION = (
    "Mình sẽ đọc thông tin sản phẩm trước, rồi so sánh với các từ khoá đang được "
    "người mua tìm nhiều nhất để xem tiêu đề có cần chỉnh không. Sau đó mình kiểm "
    "tra mô tả, thuộc tính và ảnh chính, vì đây là những phần TikTok dùng để xếp hạng "
    "sản phẩm trong kết quả tìm kiếm."
)
FINAL = (
    "Tiêu đề hiện tại đã chứa các từ khoá chính, mô tả đủ chi tiết và ảnh rõ ràng, "
    "nên lượt này mình không đề xuất thay đổi nào. Mình sẽ theo dõi số liệu tuần sau: "
    "lượt xem trang, tỉ lệ bấm vào sản phẩm và số đơn. Nếu tỉ lệ bấm giảm, mình sẽ "
    "quay lại với một đề xuất tiêu đề cụ thể để bạn xác nhận."
)


def _script() -> list[Any]:
    return [
        _turn(
            TextBlock(text=NARRATION),
            ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={}),
        ),
        _turn(FinalResponse(content=FINAL)),
    ]


async def _build(engine: AsyncEngine) -> GoldenScenario:
    with freeze_time(_FROZEN_SYSTEM_CLOCK):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            run_id = await _seed_run(session, _RUN_ID)
        async with factory() as session:
            runner = WorkflowRunner(
                llm_service=FakeLLMService(script=_script(), stream_chunk_chars=_CHUNK_CHARS),
                tool_executor=_SpyToolExecutor(result={"title": "unused"}),
                event_sink=PersistingEventSink(factory, _NullPublisher(), shop_id=None),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=_minimal_playbook((_step("get_product_information"),)),
                clock=_SteppingClock(start=1000.0, step=2.0),
                stream_text=True,
            )
            result = await runner.run(run_id, product_ref="prod-golden")
            assert result.stop_reason == StopReason.FINAL_RESPONSE
            await session.commit()
        scenario = await _capture(factory, run_id)
    return scenario.model_copy(update={"scenario_id": "optimize-product-streamed"})


@pytest.mark.asyncio
async def test_the_committed_streamed_scenario_is_what_the_tool_produces(engine: AsyncEngine):
    scenario = await _build(engine)
    if os.environ.get(_REGENERATE_ENV_VAR):
        FIXTURE_PATH.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert json.loads(scenario.model_dump_json()) == committed


@pytest.mark.asyncio
async def test_the_streamed_scenario_has_deltas_committed_by_assistant_text(engine: AsyncEngine):
    scenario = await _build(engine)
    events = [WorkflowRunEventAdapter.validate_python(e) for e in scenario.events]
    types = [e.event_type for e in events]

    texts = [e.payload.text for e in events if e.event_type == "assistant.text"]
    assert texts == [NARRATION, FINAL]
    blocks: dict[str, str] = {}
    for event in events:
        if event.event_type == "assistant.text.delta":
            blocks[event.payload.block_id] = (
                blocks.get(event.payload.block_id, "") + event.payload.text
            )
    assert len(blocks) == 2
    for streamed, final in zip(blocks.values(), texts, strict=True):
        assert streamed and final.startswith(streamed) and streamed != final

    # Every block's deltas sit immediately before its committing assistant.text.
    for index, event_type in enumerate(types):
        if event_type == "assistant.text":
            assert types[index - 1] == "assistant.text.delta"
    assert types[-1] == "workflow.completed"
