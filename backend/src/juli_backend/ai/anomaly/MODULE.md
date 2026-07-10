# backend/ai/anomaly

## Purpose

Phase 1.5 buyer-behavior anomaly detector for return fraud patterns (`item_swap`,
`empty_return`). Trains on backtest features (#137) and buyer-behavior labels from
`labels.parquet` only — no affiliate or creator signals ([ADR-011](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md)).
Offline only; no TikTok API calls, no UI changes.

## Public Interface

- `train_anomaly(manifest, output_dir, *, seed) -> TrainResult` — train on labeled returns; writes per-class metrics JSON
- `predict_anomaly(model, features, *, threshold) -> InferenceResult` — buyer feature vector → anomaly prediction
- `build_anomaly_training_frame(manifest) -> (frame, features, labels)` — return-level join for tests
- `GOLDEN_ANOMALY_FIXTURES` — golden buyer profiles for integration tests
- Threshold constants: `ANOMALY_CONFIDENCE_THRESHOLD`, `ANOMALY_CLASSES`
- CLI: `python -m src.modules.ml.anomaly.cli` (`train-anomaly`)

## Inference output schema

```json
{
  "anomaly_class": "item_swap | empty_return | null",
  "confidence": 0.0,
  "feature_summary": { "buyer_item_swap_count_30d": 3.0 },
  "is_anomaly": true
}
```

- `anomaly_class` — predicted buyer-behavior anomaly class, or `null` when below threshold / legitimate return
- `confidence` — max class probability from the classifier in `[0, 1]`
- `feature_summary` — non-zero Group A feature values contributing to the score (Phase 2 UI evidence)
- `is_anomaly` — `true` when predicted class is `item_swap` or `empty_return` and anomaly probability ≥ threshold

## Dependencies

- `backend/ai/features` — `build_anomaly_features`, `ANOMALY_FEATURE_COLUMNS`
- `labels.parquet` — `return_id`, `ground_truth_anomaly`, `return_type`
- `scikit-learn` — `RandomForestClassifier`

## Key Behaviors

- Training frame: `returns.parquet` ⋈ `labels.parquet` ⋈ buyer×shop feature matrix
- Class imbalance handled via `class_weight="balanced"` (documented in metrics + training log)
- Held-out eval split by return `created_at` vs manifest `split_boundaries.train_end`
- Per-class precision/recall reported separately for `item_swap` and `empty_return`

## Out of Scope

- Model serialization to `models/` (#141)
- Seller stage and ad trainers (#138, #140)
- Affiliate fraud, commission disputes, creator-attributed refunds (ADR-011)
- Production inference / TikTok API
