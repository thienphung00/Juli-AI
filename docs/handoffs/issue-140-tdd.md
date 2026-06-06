# Handoff: tdd → review — Issue #140

## Issue

- **#140** — Ad performance analyzer — train + backtest

## Branch

- `feature/issue-140-ad-performance-trainer`

## Changes summary

- New: `src/modules/ml/ad_performance/*` (types, thresholds, rules, fixtures, inference, train, cli, MODULE.md)
- New: `tests/unit/test_ad_performance_trainer.py`
- New: `docs/decisions/017-phase-15-ad-performance-trainer.md`
- New: `docs/handoffs/issue-140-focus.md`
- Modified: `docs/architecture/map.md`

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_golden_scale_candidate_returns_scale_with_high_confidence` | Golden scale → scale with confidence > hold threshold |
| `test_golden_cut_candidate_returns_cut` | Golden cut → cut action |
| `test_sparse_history_campaign_returns_hold_low_confidence` | Sparse history → hold, low confidence, no raise |
| `test_train_writes_roas_mape_metrics_json` | Metrics JSON includes ROAS MAPE |
| `test_training_frame_includes_account_baseline_features` | Account baselines in training frame |
| `test_inference_output_schema_documented` | action, confidence, predicted_roas schema |
| `test_ad_performance_trainer_has_no_tiktok_api_calls` | No TikTok API calls |

## Test results

- All 7 new tests passing
- ML suite: 40/40 passing (seller_stage + anomaly + feature_builder + backtest + ad_performance)

## Acceptance criteria status

- [x] CLI train entrypoint writes metrics JSON with ROAS MAPE — `test_train_writes_roas_mape_metrics_json`
- [x] Model outputs scale | cut | hold plus confidence — inference schema + golden tests
- [x] Account-level baseline features included — `test_training_frame_includes_account_baseline_features`
- [x] Golden scale → scale with high confidence — `test_golden_scale_candidate_returns_scale_with_high_confidence`
- [x] Golden cut → cut — `test_golden_cut_candidate_returns_cut`
- [x] Sparse → hold low confidence — `test_sparse_history_campaign_returns_hold_low_confidence`
- [x] No TikTok API calls — `test_ad_performance_trainer_has_no_tiktok_api_calls`

## Notes for reviewer

- Golden fixture augmentation in training (same pattern as #139) for stable tests on small synthetic datasets
- Model serialization deferred to #141
