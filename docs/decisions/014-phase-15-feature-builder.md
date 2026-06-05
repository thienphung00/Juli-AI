# ADR 014: Phase 1.5 Feature Builder Module

## Status
Accepted

## Context

Issue #137 adds shared feature engineering between backtest dataset assembly (#136)
and the three model trainers (#138–#140). The feature builder must:

- Read versioned parquet + manifest from `ml/dataset`
- Emit per-model feature matrices with column names matching
  `docs/data-models/feature-store-schema.md`
- Enforce ADR-011 buyer-behavior scope on the anomaly path (no affiliate/creator columns)
- Remain runner-agnostic (plain Python functions, no scheduler coupling)

`docs/architecture/map.md` gains a new tier-2 module row for `src/modules/ml/features`.

## Decision

- **We will:** Add `src/modules/ml/features` with three public entrypoints:
  `build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`, returning
  a `FeatureMatrix` dataclass (`grain`, `feature_columns`, `frame`, `metadata`).
- **We will:** Extend the dataset manifest with `dataset_dir` so builders resolve parquet
  without caller-supplied paths.
- **We will:** Raise `FeatureValidationError` when anomaly inputs contain affiliate/creator
  columns or non-canonical entity columns.
- **We will not:** Train models, write Postgres feature tables, or call TikTok APIs in this module.

## Rationale

- Centralizes feature logic shared by three trainers — avoids duplicating Group A math and
  shop-level aggregates in #138–#140.
- `FeatureMatrix` gives trainers a stable contract (column tuple + pandas frame) for schema
  hash computation in #141.
- Manifest `dataset_dir` keeps the builder API to a single argument as specified in the PRD.
- Fail-fast forbidden-column guard encodes ADR-011 at the feature layer, not just in docs.

## Consequences

- `map.md` registers `src/modules/ml/features`; trainers import builders instead of
  reimplementing parquet reads.
- #138–#140 depend on this module; parallel trainer work can proceed once #137 merges.
- Phase 2 swaps parquet readers for Postgres queries without changing builder function signatures.
