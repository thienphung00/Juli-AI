# backend/src/juli_backend/services/agent/golden_scenarios

## Purpose

Golden scenarios: capture, validate, and replay (issue #1311, ADR-084 decision 2).

A scenario captures a real run's event history, sanitizes it (no raw vendor identifiers, no credentials), and enables replay through the real SSE endpoint. Every event validates against the shared packages/contracts event union. Scenarios are versioned by prompt_sha256 so staleness is detectable when the prompt changes.

**Three parts:**

1. **Capture tool** (`capture.py`). Given a real `workflow_run` id, read its persisted `workflow_run_events`, sanitize (no raw vendor identifiers, no credentials, no shop or product ids that identify a real merchant), and return a versioned scenario.

2. **Scenario schema and loader** (`scenarios.py`). A scenario is `{scenario_id, workflow_key, prompt_sha256, captured_at, events[], continuations{option_id -> events[]}}`. Every event validates against the **shared event union** in `packages/contracts`.

3. **Server-side replay source** (`replay.py`). Starting a demo run seeds the scenario's events as real `workflow_run_events` rows for that run, so `GET /v1/demo/runs/{id}/events` serves them **unmodified** — same endpoint, same protocol, same replay and `Last-Event-ID` semantics. Timestamps rebased to now; recorded inter-event deltas preserved so pacing is the run's own. When a decision request is answered, the chosen option's continuation is appended.

## Public Interface

```python
from juli_backend.services.agent.golden_scenarios import (
    GoldenScenario,
    load_scenario,
    capture_run_as_scenario,
    seed_replay_run,
    append_continuation,
)
```

- `GoldenScenario` — Pydantic schema for a captured scenario
- `load_scenario(path: str) -> GoldenScenario` — load scenario from JSON file
- `capture_run_as_scenario(session, run_id) -> GoldenScenario` — capture a real run
- `seed_replay_run(session, run_id, scenario) -> None` — seed events for replay
- `append_continuation(session, run_id, option_id, scenario) -> None` — append decision outcome

## Key behaviors

- **Validation against shared union** — every event in capture and replay validates against `packages/contracts/src/agent-events.ts`'s `AgentEvent` union via `WorkflowRunEventAdapter`. A scenario that does not validate fails CI.
- **Sanitization** — product_ref and other vendor identifiers are hashed during capture; no raw IDs survive.
- **Deterministic capture** — re-running capture on the same run produces the same scenario_id and events (only `captured_at` changes).
- **Timestamp rebasing** — replay runs have timestamps rebased to now, but inter-event deltas are preserved exactly, so pacing matches the captured run.
- **Continuation handling** — when a seller decides on a CONFIRM pause, the chosen option's continuation events are appended with a new sequence number range.

## Acceptance criteria

- The capture tool run against a real persisted run produces a scenario file that validates against the shared event union, with zero raw vendor identifiers and zero credentials — asserted by scanning the output, not by inspection.
- Re-running capture on the same run is deterministic: byte-identical output apart from the recorded `captured_at`.
- A seeded replay run streams through the **real** `/v1/demo/runs/{id}/events` handler. The test asserts the handler was used, not that the bytes look right — an in-memory shortcut here is the defect this slice exists to prevent.
- `Last-Event-ID` reconnect against a replay run is gapless and duplicate-free, using the same sequence semantics as a live run.
- Answering a decision request appends **that option's** continuation and no other; an unknown option id is refused.
- Inter-event deltas are preserved within tolerance, and timestamps are rebased so nothing renders a date from the capture day.
- A scenario whose `prompt_sha256` does not match the current production prompt is detectable by a command, and the command is documented.
- At least one scenario is committed: captured by this tool from the real runner driven by the scripted-fake integration path, covering a confirm pause with two options and both continuations. **Hand-authored event JSON is not acceptable input** — if the tool cannot produce it, fix the tool.

## Dependencies

- `sqlalchemy.ext.asyncio` — async database access
- `juli_backend.models.models` — `WorkflowRun`, `WorkflowRunEvent` ORM models
- `juli_backend.services.agent.events.envelope` — `WorkflowRunEvent`, `WorkflowRunEventAdapter` validation
- `pydantic` — `GoldenScenario` schema

## Out of scope

- Tool invocation CLI (will be in infra/scripts or agents/tools in a future slice)
- Prompt staleness detection command (future slice)
- Demo UI for scenario replay (UI domain)
