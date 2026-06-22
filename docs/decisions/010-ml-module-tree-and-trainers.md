# ADR 010: ML module tree, features, trainers, and artifacts

## Status
Accepted

## Context

Phase 2 MVP requires offline ML training (seller stage router, buyer-behavior anomaly,
ad performance) and daily batch inference. Legacy `intelligence/scoring/` targets
creator/livestream signals — seller-money ML must not extend it.

## Decision

### Module tree

- **We will:** Maintain ML code under `src/modules/ml/` with MODULE.md per sub-module:
  `dataset`, `features`, `seller_stage`, `anomaly`, `ad_performance`, `artifacts`.
- **We will:** Pin `pandas`, `pyarrow`, `scikit-learn`, and `xgboost` in `requirements.txt`.
- **We will:** Expose plain Python functions and CLI entrypoints — no Celery or scheduler
  coupling — so Phase 2 MVP swaps the runner without rewriting ML logic.
- **We will not:** Extend legacy `intelligence/scoring` for seller-money models.

### Feature builder

- **We will:** Provide `build_seller_stage_features`, `build_anomaly_features`,
  `build_ad_features` returning a `FeatureMatrix` dataclass.
- **We will:** Enforce [ADR-008](008-buyer-behavior-anomaly-scope.md) at the feature layer
  (no affiliate/creator columns in anomaly path).

### Trainers

- **Router classifier:** `NEW_SHOP` vs `MID_LARGE_SHOP` shop profile.
- **Return-fraud detector:** `item_swap` / `empty_return` classification.
- **Ads regressor:** ROAS prediction + scale/cut/hold action.

### Artifacts

- **We will:** Serialize to `models/{suite}/{version}/` with lineage metadata
  (`train_date`, row count, feature schema hash, metrics, promotion status).
- **We will:** Gate promotion on backtest thresholds documented in `feature-store-schema.md`.
- **We will not:** Persist artifacts to Postgres in offline training mode.

## Consequences

- Phase 2 MVP batch inference (08:00 UTC) loads from the same artifact layout.
- `docs/architecture/map.md` registers all `src/modules/ml/*` modules.
