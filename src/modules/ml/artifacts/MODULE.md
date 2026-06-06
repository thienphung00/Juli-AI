# Model Artifacts (`src/modules/ml/artifacts`)

Serialize trained Phase 1.5 model suites to versioned on-disk joblib artifacts with lineage metadata and CI smoke tests.

## Public interface

| Function | Description |
|----------|-------------|
| `publish_model(suite, *, model, metrics, version, ...)` | Write `model.joblib`, `metadata.json`, copy `metrics.json` |
| `load_model(suite, version, *, models_root="models")` | Load model + metadata |
| `load_metadata(suite, version, *, models_root="models")` | Load metadata only |
| `run_smoke_test(suite, version, *, models_root="models")` | Load + golden fixture inference |
| `run_all_smoke_tests(version, *, models_root="models")` | Smoke all three suites |
| `evaluate_promotion_status(suite, metrics)` | `promoted` \| `experimental` |
| `feature_schema_hash(suite)` | Stable hash of feature column names |

## Directory layout

```
models/
  seller_stage/{version}/model.joblib + metadata.json + metrics.json
  anomaly/{version}/model.joblib + metadata.json + metrics.json
  ad_performance/{version}/model.joblib + metadata.json + metrics.json
```

## metadata.json schema

| Field | Type | Description |
|-------|------|-------------|
| `suite` | string | `seller_stage` \| `anomaly` \| `ad_performance` |
| `version` | string | Caller-supplied version label |
| `train_date` | string | ISO-8601 UTC timestamp |
| `row_count` | int | `train_rows + eval_rows` from metrics |
| `feature_schema_hash` | string | SHA-256 prefix of feature column tuple |
| `metrics` | object | Training metrics snapshot |
| `promotion_status` | string | `promoted` \| `experimental` |

## Promotion gate

Provisional thresholds in `thresholds.py` (finalized in #142):

- **seller_stage:** precision ≥ 0.5 AND recall_macro ≥ 0.5
- **anomaly:** precision ≥ 0.5 AND recall ≥ 0.5 per `item_swap` and `empty_return`
- **ad_performance:** roas_mape ≤ 50.0

## Dependencies

- **Upstream:** `ml/seller_stage`, `ml/anomaly`, `ml/ad_performance` trainers (TrainResult)
- **Downstream:** Phase 2 inference job loads artifacts via `load_model`

## Out of scope

- Postgres artifact persistence
- Threshold sign-off in `system-design.md` (#142)
- Production inference scheduling
