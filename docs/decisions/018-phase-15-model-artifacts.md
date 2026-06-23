# ADR 018: Phase 1.5 Model Artifact Publisher

## Status
Accepted

## Context

Issue #141 adds serialization for the three Phase 1.5 trainers (#138–#140). Artifacts must:

- Follow the `models/{suite}/{version}/` layout in `system-design.md`
- Include lineage metadata (`train_date`, row count, feature schema hash, metrics, promotion status)
- Gate promotion on provisional backtest thresholds (finalized in #142)
- Support CI smoke tests (load + golden fixture inference)
- Remain offline — no Postgres writes

`docs/architecture/map.md` gains a new tier-2 module row for `src/modules/ml/artifacts`.

## Decision

- **We will:** Add `src/modules/ml/artifacts` with `publish_model`, `load_model`, and smoke test helpers.
- **We will:** Copy training `metrics.json` into the artifact directory during publish for exit-gate review without re-training.
- **We will:** Compute `feature_schema_hash` from authoritative column tuples in `ml/features/schema.py`.
- **We will not:** Persist artifacts to Postgres, modify trainer modules, or finalize `system-design.md` thresholds (#142).

## Rationale

- Centralizes serialization logic shared by three trainers — avoids duplicating joblib/metadata code in each CLI.
- Promotion gate encodes provisional thresholds as code constants updatable when Product signs off in #142.
- Smoke tests validate the full load → infer path using existing golden fixtures from trainer modules.
- Disk-only artifacts match Phase 1.5 offline scope; Phase 2 inference loads from the same layout.

## Consequences

- `map.md` registers `src/modules/ml/artifacts`; Phase 2 inference imports `load_model`.
- Trainer CLIs remain focused on training; callers publish via `publish_model` after training.
- `models/` directory is gitignored; CI smoke tests train + publish in pytest temp dirs.
