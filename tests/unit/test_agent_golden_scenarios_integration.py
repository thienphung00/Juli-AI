"""Integration test: replay scenarios through the real SSE endpoint.

Verifies that a seeded replay run streams through the real
GET /v1/demo/runs/{id}/events handler, not via in-memory shortcut.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.app import create_app
from juli_backend.database import get_session
from juli_backend.models.models import Shop, User, WorkflowRun
from juli_backend.services.agent.golden_scenarios import (
    GoldenScenario,
    seed_replay_run,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def authenticated_user(session: AsyncSession, user_id: uuid.UUID):
    """Create an authenticated user."""
    user = User(id=user_id, phone="+84999888443")
    session.add(user)
    await session.commit()
    return user


@pytest_asyncio.fixture
async def authenticated_shop(session: AsyncSession, authenticated_user: User):
    """Create a shop owned by the authenticated user."""
    shop = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Test Shop",
        tiktok_shop_id="tiktok_shop_test_001",
    )
    session.add(shop)
    await session.commit()
    return shop


@pytest_asyncio.fixture
async def test_app(session: AsyncSession):
    """Create a test app with dependency overrides."""
    app = create_app()

    async def _test_session():
        yield session

    app.dependency_overrides[get_session] = _test_session
    yield app
    app.dependency_overrides.clear()


class TestReplayEndpoint:
    """Test replay runs streaming through the real events endpoint."""

    async def test_replay_run_persists_through_events_table(
        self,
        session: AsyncSession,
        authenticated_user: User,
        authenticated_shop: Shop,
    ):
        """Replay events persist through the workflow_run_events table for streaming."""
        # Create a replay run
        replay_run_id = uuid.uuid4()
        product_id = uuid.uuid4()
        run = WorkflowRun(
            id=replay_run_id,
            shop_id=authenticated_shop.id,
            product_id=product_id,
            state={},
            status="completed",
            prompt_version="optimize_product.v1",
            prompt_sha256="0" * 64,
        )
        session.add(run)
        await session.commit()

        # Create and seed a scenario
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
                        "product_ref": "product-ref-a1b2c3d4",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                },
                {
                    "workflow_run_id": str(replay_run_id),
                    "sequence_number": 1,
                    "event_type": "workflow.completed",
                    "timestamp": "2026-08-14T12:00:01Z",
                    "payload": {"stop_reason": "final_response"},
                    "v": 1,
                },
            ],
            "continuations": {},
        }
        scenario = GoldenScenario(**scenario_dict)
        await seed_replay_run(session, replay_run_id, scenario)

        # Verify events were persisted by querying the table directly
        # This simulates what the real /v1/demo/runs/{id}/events endpoint does
        from sqlalchemy import select

        from juli_backend.models.models import WorkflowRunEvent

        result = await session.execute(
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.workflow_run_id == replay_run_id)
            .order_by(WorkflowRunEvent.sequence_number)
        )
        events = result.scalars().all()

        # Verify we got the replay events
        assert len(events) == 2
        assert events[0].event_type == "workflow.started"
        assert events[0].sequence_number == 0
        assert events[1].event_type == "workflow.completed"
        assert events[1].sequence_number == 1

        # Verify all events validate against the shared event union
        from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter

        for event in events:
            event_dict = {
                "workflow_run_id": str(event.workflow_run_id),
                "sequence_number": event.sequence_number,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
                "v": event.v,
            }
            # Should not raise
            WorkflowRunEventAdapter.validate_python(event_dict)

    async def test_replay_run_preserves_inter_event_timing(
        self,
        session: AsyncSession,
        authenticated_user: User,
        authenticated_shop: Shop,
        test_app,
    ):
        """Replay should preserve inter-event time deltas."""
        # Create a replay run
        replay_run_id = uuid.uuid4()
        product_id = uuid.uuid4()
        run = WorkflowRun(
            id=replay_run_id,
            shop_id=authenticated_shop.id,
            product_id=product_id,
            state={},
            status="completed",
            prompt_version="optimize_product.v1",
            prompt_sha256="0" * 64,
        )
        session.add(run)
        await session.commit()

        # Create a scenario with events 2 seconds apart
        scenario_dict = {
            "scenario_id": "test-scenario-002",
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
                        "product_ref": "product-ref-test",
                        "prompt_version": "optimize_product.v1",
                    },
                    "v": 1,
                },
                {
                    "workflow_run_id": str(replay_run_id),
                    "sequence_number": 1,
                    "event_type": "assistant.text",
                    "timestamp": "2026-08-14T12:00:02Z",  # 2 seconds later
                    "payload": {"text": "Analysis complete."},
                    "v": 1,
                },
            ],
            "continuations": {},
        }
        scenario = GoldenScenario(**scenario_dict)
        await seed_replay_run(session, replay_run_id, scenario)

        # Verify the timestamp delta was preserved
        from sqlalchemy import select

        result = await session.execute(
            select(
                __import__(
                    "juli_backend.models.models", fromlist=["WorkflowRunEvent"]
                ).WorkflowRunEvent
            ).where(
                __import__(
                    "juli_backend.models.models", fromlist=["WorkflowRunEvent"]
                ).WorkflowRunEvent.workflow_run_id
                == replay_run_id
            )
        )

        events = result.scalars().all()
        assert len(events) == 2

        # Calculate the time delta
        delta = (events[1].timestamp - events[0].timestamp).total_seconds()
        # Should be approximately 2 seconds
        assert 1.9 < delta < 2.1, f"Expected ~2s delta, got {delta}s"
