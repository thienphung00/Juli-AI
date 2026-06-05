# Handoff: focus → tdd — Issue #137

## Issue

- **#137** — Feature builder for all three model suites
- **EXECUTION slice:** shared infrastructure between P1.5-1 and P1.5-2/3/4
- **Parent:** #135 · **Blocked by:** #136 (complete)

## Acceptance criteria

- `build_seller_stage_features(manifest) → FeatureMatrix` with shop-level columns (shop age, order count, return rate, ad spend, GMV)
- `build_anomaly_features(manifest) → FeatureMatrix` using Group A features only; **rejects** affiliate/creator columns if present in input
- `build_ad_features(manifest) → FeatureMatrix` with spend, ROAS, CPC, conversion, and account-baseline columns
- Buyer aggregates computable: `buyer_return_count_30d`, `buyer_item_swap_count_30d`, `buyer_empty_return_count_30d`, `buyer_repeat_anomaly_flag`, `return_rate_30d`
- Unit test: golden mini-parquet → anomaly feature matrix column names match `feature-store-schema.md` exactly
- Unit test: anomaly builder raises if non Order/OrderItem/Return columns are passed
- Unit test: buyer aggregate counts match hand-computed expected values on fixture
- Integration test: all three builders run on #136 tiny fixture without error

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md`, `docs/system-design.md`, `docs/architecture/map.md`, `docs/data-models/feature-store-schema.md` |
| Dataset contract | `src/modules/ml/dataset/schema.py`, `src/modules/ml/dataset/MODULE.md` |
| Decisions | `docs/decisions/011-buyer-behavior-anomaly-scope.md`, `docs/decisions/013-phase-15-ml-module-tree.md` |
| Baseline constants | `web/src/lib/seller-stage-router/thresholds.ts` (seller-stage column names) |
| Domain patterns | `.cursor/skills/domain/python-patterns.md`, `.cursor/skills/domain/python-testing.md` |

## Standards applied

- Reliability — fail-fast on forbidden affiliate/creator columns; deterministic 30d window math
- Security — no PII; masked buyer_id only from upstream parquet
- Performance — vectorized pandas groupby; bounded test fixtures
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`

## Plugin skills & MCP

- None required (offline parquet reads only)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** types/schema → loader → anomaly → seller_stage → ad → tests

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/features/types.py` | `FeatureMatrix` dataclass |
| `src/modules/ml/features/schema.py` | Authoritative column name constants |
| `src/modules/ml/features/exceptions.py` | `FeatureValidationError` |
| `src/modules/ml/features/loader.py` | Parquet loader + forbidden-column guard |
| `src/modules/ml/features/anomaly.py` | `build_anomaly_features` |
| `src/modules/ml/features/seller_stage.py` | `build_seller_stage_features` |
| `src/modules/ml/features/ad.py` | `build_ad_features` |
| `src/modules/ml/features/MODULE.md` | Public interface |
| `tests/unit/test_feature_builder.py` | AC-mapped unit + integration tests |

### Modified files

| File | Change |
|------|--------|
| `src/modules/ml/dataset/assembler.py` | Add `dataset_dir` to manifest for downstream builders |
| `docs/architecture/map.md` | Register `src/modules/ml/features` |

### Key patterns

- `FeatureMatrix` exposes `feature_columns` tuple + pandas `frame` + `grain` metadata
- Reference date = manifest `date_range.end` (fallback: max timestamp in orders)
- Group A anomaly columns match inference signature in `feature-store-schema.md`
- Seller-stage shop columns align with Phase 1 profile fields (`shop_age_days`, `order_count_30d`, etc.)
- Ad features at campaign/day grain with account-level baseline joins

### Tests (TDD)

1. RED: `test_anomaly_feature_columns_match_feature_store_schema`
2. RED: `test_anomaly_builder_rejects_affiliate_creator_columns`
3. RED: `test_buyer_aggregate_counts_match_hand_computed_fixture`
4. RED: `test_all_three_builders_run_on_tiny_dataset_fixture`
5. GREEN: implement builders incrementally

Run: `pytest tests/unit/test_feature_builder.py -v`

## DO NOT touch

- Model trainers (`ml/seller_stage`, `ml/anomaly`, `ml/ad_performance`) — #138–#140
- Legacy `catalog/domain/intelligence/scoring`
- TikTok API / Postgres paths
