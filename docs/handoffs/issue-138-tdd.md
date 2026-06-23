# Handoff: tdd → review — Issue #138

## Issue

- **#138** — Seller stage classifier — train + rules baseline

## Branch

- `feature/issue-138-seller-stage-classifier`

## Changes summary

- New: `src/modules/ml/seller_stage/` — thresholds, rules, fixtures, train, inference, compare, cli, MODULE.md
- Modified: `docs/architecture/map.md` — registers `ml/seller_stage` module
- New: `tests/unit/test_seller_stage_trainer.py` — 10 AC-mapped tests (6 parametrized boundary cases)

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_threshold_constants_match_phase1` | Rules constants mirror TS thresholds |
| `test_rules_baseline_golden_boundary_fixtures` | Golden profiles → expected rules stage |
| `test_ml_inference_on_golden_profiles_valid_class_and_confidence` | ML returns valid stage + confidence ∈ [0,1] |
| `test_compare_to_rules_baseline_includes_agreement_rate` | Comparison report has agreement_rate |
| `test_train_writes_metrics_json` | Metrics JSON with precision, recall_macro, confusion_matrix |

## Test results

- All 10 new tests passing
- All 13 existing ML tests still passing (23 total)

## Acceptance criteria status

- [x] CLI train entrypoint writes metrics JSON — `train_seller_stage` + cli module
- [x] Class imbalance strategy documented — `CLASS_IMBALANCE_STRATEGY` in metrics + training_log
- [x] Rules baseline mirrors Phase 1 thresholds — `thresholds.py` + constant test
- [x] Comparison report with agreement rate — `compare_to_rules_baseline`
- [x] Golden profiles rules baseline — parametrized boundary fixture tests
- [x] ML inference on golden profiles — confidence bounds test
- [x] compareToRulesBaseline agreement rate — dedicated test
- [x] No TikTok API / UI changes — offline sklearn only

## Notes for reviewer

- Training labels derived from rules baseline on feature rows (no seller-stage labels in parquet)
- Train/eval split uses manifest `split_boundaries.train_end` with stratified fallback for tiny datasets
- Model serialization deferred to #141
