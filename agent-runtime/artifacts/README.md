# CI/CD and Agent Runtime Artifacts

Machine-readable outputs for the AI-native harness ([ADR-003](../docs/adr/003-ai-native-cicd-policy.md))
and Agent Runtime ([`agent-runtime/docs/agent-runtime-artifacts.md`](../agent-runtime/docs/agent-runtime-artifacts.md)).

## Directory layout

| Directory | Producer | Consumer | Commit? |
|-----------|----------|----------|---------|
| `reviews/` | `review` skill, `generate_review_artifact.py` | `validate`, `pr.yml`, Meta Agent | **Yes** — CI gate |
| `validation/` | `validate` skill, `generate_validation_artifact.py`, nightly audits | `ship`, `pr.yml`, Meta Agent | **Yes** — CI gate |
| `implementations/` | Executor Agent | Review Agent, Meta Agent | **Yes** — small JSON |
| `optimization/` | Meta Agent | Harness config, Architect backlog | **Yes** — small JSON |
| `benchmarks/` | Benchmark runs | Meta Agent, Architect | **Yes** — benchmark reports |
| `releases/` | `ship` skill, `release.yml` | Rollback / hotfix agents | **Yes** |
| `runtime/raw/` | Agents (verbose logs) | Local debugging only | **No** — gitignored |
| `runtime/logs/` | Agents (session telemetry) | Local debugging only | **No** — gitignored |

## File naming

| Pattern | Example |
|---------|---------|
| `reviews/review-issue-<n>.json` | `review-issue-42.json` |
| `validation/validation-issue-<n>.json` | `validation-issue-42.json` |
| `validation/audit-<type>-<date>.json` | `audit-drift-2026-06-23.json` |
| `implementations/implementation-issue-<n>.json` | `implementation-issue-42.json` |
| `optimization/harness-issue-<n>-<phaseRunId>.json` | `harness-issue-42-2026-06-23-a1b2c3.json` |
| `optimization/product-development-<id>.json` | `product-development-unclear-decomposition-2026-06.json` |
| `benchmarks/<benchmarkRunId>.json` | `bug-fix-2026-06-23-a1b2.json` |
| `releases/release-<version>.json` | `release-1.2.3.json` |

## Schemas

- **ADR-003 CI gates:** [`docs/deployment/implementation-guide.md`](../docs/deployment/implementation-guide.md) (review, validation, release)
- **Agent Runtime (JSON Schema):** [`agent-runtime/docs/schemas/`](../agent-runtime/docs/schemas/)
- **Benchmark protocol:** [`agent-runtime/docs/agent-runtime-benchmarks.md`](../agent-runtime/docs/agent-runtime-benchmarks.md)

## Commit policy

**Commit** review, validation, implementation, optimization, release, and audit JSON on feature
branches so CI and Meta Agent can read them across sessions.

**Do not commit** raw logs under `runtime/raw/` or `runtime/logs/`.

## Editing rules

- Do not edit a review artifact from the `validate` skill — regenerate via `review` if findings change.
- Validation artifacts are produced after gate scripts pass.
- Optimization artifacts are produced by Meta Agent (Phase 4+ skill updates).
