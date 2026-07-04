# backend/ai/seller_stage

## Purpose

Phase 1.5 seller lifecycle classifier: rules baseline (ported from Phase 1 TypeScript
router), sklearn training on backtest features, and rules-vs-ML comparison. Offline only —
no TikTok API calls, no UI changes.

## Public Interface

- `classify_seller_stage(profile) -> SellerStage` — deterministic rules baseline (`new | leakage | growth`)
- `predict_seller_stage(model, features) -> InferenceResult` — ML inference with confidence in `[0, 1]`
- `train_seller_stage(manifest, output_dir, *, seed) -> TrainResult` — train on #136 backtest split; writes metrics JSON
- `compare_to_rules_baseline(model, profiles) -> ComparisonReport` — agreement rate + disagreements
- `STAGE_BOUNDARY_FIXTURES` — golden threshold boundary profiles
- Threshold constants: `RETURN_RATE_LEAKAGE_MIN`, `ORDER_COUNT_NEW_MAX`, `SHOP_AGE_NEW_MAX_DAYS`, `ORDER_COUNT_GROWTH_MIN`, `AD_SPEND_GROWTH_MIN_VND`
- CLI: `python -m src.modules.ml.seller_stage.cli` (`train-seller-stage`)

## Dependencies

- `backend/ai/features` — `build_seller_stage_features`, `SELLER_STAGE_FEATURE_COLUMNS`
- `scikit-learn` — `RandomForestClassifier`
- `web/src/lib/seller-stage-router/thresholds.ts` — authoritative Phase 1 constant source (mirrored in Python)

## Key Behaviors

- Training labels derived from rules baseline applied to shop feature rows
- Class imbalance handled via `class_weight="balanced"` (documented in metrics + training log)
- Fixed random seed for reproducibility; structured JSON training logs (no PII)
- Train/eval split uses manifest `split_boundaries.train_end` when possible

## Out of Scope

- Model serialization to `models/` (#141)
- Anomaly and ad trainers (#139, #140)
- Production inference / TikTok API
