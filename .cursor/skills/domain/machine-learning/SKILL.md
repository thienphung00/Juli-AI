---
name: machine-learning-executor
description: >-
  Executor Agent domain skill for ML training, evaluation, datasets, and model
  artifacts. Use when implementing work under src/modules/ml/ or model promotion
  paths.
---

# Machine Learning Executor

Executor Agent domain skill for ML work. Implements with built-in TDD (Red →
Green → Refactor). Canonical requirements:
[`docs/architecture/agent-runtime.md`](../../../docs/architecture/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| Dataset assembly, feature pipelines | ML module `MODULE.md`, `ml_layer.md` |
| Training / eval scripts | `reliability.mdc`, `observability.mdc` for metric outputs |
| Model promotion / thresholds | `EXECUTION.md` slice gates, relevant ADRs |

## Required context

- Feature specs and `docs/data-models/` feature definitions
- Training/evaluation module docs under `src/modules/ml/`
- Model artifact thresholds and benchmark manifests
- Phase constraints (e.g. offline vs live inference per `system-design.md`)

## TDD expectations

- **Red:** failing unit test, golden-dataset test, metric-threshold test, or
  artifact-schema test
- **Green:** minimal implementation to pass deterministic checks
- **Refactor:** pipeline clarity without changing published metrics contracts

Prefer deterministic tests over flaky integration; use fixed seeds and small
golden fixtures.

## Review focus

Leakage prevention, reproducibility, metric validity, phase constraints, model
artifact promotion rules.

## Validation

`pytest` for ML modules, artifact smoke tests, coverage/acceptance mapping,
benchmark status when defined for the slice.

## Implementation artifact (required handoff)

Before Review Agent, write `artifacts/implementations/implementation-issue-<n>.json`.

```bash
python scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain machine-learning
```

Record golden-dataset tests, metric evidence, and promotion status in
`implementationSummary` and `redGreenRefactorEvidence`.

Schema: [`docs/schemas/agent-runtime/implementation-artifact.schema.json`](../../../docs/schemas/agent-runtime/implementation-artifact.schema.json)

## Must not

- Promote models past phase gates in `EXECUTION.md`
- Ship or validate — hand off to Review Agent
