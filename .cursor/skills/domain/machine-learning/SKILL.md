---
name: machine-learning-executor
description: >-
  Executor Agent domain skill for ML training, evaluation, datasets, and model
  artifacts. Use when implementing work under backend/src/juli_backend/ai/ or
  model promotion paths.
---

# Machine Learning Executor

ML pipelines, training, evaluation, artifact promotion. TDD + artifact handoff:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| Dataset / features | `ai/dataset/MODULE.md`, `ai/features/MODULE.md` |
| Train / eval / inference | suite `MODULE.md`, `reliability.mdc`, `observability.mdc` |
| Promotion / thresholds | `ai/artifacts/MODULE.md`, `EXECUTION.md`, relevant ADRs |
| Entity contracts | `docs/api/data-models/` |

## Owns / Does not own

**Owns:** backtest datasets, feature engineering, trainers/inference, golden fixtures,
metric thresholds, joblib publish/load/smoke, promotion status in `juli_backend/ai/`.

**Does not own:** **`backend`** — `/v1/*` routes, copy layer, Celery product wiring;
**`data-platform`** — Postgres schema, feature-store repos, ETL; **`integrations`** —
vendor fetch (ML reads parquet/manifests only).

Path: `backend/src/juli_backend/ai/` (not `src/modules/ml/`; no `backend/ai/` tree).
Load each subpackage `MODULE.md`, `docs/api/data-models/`, `EXECUTION.md` gates,
[`REFERENCE.md`](REFERENCE.md) on demand.

## Juli recipes

**Dataset** — `assemble_backtest_dataset` + manifest validation; fixed `seed`; contracts
in `dataset/schema.py`; no TikTok API or Postgres writes.

**Features** — `features/build_*` from manifest; columns in `features/schema.py`; honor
manifest train/eval boundaries — no re-split after materialization in eval tests.

**Training** — `train_*` with explicit `seed`; rules baseline + sklearn where used;
metrics JSON beside model output.

**Golden fixtures** — `*/fixtures.py` boundary profiles; `artifacts.run_smoke_test`;
deterministic pytest over live inference.

**Artifacts** — `publish_model` → `models/<suite>/<version>/model.joblib` +
`metadata.json`; load via `artifacts.load_model`; no train paths in eval fixtures;
`feature_schema_hash` must match metadata.

**Promotion** — `evaluate_promotion_status` + `artifacts/thresholds.py`; no promotion
past `EXECUTION.md` gates.

## Domain test surfaces

- `tests/unit/test_*trainer.py`, `test_model_artifacts.py`, suite fixture tests
- `tmp_path` fixtures; fixed seeds (e.g. `seed=141`); metric-threshold + smoke tests
- Mock at public trainer/loader boundaries only

Vertical RED→GREEN. Process details in agent-runtime doc above.

## Implementation artifact

```bash
python agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain machine-learning
```

Record golden tests, metrics, promotion in artifact JSON. Schema:
[`implementation-artifact.schema.json`](../../../agent-runtime/docs/schemas/implementation-artifact.schema.json).

## Validation & must not

`pytest` for touched suites; `ruff check .`; artifact smoke when publish/load changes.
No phase-gate bypass, `/v1` routes, vendor clients, schema migrations, or ship/validate.
