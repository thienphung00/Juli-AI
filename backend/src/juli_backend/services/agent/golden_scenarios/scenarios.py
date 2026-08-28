"""Golden scenario schema (issue #1311, ADR-084 decision 2).

A scenario captures a real run's event history, sanitized for replay.
Scenarios validate every event against the shared packages/contracts
event union. prompt_sha256 enables staleness detection when the prompt
version changes.

Schema: {scenario_id, workflow_key, prompt_sha256, captured_at, events[],
continuations{option_id -> events[]}}.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GoldenScenario(BaseModel):
    """A captured, replayed scenario.

    - scenario_id: unique identifier for this scenario
    - workflow_key: the workflow type (e.g., "optimize_product")
    - prompt_sha256: SHA-256 of the production prompt at capture time
    - captured_at: ISO-8601 timestamp of capture
    - events: ordered event sequence from workflow start
    - continuations: option_id -> event sequence, for decision resumption
    """

    scenario_id: str = Field(..., description="Unique scenario identifier")
    workflow_key: str = Field(..., description="Workflow type (e.g., 'optimize_product')")
    prompt_sha256: str = Field(..., description="SHA-256 hash of production prompt at capture")
    captured_at: str = Field(..., description="ISO-8601 capture timestamp")
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered event sequence from workflow start",
    )
    continuations: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="option_id -> event sequence for each decision option",
    )


async def load_scenario(path: str) -> GoldenScenario:
    """Load a scenario from a JSON file.

    Args:
        path: path to the scenario JSON file

    Returns:
        parsed GoldenScenario

    Raises:
        FileNotFoundError: if the file does not exist
        pydantic.ValidationError: if the scenario is malformed
    """
    import json
    from pathlib import Path

    scenario_path = Path(path)
    with open(scenario_path) as f:
        data = json.load(f)

    return GoldenScenario(**data)
