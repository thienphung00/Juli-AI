# Handoff: focus → tdd — Issue #138

## Issue

- **#138** — Seller stage classifier — train + rules baseline
- **EXECUTION slice:** P1.5-2
- **Parent:** #135 · **Blocked by:** #137 (complete)

## Acceptance criteria

- CLI train entrypoint runs on #136 backtest split; writes metrics JSON (precision, recall macro, confusion matrix)
- Class imbalance strategy documented (class weights, resampling, or stratified split)
- Rules baseline module mirrors `ORDER_COUNT_NEW_MAX`, `RETURN_RATE_LEAKAGE_MIN`, `SHOP_AGE_NEW_MAX_DAYS`, `ORDER_COUNT_GROWTH_MIN`, `AD_SPEND_GROWTH_MIN_VND`
- Comparison report: agreement rate + disagreement cases exportable as JSON
- Integration test: golden profiles (new, leakage, growth + threshold edge cases) → expected stage from rules baseline
- Integration test: ML inference on same golden profiles returns valid class + confidence in `[0, 1]`
- Integration test: `compareToRulesBaseline` report includes agreement rate field
- No TikTok API calls; no UI changes

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-2), `docs/architecture/system-design.md` § ML models, `docs/architecture/map.md` |
| Feature builder | `src/modules/ml/features/seller_stage.py`, `schema.py`, `MODULE.md` |
| Dataset contract | `src/modules/ml/dataset/assembler.py`, `MODULE.md` |
| Rules baseline (TS) | `web/src/lib/seller-stage-router/thresholds.ts`, `classify.ts`, `boundary-fixtures.ts` |
| Prior art | `web/src/__tests__/test_seller_stage_router.test.ts`, `docs/handoffs/issue-137-ship.md` |
| Decisions | `docs/adr/013-phase-15-ml-module-tree.md` |

## Standards applied

- Reliability — fixed random seed; deterministic rules baseline; fail-fast on missing features
- Security — no PII in training logs; structured JSON only
- Observability — structured JSON training logs (metrics, class imbalance strategy)
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`

## Plugin skills & MCP

- None required (offline sklearn training on parquet features)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** thresholds → rules → fixtures → types → inference → train → compare → cli → tests

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/seller_stage/thresholds.py` | Mirror Phase 1 TS constants |
| `src/modules/ml/seller_stage/rules.py` | `classify_seller_stage(profile) → str` |
| `src/modules/ml/seller_stage/fixtures.py` | Golden boundary profiles (ported from TS) |
| `src/modules/ml/seller_stage/types.py` | `TrainResult`, `InferenceResult`, `ComparisonReport` |
| `src/modules/ml/seller_stage/inference.py` | `predict_seller_stage(model, features)` |
| `src/modules/ml/seller_stage/train.py` | `train_seller_stage(manifest, output_dir)` |
| `src/modules/ml/seller_stage/compare.py` | `compare_to_rules_baseline(model, profiles)` |
| `src/modules/ml/seller_stage/cli.py` | `train-seller-stage` CLI |
| `src/modules/ml/seller_stage/MODULE.md` | Public interface |
| `tests/unit/test_seller_stage_trainer.py` | AC-mapped integration tests |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Register `src/modules/ml/seller_stage` |

### Key patterns

- Rules baseline is authoritative for golden fixtures; training labels derived via rules on feature rows
- `RandomForestClassifier(class_weight="balanced", random_state=seed)` for class imbalance
- Train/eval split: shops assigned by earliest order date vs manifest `split_boundaries.train_end`; fallback stratified holdout when single snapshot date
- Inference uses `predict_proba` max as confidence in `[0, 1]`
- Metrics JSON: precision, recall_macro, confusion_matrix, class_imbalance_strategy
- Comparison report JSON: `agreement_rate`, `disagreements[]`

### Tests (TDD)

1. RED: `test_rules_baseline_golden_boundary_fixtures`
2. RED: `test_threshold_constants_match_phase1`
3. RED: `test_ml_inference_on_golden_profiles_valid_class_and_confidence`
4. RED: `test_compare_to_rules_baseline_includes_agreement_rate`
5. RED: `test_train_writes_metrics_json`
6. GREEN: implement module incrementally

Run: `pytest tests/unit/test_seller_stage_trainer.py -v`

## DO NOT touch

- `ml/anomaly`, `ml/ad_performance` — #139, #140
- `web/` UI — no changes per AC
- Legacy `catalog/domain/intelligence/scoring`
- TikTok API / Postgres paths
