# Handoff: tdd → review — Issue #136

## Issue

- **#136** — Backtest dataset assembly (parquet + synthetic)

## Branch

- `feat/issue-136-backtest-dataset` → merged via PR #144

## Changes summary

- **New:** `src/modules/ml/dataset/` (assembler, synthetic, validation, schema, cli, exceptions, MODULE.md)
- **New:** `tests/unit/test_backtest_dataset.py`
- **New:** `docs/decisions/013-phase-15-ml-module-tree.md`
- **New:** `artifacts/reviews/review-issue-136.json`, `artifacts/validation/validation-issue-136.json`
- **Modified:** `requirements.txt`, `docs/architecture/map.md`, `docs/decisions/README.md`
- **Migrations:** none

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_ml_module_public_interface_and_pinned_dependencies` | MODULE.md + pinned ML deps |
| `test_assemble_tiny_fixture_with_fixed_seed_writes_manifest_and_parquet` | CLI assembler + manifest JSON |
| `test_parquet_columns_match_return_schema_contract` | All 5 parquet column contracts |
| `test_labels_parquet_contains_buyer_behavior_labels_only` | Buyer-behavior labels only |
| `test_synthetic_generator_produces_anomaly_labels_and_masked_buyer_ids` | item_swap/empty_return prevalence + masked buyer_id |
| `test_schema_validation_fails_fast_on_missing_columns` | Invalid enum fail-fast |
| `test_validate_raises_on_missing_return_type_with_actionable_message` | Corrupt parquet actionable error |
| `test_assembler_has_no_tiktok_api_calls` | No TikTok API |
| `test_assembler_has_no_postgres_writes` | No Postgres writes |

## Test results

- All 9 tests passing (`pytest tests/unit/test_backtest_dataset.py`)
- No pre-existing tests broken (220 total at merge time per PR #144)

## Acceptance criteria status

- [x] ML module directory + MODULE.md; dependencies pinned — `test_ml_module_public_interface_and_pinned_dependencies`
- [x] CLI writes manifest JSON — `test_assemble_tiny_fixture_with_fixed_seed_writes_manifest_and_parquet`
- [x] Parquet files match schema contract — `test_parquet_columns_match_return_schema_contract`
- [x] labels.parquet buyer-behavior only — `test_labels_parquet_contains_buyer_behavior_labels_only`
- [x] Synthetic generator + masked buyer_id — `test_synthetic_generator_produces_anomaly_labels_and_masked_buyer_ids`
- [x] Schema validation fail-fast — `test_schema_validation_fails_fast_on_missing_columns`
- [x] Integration: tiny fixture — `test_assemble_tiny_fixture_with_fixed_seed_writes_manifest_and_parquet`
- [x] Integration: corrupt parquet — `test_validate_raises_on_missing_return_type_with_actionable_message`
- [x] No TikTok API — `test_assembler_has_no_tiktok_api_calls`
- [x] No Postgres writes — `test_assembler_has_no_postgres_writes`

## Notes for reviewer

- First ML touch in repo; ADR-013 documents module tree policy
- `xgboost`/`scikit-learn` pinned for downstream trainers (#138–#140) but unused in dataset module
- mypy reports missing `pandas-stubs` locally; ruff clean
