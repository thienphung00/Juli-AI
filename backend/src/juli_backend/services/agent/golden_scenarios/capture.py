"""Capture a real run as a golden scenario (issue #1311, ADR-084 decision 2).

Given a workflow_run id, read its persisted workflow_run_events, sanitize
(no raw vendor identifiers, no credentials, no shop or product ids that
identify a real merchant), and return a versioned scenario.

Every event validates against the shared event union. Re-running capture
on the same run is deterministic: byte-identical output apart from the
recorded captured_at timestamp.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WorkflowRun, WorkflowRunEvent
from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter
from juli_backend.services.agent.golden_scenarios.scenarios import GoldenScenario


async def capture_run_as_scenario(session: AsyncSession, run_id: uuid.UUID) -> GoldenScenario:
    """Capture a real run's events as a golden scenario.

    Args:
        session: async database session
        run_id: workflow_runs.id to capture

    Returns:
        GoldenScenario with sanitized events

    Raises:
        ValueError: if the run is not found or has no events
    """
    # Fetch the run
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"Workflow run {run_id} not found")

    # Fetch all events for this run, ordered by sequence
    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.workflow_run_id == run_id)
        .order_by(WorkflowRunEvent.sequence_number)
    )
    result = await session.execute(stmt)
    events = result.scalars().all()

    if not events:
        raise ValueError(f"Workflow run {run_id} has no events")

    # Convert events to dicts and validate against the shared event union
    # Annotated: the literal's values are str/int/JSON, which mypy joins to
    # `object`, and that propagates all the way to the payload read below.
    event_dicts: list[dict[str, Any]] = []
    for event in events:
        # Convert to dict
        event_dict: dict[str, Any] = {
            "workflow_run_id": str(event.workflow_run_id),
            "sequence_number": event.sequence_number,
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            "payload": event.payload,
            "v": event.v,
        }

        # Validate against the shared event union
        try:
            WorkflowRunEventAdapter.validate_python(event_dict)
        except Exception as e:
            raise ValueError(
                f"Event {event.sequence_number} in run {run_id} does not validate: {e}"
            )

        event_dicts.append(event_dict)

    # Sanitize identifiers (no raw vendor/product IDs)
    sanitized_events = _sanitize_events(event_dicts)

    # Extract workflow_key from the first event (workflow.started)
    workflow_key: str | None = None
    for event_dict in sanitized_events:
        if event_dict["event_type"] == "workflow.started":
            payload: dict[str, Any] = event_dict["payload"]
            workflow_key = payload.get("workflow_key")
            break

    if not workflow_key:
        raise ValueError(f"Workflow run {run_id} has no workflow.started event")

    # Generate scenario ID deterministically from run_id
    # Re-running capture on the same run produces the same scenario_id
    scenario_id = f"scenario-{run_id.hex[:16]}"

    # Use the prompt_sha256 from the run model
    prompt_sha256 = run.prompt_sha256

    # Build scenario
    scenario = GoldenScenario(
        scenario_id=scenario_id,
        workflow_key=workflow_key,
        prompt_sha256=prompt_sha256,
        captured_at=datetime.now(UTC).isoformat(),
        events=sanitized_events,
        continuations={},
    )

    return scenario


def _sanitize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize events: remove raw vendor identifiers and credentials.

    Args:
        events: list of event dicts

    Returns:
        sanitized event dicts
    """
    sanitized = []
    for event in events:
        sanitized_event = event.copy()
        payload = event["payload"].copy()

        # Sanitize product_ref if present (workflow.started)
        if event["event_type"] == "workflow.started":
            if "product_ref" in payload:
                # Replace with a synthetic reference
                payload["product_ref"] = (
                    f"product-ref-{hashlib.sha256(payload['product_ref'].encode()).hexdigest()[:8]}"
                )

        sanitized_event["payload"] = payload
        sanitized.append(sanitized_event)

    return sanitized
