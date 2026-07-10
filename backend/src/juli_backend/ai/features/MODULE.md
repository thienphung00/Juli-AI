# backend/ai/features

## Purpose

Phase 1.5 shared feature engineering: transform backtest parquet (from `ml/dataset`)
into per-model feature matrices with column names matching
[`docs/data-models/feature-store-schema.md`](../../../docs/data-models/feature-store-schema.md).
Runner-agnostic plain Python — no scheduler coupling ([ADR-010](../../../docs/decisions/010-ml-module-tree-and-trainers.md)).

## Public Interface

- `build_seller_stage_features(manifest) -> FeatureMatrix` — shop-level columns:
  `shop_age_days`, `order_count_30d`, `return_rate_30d`, `ad_spend_30d_vnd`, `gmv_30d_vnd`
- `build_anomaly_features(manifest) -> FeatureMatrix` — Group A buyer-behavior features only;
  rejects affiliate/creator columns ([ADR-011](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md))
- `build_ad_features(manifest) -> FeatureMatrix` — campaign/day grain with spend, ROAS, CPC,
  conversions, and account-level baselines
- `FeatureMatrix` — dataclass with `grain`, `feature_columns`, `frame`, `metadata`
- `FeatureValidationError` — fail-fast schema / forbidden-column errors
- Column constants: `ANOMALY_FEATURE_COLUMNS`, `SELLER_STAGE_FEATURE_COLUMNS`, `AD_FEATURE_COLUMNS`

## Dependencies

- `backend/ai/dataset` — manifest + parquet contract (`dataset_dir`, entity columns)
- `pandas`, `pyarrow` — parquet I/O and vectorized feature math
- `docs/data-models/feature-store-schema.md` — authoritative feature names

## Key Behaviors

- Manifest must include `dataset_dir` pointing at assembled parquet root
- Reference date = manifest `date_range.end` (30-day windows computed backward)
- Anomaly path reads Order, OrderItem, Return only; raises on affiliate/creator columns
- Ad baselines: `account_avg_roas_30d`, `account_spend_velocity_30d` joined per shop

## Out of Scope

- Model training (#138–#140)
- Postgres feature tables (Phase 2)
- TikTok API ingestion
