# src/modules/ml/ad_performance

## Purpose

Phase 1.5 ad performance analyzer for Growth Copilot scale/cut/hold recommendations.
Trains on backtest campaign/day features (#137) and ads parquet from #136.
Offline only; no TikTok API calls, no UI changes.

## Public Interface

- `train_ad_performance(manifest, output_dir, *, seed) -> TrainResult` — train ROAS regressor + action classifier; writes metrics JSON
- `predict_ad_action(model, features, *, hold_threshold) -> InferenceResult` — campaign feature vector → action + confidence
- `build_ad_training_frame(manifest) -> DataFrame` — campaign/day frame with derived action labels
- `GOLDEN_AD_FIXTURES` — golden campaign profiles for integration tests
- Threshold constants: `HOLD_CONFIDENCE_THRESHOLD`, `AD_ACTIONS`, `SPARSE_MAX_CONFIDENCE`
- CLI: `python -m src.modules.ml.ad_performance.cli` (`train-ad`)

## Inference output schema

```json
{
  "action": "scale | cut | hold",
  "confidence": 0.0,
  "predicted_roas": 0.0
}
```

- `action` — discrete recommendation for the campaign
- `confidence` — classifier probability for the predicted action in `[0, 1]`; sparse history capped low
- `predicted_roas` — regressor output for the campaign feature vector

## Dependencies

- `src/modules/ml/features` — `build_ad_features`, `AD_FEATURE_COLUMNS` (includes account baselines)
- `ads.parquet` — campaign/day spend, ROAS, CPC, conversions, impressions, clicks
- `scikit-learn` — `RandomForestRegressor`, `RandomForestClassifier`

## Key Behaviors

- Training frame: `build_ad_features` on campaign×day grain with account-level baselines
- Action labels derived from ROAS vs `account_avg_roas_30d` rules (scale/cut/hold)
- Held-out eval split by ad `date` vs manifest `split_boundaries.train_end`
- ROAS MAPE reported on held-out window in `metrics.json`
- Sparse ad history (low impressions/clicks/conversions) → `hold` with low confidence, no crash

## Out of Scope

- Model serialization to `models/` (#141)
- Seller stage and anomaly trainers (#138, #139)
- Production inference / TikTok API
