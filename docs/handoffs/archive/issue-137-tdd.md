# Handoff: tdd → review — Issue #137

## Issue

- **#137** — Feature builder for all three model suites

## Branch

- `feature/issue-137-feature-builder`

## Changes summary

- New: `src/modules/ml/features/` — types, schema, loader, anomaly/seller_stage/ad builders, MODULE.md
- Modified: `src/modules/ml/dataset/assembler.py` — adds `dataset_dir` to manifest
- Modified: `docs/architecture/map.md` — registers `ml/features` module
- New: `tests/unit/test_feature_builder.py` — 4 AC-mapped tests

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_anomaly_feature_columns_match_feature_store_schema` | Group A column names match `feature-store-schema.md` exactly |
| `test_anomaly_builder_rejects_affiliate_creator_columns` | Raises on forbidden affiliate/creator columns |
| `test_buyer_aggregate_counts_match_hand_computed_fixture` | Buyer aggregates + shop rates match hand-computed values |
| `test_all_three_builders_run_on_tiny_dataset_fixture` | All three builders succeed on #136 tiny fixture |

## Test results

- All 4 new tests passing
- All 9 existing `test_backtest_dataset.py` tests still passing (13 total ML tests)

## Acceptance criteria status

- [x] `build_seller_stage_features` with shop-level columns — `test_all_three_builders_run_on_tiny_dataset_fixture`
- [x] `build_anomaly_features` Group A only; rejects affiliate/creator — column + reject tests
- [x] `build_ad_features` with spend, ROAS, CPC, conversion, baselines — integration test
- [x] Buyer aggregates computable — hand-computed fixture test
- [x] Golden column names — schema match test
- [x] Integration all three builders — integration test

## Notes for reviewer

- Anomaly path raises (not strips) on forbidden columns per ADR-011 focus decision
- `return_rate_30d` uses delivered orders in 30d window; excludes rejected returns
- `seller_fault_cancel_rate_30d` is `null` when all `is_seller_fault` values are unknown (synthetic default)
