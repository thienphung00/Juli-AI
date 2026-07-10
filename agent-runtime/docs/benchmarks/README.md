# Agent Runtime Benchmark Fixtures

Issue-like specs for the unified benchmark framework
([`agent-runtime/docs/agent-runtime-benchmarks.md`](../../architecture/agent-runtime-benchmarks.md)).

Each fixture defines scope small enough for a single agent session, expected artifacts,
and deterministic checks. Use a real GitHub issue when it matches the type; otherwise
run against the fixture description directly.

| Type | File | `taskType` value |
|------|------|------------------|
| A | [`task-type-a-new-feature.md`](task-type-a-new-feature.md) | `new-feature` |
| B | [`task-type-b-bug-fix.md`](task-type-b-bug-fix.md) | `bug-fix` |
| C | [`task-type-c-architecture-refactor.md`](task-type-c-architecture-refactor.md) | `architecture-refactor` |
| D | [`task-type-d-multi-agent-workflow.md`](task-type-d-multi-agent-workflow.md) | `multi-agent-workflow` |

## Fixture selection

| Harness question | Use type |
|------------------|----------|
| Can the harness deliver a small feature end-to-end? | A |
| Can Executor reproduce and fix a bug with TDD? | B |
| Can the harness refactor without breaking boundaries? | C |
| Can agents hand off cleanly across phases? | D |

## Artifact output (all types)

Every run must produce:

1. `agent-runtime/artifacts/implementations/implementation-issue-<n>.json`
2. `agent-runtime/artifacts/reviews/review-issue-<n>.json`
3. `agent-runtime/artifacts/validation/validation-issue-<n>.json`
4. `agent-runtime/artifacts/optimization/harness-issue-<n>-<phaseRunId>.json`
5. `artifacts/benchmarks/<benchmarkRunId>.json`

Product-development optimization is optional unless the fixture or rerun protocol
requires it.
