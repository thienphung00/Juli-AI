# Handoff: tdd → review — Issue #139

## Issue

- **#139** — Anomaly detector — buyer behavior only

## Branch

- `feature/issue-139-anomaly-trainer`

## Changes Summary

### New files

- `src/modules/ml/anomaly/` — types, thresholds, fixtures, inference, train, cli, MODULE.md
- `tests/unit/test_anomaly_trainer.py` — 7 AC-mapped integration tests
- `docs/decisions/016-phase-15-anomaly-trainer.md`

### Modified files

- `docs/architecture/map.md` — register `src/modules/ml/anomaly`

## Tests Written

- `test_golden_item_swap_scores_as_anomaly` — golden item_swap → anomaly class item_swap
- `test_golden_empty_return_scores_as_anomaly` — golden empty_return → anomaly class empty_return
- `test_golden_other_scores_non_anomaly` — golden other → non-anomaly
- `test_training_frame_has_no_affiliate_creator_columns` — no affiliate/creator columns in training frame
- `test_train_writes_per_class_metrics_json` — per-class precision/recall in metrics JSON
- `test_inference_output_schema_documented` — `{ anomaly_class, confidence, feature_summary, is_anomaly }`
- `test_anomaly_trainer_has_no_tiktok_api_calls` — offline-only trainer

## Test Results

- All 7 new tests passing
- 33/33 ML unit tests passing (anomaly + seller_stage + features + dataset)

## Acceptance Criteria Status

- [x] Training uses Order/OrderItem/Return features + labels.parquet — `test_train_writes_per_class_metrics_json`
- [x] Per-class metrics for item_swap and empty_return — `test_train_writes_per_class_metrics_json`
- [x] Golden item_swap scores as anomaly — `test_golden_item_swap_scores_as_anomaly`
- [x] Golden empty_return scores as anomaly — `test_golden_empty_return_scores_as_anomaly`
- [x] Golden other non-anomaly — `test_golden_other_scores_non_anomaly`
- [x] No affiliate/creator columns — `test_training_frame_has_no_affiliate_creator_columns`
- [x] Inference schema documented — `test_inference_output_schema_documented` + MODULE.md
- [x] ADR-011 scope — training frame + MODULE.md out-of-scope notes
- [x] No TikTok API calls — `test_anomaly_trainer_has_no_tiktok_api_calls`

## Notes for Reviewer

- Golden profile augmentation in `train_anomaly` handles sparse `empty_return` labels in synthetic backtest data (typically 1 row per small dataset).
- Stratified train/eval split by `return_type` keeps all classes in training when present.
