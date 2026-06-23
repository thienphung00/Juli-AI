---
name: backend-executor
description: >-
  Executor Agent domain skill for Python/FastAPI backend work. Use when
  implementing API endpoints, services, auth, background jobs, or domain logic
  under src/.
---

# Backend Executor

Executor Agent domain skill for backend work. Implements issues with **mandatory
built-in TDD** (Red → Green → Refactor). Canonical requirements:
[`docs/architecture/agent-runtime.md`](../../../docs/architecture/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| FastAPI route, service, repo | `python-patterns`, `patterns.mdc` |
| pytest / API tests | `python-testing` |
| User input, auth, PII | `security.mdc`, `reliability.mdc` |
| External HTTP / webhooks | `reliability.mdc`, `observability.mdc` |
| Celery tasks | Celery MCP, `reliability.mdc` |

## Required context

- `MODULE.md` for each affected module under `src/`
- API contracts from issue / `system-design.md`
- Relevant ADRs for architectural constraints

## TDD lifecycle (built-in)

### Philosophy

Tests verify **behavior through public interfaces**, not implementation details.
Avoid mocking internal collaborators by default, testing private methods, or
asserting incidental call sequences.

### Anti-pattern: horizontal slices

Do **not** write many tests first then implement everything.

- WRONG: RED = test1..testN, then GREEN = impl1..implN
- RIGHT: RED→GREEN for **one** behavior at a time (vertical slices)

### Test surfaces in this repo

- **API (FastAPI):** `httpx.AsyncClient` + `ASGITransport` on `create_app()`;
  override deps via `app.dependency_overrides`
- **Repository / domain:** async functions with in-memory SQLite fixtures from
  `tests/unit/conftest.py`

Pick the **lowest-cost public interface** that proves the behavior:

- Pure logic → unit test the function/class
- Service boundary → integration-style test on public entrypoint
- API contract → route test: status + response shape + key fields

### Per-cycle checklist

- [ ] Test describes behavior, not implementation
- [ ] Test uses a public interface only
- [ ] RED failure matches the missing/buggy behavior
- [ ] GREEN is minimal for the current test
- [ ] Refactor only when GREEN; run tests after each step

### Workflow

1. **Plan** — confirm public interface and critical behaviors
2. **Tracer bullet** — one end-to-end RED→GREEN path
3. **Incremental loop** — one behavior per RED→GREEN cycle
4. **Refactor implementation** — when GREEN
5. **Refactor tests/fixtures** — still GREEN

## Review focus

Auth/authz, error handling, idempotency, timeouts/retries, logging, API envelope
consistency per `patterns.mdc`.

## Validation

`pytest`, `ruff check .`, `mypy src/`; migration up/down when schema changes.

## Implementation artifact (required handoff)

Before Review Agent, write `artifacts/implementations/implementation-issue-<n>.json`.

```bash
python scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain backend
```

Fill in from the implementation session:

- `redGreenRefactorEvidence` — one entry per TDD cycle (failing/passing commands)
- `filesModified`, `testsAdded`, `testsUpdated`
- `contextFilesLoaded`, `skillsLoaded`, `toolsUsed`, `toolInvocationCount`
- `implementationSummary`, `assumptions`, `risks`
- `phaseRunId` — shared with review/validation artifacts for this run

Schema: [`docs/schemas/agent-runtime/implementation-artifact.schema.json`](../../../docs/schemas/agent-runtime/implementation-artifact.schema.json)

Commit the artifact on the feature branch with the code changes.

## Must not

- Ship or validate — hand off to Review Agent
- Bypass module public surfaces documented in `MODULE.md`
