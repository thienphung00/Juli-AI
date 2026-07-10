# Handoff: focus → tdd — Issue #139

## Issue

- **#139** — Anomaly detector — buyer behavior only
- **EXECUTION slice:** P1.5-3
- **Parent:** #135 · **Blocked by:** #137 (complete)

## Acceptance criteria

- Training uses only Order/OrderItem/Return-derived features and buyer-behavior labels from `labels.parquet`
- Per-class metrics reported separately for `item_swap` and `empty_return` on held-out split
- Integration test: golden `item_swap` row scores as anomaly with class `item_swap`
- Integration test: golden `empty_return` row scores as anomaly with class `empty_return`
- Integration test: golden `other` (legitimate return) scores below anomaly threshold or as non-anomaly
- Integration test: feature matrix for anomaly training contains no affiliate/creator column names
- Inference output schema documented: `{ anomaly_class, confidence, feature_summary }`
- No affiliate fraud, commission dispute, or creator-attributed refund signals (ADR-011)
- No TikTok API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-3), `docs/architecture/system-design.md` § ML models + Return schema, `docs/architecture/map.md` |
| Feature builder | `src/modules/ml/features/anomaly.py`, `schema.py`, `MODULE.md` |
| Dataset contract | `src/modules/ml/dataset/assembler.py`, `labels.parquet` schema |
| Prior art | `src/modules/ml/seller_stage/*`, `tests/unit/test_seller_stage_trainer.py`, `docs/handoffs/issue-137-ship.md` |
| Decisions | `docs/adr/011-buyer-behavior-anomaly-scope.md`, `013-phase-15-ml-module-tree.md` |

## Standards applied

- Reliability — fixed random seed; fail-fast on missing labels/features; deterministic splits
- Security — no PII in training logs; masked buyer_id only via dataset layer
- Observability — structured JSON training logs (per-class metrics, class imbalance strategy)
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`

## Plugin skills & MCP

- None required (offline sklearn on parquet)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** types → thresholds → fixtures → inference → train → cli → tests → map.md → ADR

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/anomaly/types.py` | `TrainResult`, `InferenceResult` (`anomaly_class`, `confidence`, `feature_summary`) |
| `src/modules/ml/anomaly/thresholds.py` | `ANOMALY_CONFIDENCE_THRESHOLD`, `ANOMALY_CLASSES` |
| `src/modules/ml/anomaly/fixtures.py` | Golden buyer feature profiles for item_swap / empty_return / other |
| `src/modules/ml/anomaly/inference.py` | `predict_anomaly(model, features)` |
| `src/modules/ml/anomaly/train.py` | `train_anomaly(manifest, output_dir)` — labels.parquet join |
| `src/modules/ml/anomaly/cli.py` | `train-anomaly` CLI |
| `src/modules/ml/anomaly/MODULE.md` | Public interface + inference schema |
| `tests/unit/test_anomaly_trainer.py` | AC-mapped integration tests |
| `docs/adr/016-phase-15-anomaly-trainer.md` | ADR for new module |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Register `src/modules/ml/anomaly` |

### Key patterns

- Training frame: `returns.parquet` ⋈ `labels.parquet` ⋈ `build_anomaly_features` on `(buyer_id, shop_id)`
- Labels: `return_type` ∈ `{item_swap, empty_return, other}` from `labels.parquet` only
- `RandomForestClassifier(class_weight="balanced", random_state=139)` for class imbalance
- Held-out split by return `created_at` vs manifest `split_boundaries.train_end`; stratified fallback
- Metrics JSON: per-class precision/recall for `item_swap` and `empty_return`
- Inference: anomaly when predicted class ∈ anomaly classes and confidence ≥ threshold
- `feature_summary`: non-zero Group A feature values for Phase 2 UI evidence

### Tests (TDD)

1. RED: `test_golden_item_swap_scores_as_anomaly`
2. RED: `test_golden_empty_return_scores_as_anomaly`
3. RED: `test_golden_other_scores_non_anomaly`
4. RED: `test_training_frame_has_no_affiliate_creator_columns`
5. RED: `test_train_writes_per_class_metrics_json`
6. GREEN: implement module incrementally

Run: `pytest tests/unit/test_anomaly_trainer.py -v`

## DO NOT touch

- `ml/seller_stage`, `ml/ad_performance` — parallel issues
- `web/` UI — no changes per AC
- Model serialization (#141)
- TikTok API / Postgres paths
