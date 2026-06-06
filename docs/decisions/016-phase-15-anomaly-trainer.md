# ADR 016: Phase 1.5 Anomaly Trainer Module

## Status
Accepted

## Context

Issue #139 adds the buyer-behavior anomaly detector trainer between the shared
feature builder (#137) and model artifact serialization (#141). The trainer must:

- Train exclusively on Order/OrderItem/Return-derived features and `labels.parquet`
  buyer-behavior ground truth (`item_swap`, `empty_return`, `other`)
- Report per-class precision/recall on held-out labeled returns
- Expose stable inference (`anomaly_class`, `confidence`, `feature_summary`) for Phase 2 UI evidence
- Exclude affiliate and creator signals per [ADR-011](011-buyer-behavior-anomaly-scope.md)
- Remain offline — no TikTok API calls, no UI changes, no Postgres writes

`docs/architecture/map.md` gains a new tier-2 module row for `src/modules/ml/anomaly`.

## Decision

- **We will:** Add `src/modules/ml/anomaly` with `train_anomaly`, `predict_anomaly`, and
  `build_anomaly_training_frame` (return-level join to buyer×shop features).
- **We will:** Use `RandomForestClassifier(class_weight="balanced")` with fixed random seed
  for reproducible training on `labels.parquet` return types.
- **We will:** Write `metrics.json` (per-class precision/recall) and `training_log.json`
  via CLI `train-anomaly`.
- **We will not:** Serialize joblib artifacts (#141), train seller stage or ad models (#138, #140),
  or include affiliate/creator features in training or inference.

## Rationale

- Return-level labels from `labels.parquet` are authoritative ground truth; buyer×shop
  features from #137 provide the feature vector without affiliate joins.
- Disjoint module boundary allows parallel work on #138 and #140 per `issue-workflow.mdc`.
- `feature_summary` in inference output supports Phase 2 Revenue Leakage UI evidence panels.

## Consequences

- `map.md` registers `src/modules/ml/anomaly`; #141 consumes trained models for serialization.
- Golden fixtures document high-signal buyer profiles for integration tests.
- Phase 2 inference loads serialized artifacts from #141, not this training module directly.
