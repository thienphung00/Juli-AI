# Handoff: focus → tdd — Issue #136

## Issue

- **#136** — Backtest dataset assembly (parquet + synthetic)
- **EXECUTION slice:** P1.5-1
- **Parent:** #135 · **Blocked by:** none

## Acceptance criteria

- ML module directory exists with MODULE.md; dependencies pinned in requirements
- CLI `assemble-backtest-dataset` writes manifest JSON with row counts, date range, split boundaries, and dataset version
- Parquet files: `orders.parquet`, `order_items.parquet`, `returns.parquet`, `labels.parquet`, `ads.parquet` with columns matching `system-design.md` § Return schema contract
- `labels.parquet` contains buyer-behavior labels only: `return_id`, `ground_truth_anomaly`, `return_type` (`item_swap` | `empty_return` | `other`)
- Synthetic generator produces labeled `item_swap` and `empty_return` rows at realistic prevalence; masked `buyer_id` only — no PII
- Schema manifest validation fails fast on missing columns or invalid enums
- Integration test: assemble tiny fixture dataset with fixed seed → manifest + all parquet files present
- Integration test: corrupt parquet (missing `return_type`) raises validation error with actionable message
- No TikTok API calls; no Postgres writes

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-1), `docs/system-design.md` (Return schema contract), `docs/architecture/map.md`, `docs/architecture/data-sources.md` |
| Data models | `docs/data-models/canonical-entities.md`, `docs/data-models/mock-data-generator.md` |
| Decisions | `docs/decisions/011-buyer-behavior-anomaly-scope.md`, `docs/decisions/013-phase-15-ml-module-tree.md` |
| Module | `src/modules/ml/dataset/MODULE.md` (new) |
| Domain patterns | `.cursor/skills/domain/python-patterns.md`, `.cursor/skills/domain/python-testing.md` |

## Standards applied

- Reliability — fail-fast validation, deterministic fixed-seed synthetic data
- Security — masked `buyer_id` only; no PII in parquet or logs
- Performance — bounded fixture sizes in unit tests; no unbounded result sets
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`

## Plugin skills & MCP

- None required (offline parquet I/O; no Supabase, TikTok API, or UI)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** schema contracts → synthetic generator → validation → assembler → CLI → tests

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/dataset/schema.py` | Column contracts + `REQUIRED_PARQUET_FILES` |
| `src/modules/ml/dataset/synthetic.py` | Fixed-seed synthetic orders/returns/labels/ads |
| `src/modules/ml/dataset/validation.py` | Fail-fast column + enum validation |
| `src/modules/ml/dataset/assembler.py` | `assemble_backtest_dataset` public entrypoint |
| `src/modules/ml/dataset/cli.py` | `assemble-backtest-dataset` CLI |
| `src/modules/ml/dataset/exceptions.py` | `DatasetValidationError` |
| `src/modules/ml/dataset/MODULE.md` | Public interface documentation |
| `tests/unit/test_backtest_dataset.py` | 9 integration tests mapping all ACs |
| `docs/decisions/013-phase-15-ml-module-tree.md` | ADR for ML module tree bootstrap |

### Modified files

| File | Change |
|------|--------|
| `requirements.txt` | Pin `pandas`, `pyarrow`, `scikit-learn`, `xgboost` |
| `docs/architecture/map.md` | Register `src/modules/ml/dataset` tier-2 module |

### Key patterns

- Runner-agnostic functions — no Celery/scheduler coupling (ADR-013)
- Validate before return from `assemble_backtest_dataset`; separate `validate_backtest_dataset` for downstream jobs
- No affiliate parquet in anomaly path (ADR-011)
- Do **not** extend legacy `catalog/domain/intelligence/scoring`

### Tests (TDD)

1. RED: `test_ml_module_public_interface_and_pinned_dependencies`
2. RED: `test_assemble_tiny_fixture_with_fixed_seed_writes_manifest_and_parquet`
3. RED: `test_parquet_columns_match_return_schema_contract`
4. RED: `test_labels_parquet_contains_buyer_behavior_labels_only`
5. RED: `test_synthetic_generator_produces_anomaly_labels_and_masked_buyer_ids`
6. RED: `test_schema_validation_fails_fast_on_missing_columns`
7. RED: `test_validate_raises_on_missing_return_type_with_actionable_message`
8. RED: `test_assembler_has_no_tiktok_api_calls` / `test_assembler_has_no_postgres_writes`
9. GREEN: implement schema → synthetic → validation → assembler → CLI

Run: `pytest tests/unit/test_backtest_dataset.py -v`

## DO NOT touch

- `src/modules/catalog/domain/intelligence/scoring/` — legacy; out of scope
- `src/integrations/tiktok/` — no API calls in P1.5-1
- Feature builders (`ml/features`) — #137
- Model trainers (`ml/seller_stage`, `ml/anomaly`, `ml/ad_performance`) — #138–#140
