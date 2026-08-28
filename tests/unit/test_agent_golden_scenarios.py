"""Golden scenarios: capture, validate, and replay (issue #1311).

A scenario captures a real run's event history, sanitizes it, and enables
replay through the real SSE endpoint. Every event validates against the
shared packages/contracts event union.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WorkflowRun, WorkflowRunEvent
from juli_backend.services.agent.golden_scenarios.capture import (
    capture_run_as_scenario,
)
from juli_backend.services.agent.golden_scenarios.replay import (
    seed_replay_run,
)
from juli_backend.services.agent.golden_scenarios.scenarios import (
    GoldenScenario,
)


@pytest.fixture
def shop_id():
    return uuid.uuid4()


@pytest.fixture
def run_id():
    return uuid.uuid4()


@pytest.fixture
async def product_id():
    return uuid.uuid4()


@pytest.fixture
async def workflow_run(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID, product_id: uuid.UUID
):
    """Create a workflow run for testing."""
    run = WorkflowRun(
        id=run_id,
        shop_id=shop_id,
        product_id=product_id,
        state={},
        status="completed",
        prompt_version="optimize_product.v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.commit()
    return run


class TestGoldenScenarioSchema:
    """Test the scenario schema validates and loads correctly."""

    async def test_scenario_schema_valid(self):
        """A valid scenario schema should deserialize."""
        scenario_dict = {
            "scenario_id": "test-scenario-001",
            "workflow_key": "optimize_product",
            "prompt_sha256": "abc123def456",
            "captured_at": "2026-08-14T12:00:00Z",
            "events": [
                {
                    "workflow_run_id": "17c048f5-53e3-4ec7-9c3f-7a39a272d07a",
                    "sequence_number": 0,
                    "event_type": "workflow.started",
                    "timestamp": "2026-08-14T12:00:00Z",
                    "payload": {
                        "workflow_key": "optimize_product",
                        "product_ref": "prod-123",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                }
            ],
            "continuations": {},
        }
        scenario = GoldenScenario(**scenario_dict)
        assert scenario.scenario_id == "test-scenario-001"
        assert scenario.workflow_key == "optimize_product"
        assert len(scenario.events) == 1

    async def test_scenario_with_continuations(self):
        """A scenario with continuations should validate."""
        scenario_dict = {
            "scenario_id": "test-scenario-002",
            "workflow_key": "optimize_product",
            "prompt_sha256": "abc123def456",
            "captured_at": "2026-08-14T12:00:00Z",
            "events": [
                {
                    "workflow_run_id": "17c048f5-53e3-4ec7-9c3f-7a39a272d07a",
                    "sequence_number": 0,
                    "event_type": "workflow.started",
                    "timestamp": "2026-08-14T12:00:00Z",
                    "payload": {
                        "workflow_key": "optimize_product",
                        "product_ref": "prod-123",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                },
                {
                    "workflow_run_id": "17c048f5-53e3-4ec7-9c3f-7a39a272d07a",
                    "sequence_number": 1,
                    "event_type": "workflow.approval_required",
                    "timestamp": "2026-08-14T12:00:01Z",
                    "payload": {
                        "tool_call_id": "call_1",
                        "tool_name": "update_price",
                        "proposed_change": {"price": {"from": "199000", "to": "179000"}},
                        "expires_at": "2026-08-14T16:00:01Z",
                        "options": [
                            {
                                "option_id": "1",
                                "proposed_change": {"price": {"from": "199000", "to": "179000"}},
                                "rationale": "Apply the new price.",
                                "params_sha": "abc123",
                            }
                        ],
                    },
                    "v": 1,
                },
            ],
            "continuations": {
                "1": [
                    {
                        "workflow_run_id": "17c048f5-53e3-4ec7-9c3f-7a39a272d07a",
                        "sequence_number": 2,
                        "event_type": "workflow.completed",
                        "timestamp": "2026-08-14T12:00:02Z",
                        "payload": {"stop_reason": "final_response"},
                        "v": 1,
                    }
                ]
            },
        }
        scenario = GoldenScenario(**scenario_dict)
        assert scenario.scenario_id == "test-scenario-002"
        assert "1" in scenario.continuations
        assert len(scenario.continuations["1"]) == 1


class TestCaptureRunAsScenario:
    """Test capturing a real run as a scenario."""

    async def test_capture_run_creates_scenario(
        self, session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID, workflow_run
    ):
        """Capturing a run should create a valid scenario."""
        # Create some events for the run
        now = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
        events = [
            WorkflowRunEvent(
                workflow_run_id=run_id,
                sequence_number=0,
                event_type="workflow.started",
                timestamp=now,
                payload={
                    "workflow_key": "optimize_product",
                    "product_ref": "prod-123",
                    "prompt_version": "optimize_product.v1",
                },
                v=1,
            ),
            WorkflowRunEvent(
                workflow_run_id=run_id,
                sequence_number=1,
                event_type="assistant.text",
                timestamp=now,
                payload={"text": "I'll help you optimize your product."},
                v=1,
            ),
            WorkflowRunEvent(
                workflow_run_id=run_id,
                sequence_number=2,
                event_type="workflow.completed",
                timestamp=now,
                payload={"stop_reason": "final_response"},
                v=1,
            ),
        ]
        for event in events:
            session.add(event)
        await session.commit()

        # Capture the run
        scenario = await capture_run_as_scenario(session, run_id)

        # Verify scenario is created
        assert scenario.scenario_id is not None
        assert scenario.workflow_key == "optimize_product"
        assert len(scenario.events) == 3
        assert scenario.events[0]["event_type"] == "workflow.started"

    async def test_capture_removes_vendor_identifiers(
        self, session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID, workflow_run
    ):
        """Capture should sanitize raw vendor identifiers."""
        # Create events with raw vendor data
        now = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
        events = [
            WorkflowRunEvent(
                workflow_run_id=run_id,
                sequence_number=0,
                event_type="workflow.started",
                timestamp=now,
                payload={
                    "workflow_key": "optimize_product",
                    "product_ref": "prod-123",  # Real TikTok ID - should be sanitized
                    "prompt_version": "optimize_product.v1",
                },
                v=1,
            ),
            WorkflowRunEvent(
                workflow_run_id=run_id,
                sequence_number=1,
                event_type="workflow.completed",
                timestamp=now,
                payload={"stop_reason": "final_response"},
                v=1,
            ),
        ]
        for event in events:
            session.add(event)
        await session.commit()

        scenario = await capture_run_as_scenario(session, run_id)

        # product_ref should be sanitized
        assert scenario.events[0]["payload"]["product_ref"] != "prod-123"

    async def test_capture_is_deterministic(
        self, session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID, workflow_run
    ):
        """Re-running capture on the same run should be byte-identical except captured_at."""
        now = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
        event = WorkflowRunEvent(
            workflow_run_id=run_id,
            sequence_number=0,
            event_type="workflow.started",
            timestamp=now,
            payload={
                "workflow_key": "optimize_product",
                "product_ref": "prod-123",
                "prompt_version": "optimize_product.v1",
            },
            v=1,
        )
        session.add(event)
        await session.commit()

        # Capture twice
        scenario1 = await capture_run_as_scenario(session, run_id)
        scenario2 = await capture_run_as_scenario(session, run_id)

        # Should be identical except captured_at
        scenario1_dict = scenario1.model_dump()
        scenario2_dict = scenario2.model_dump()
        scenario1_dict["captured_at"] = None
        scenario2_dict["captured_at"] = None
        assert scenario1_dict == scenario2_dict


class TestReplayRun:
    """Test replaying a scenario run."""

    async def test_seed_replay_run_creates_events(self, session: AsyncSession, shop_id: uuid.UUID):
        """Seeding a replay run should create workflow_run_events."""
        # Create a replay run
        replay_run_id = uuid.uuid4()
        product_id = uuid.uuid4()
        run = WorkflowRun(
            id=replay_run_id,
            shop_id=shop_id,
            product_id=product_id,
            state={},
            status="running",
            prompt_version="optimize_product.v1",
            prompt_sha256="0" * 64,
        )
        session.add(run)
        await session.commit()

        # Create a scenario
        scenario_dict = {
            "scenario_id": "test-scenario-001",
            "workflow_key": "optimize_product",
            "prompt_sha256": "abc123",
            "captured_at": "2026-08-14T12:00:00Z",
            "events": [
                {
                    "workflow_run_id": str(replay_run_id),
                    "sequence_number": 0,
                    "event_type": "workflow.started",
                    "timestamp": "2026-08-14T12:00:00Z",
                    "payload": {
                        "workflow_key": "optimize_product",
                        "product_ref": "prod-123",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                }
            ],
            "continuations": {},
        }
        scenario = GoldenScenario(**scenario_dict)

        # Seed the replay run
        await seed_replay_run(session, replay_run_id, scenario)

        # Verify events were created
        from sqlalchemy import select

        result = await session.execute(
            select(WorkflowRunEvent).where(WorkflowRunEvent.workflow_run_id == replay_run_id)
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "workflow.started"

    async def test_replay_run_preserves_inter_event_deltas(
        self, session: AsyncSession, shop_id: uuid.UUID
    ):
        """Replay should preserve inter-event time deltas."""
        replay_run_id = uuid.uuid4()
        product_id = uuid.uuid4()
        run = WorkflowRun(
            id=replay_run_id,
            shop_id=shop_id,
            product_id=product_id,
            state={},
            status="running",
            prompt_version="optimize_product.v1",
            prompt_sha256="0" * 64,
        )
        session.add(run)
        await session.commit()

        scenario_dict = {
            "scenario_id": "test-scenario-001",
            "workflow_key": "optimize_product",
            "prompt_sha256": "abc123",
            "captured_at": "2026-08-14T12:00:00Z",
            "events": [
                {
                    "workflow_run_id": str(replay_run_id),
                    "sequence_number": 0,
                    "event_type": "workflow.started",
                    "timestamp": "2026-08-14T12:00:00Z",
                    "payload": {
                        "workflow_key": "optimize_product",
                        "product_ref": "prod-123",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                },
                {
                    "workflow_run_id": str(replay_run_id),
                    "sequence_number": 1,
                    "event_type": "assistant.text",
                    "timestamp": "2026-08-14T12:00:05Z",  # 5 seconds later
                    "payload": {"text": "Analysis complete."},
                    "v": 1,
                },
            ],
            "continuations": {},
        }
        scenario = GoldenScenario(**scenario_dict)

        await seed_replay_run(session, replay_run_id, scenario)

        from sqlalchemy import select

        result = await session.execute(
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.workflow_run_id == replay_run_id)
            .order_by(WorkflowRunEvent.sequence_number)
        )
        events = result.scalars().all()

        # Calculate delta between events
        delta = (events[1].timestamp - events[0].timestamp).total_seconds()
        # Should be approximately 5 seconds
        assert 4.9 < delta < 5.1
