# ADR 017: Phase 1.5 Ad Performance Trainer Module

## Status
Accepted

## Context

Issue #140 adds the ad performance analyzer trainer between the shared
feature builder (#137) and model artifact serialization (#141). The trainer must:

- Train on campaign/day ad features from `build_ad_features` and `ads.parquet`
- Predict ROAS and rank campaigns as `scale`, `cut`, or `hold` with confidence
- Report ROAS MAPE on a held-out date window
- Handle sparse ad history with low-confidence `hold` — no crash on minimal data
- Remain offline — no TikTok API calls, no UI changes, no Postgres writes

`docs/architecture/map.md` gains a new tier-2 module row for `src/modules/ml/ad_performance`.

## Decision

- **We will:** Add `src/modules/ml/ad_performance` with `train_ad_performance`,
  `predict_ad_action`, and `build_ad_training_frame`.
- **We will:** Use `RandomForestRegressor` for ROAS prediction and
  `RandomForestClassifier(class_weight="balanced")` for action classification.
- **We will:** Derive training labels from ROAS vs `account_avg_roas_30d` rules.
- **We will:** Write `metrics.json` (ROAS MAPE) and `training_log.json` via CLI `train-ad`.
- **We will not:** Serialize joblib artifacts (#141), train seller stage or anomaly models (#138, #139),
  or call TikTok APIs.

## Rationale

- Campaign/day features from #137 already include account baselines required by the PRD.
- Rules-derived action labels provide interpretable scale/cut/hold ground truth on backtest data.
- Disjoint module boundary allows parallel work on #138 and #139 per `issue-workflow.mdc`.
- Sparse-history guard prevents false scale/cut recommendations for new sellers with minimal ad data.

## Consequences

- `map.md` registers `src/modules/ml/ad_performance`; #141 consumes trained models for serialization.
- Golden fixtures document high-signal campaign profiles for integration tests.
- Phase 2 Growth Copilot loads serialized artifacts from #141, not this training module directly.
